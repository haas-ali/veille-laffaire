"""Veille d'actualité @laffaire_france — un tour complet (lancé toutes les 10 min par GitHub Actions).

1. lit les clics Telegram (PRÉPARER / APPROFONDIR / IGNORER) ;
2. lit les flux RSS, regroupe les articles par événement, note chaque événement ;
3. fait analyser les meilleurs par l'IA et envoie une alerte Telegram pour les plus forts ;
4. enregistre l'état dans donnees/etat.json.

Options : --essai (n'envoie rien, affiche les alertes), --sans-ia."""
import calendar, hashlib, json, math, os, re, sys, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

ICI = Path(__file__).parent
for ligne in (ICI / ".env").read_text(encoding="utf-8").splitlines() if (ICI / ".env").exists() else []:
    if "=" in ligne and not ligne.startswith("#"):
        k, v = ligne.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import feedparser, requests
import config, ia, selection, telegram as tg

ESSAI = "--essai" in sys.argv
if "--sans-ia" in sys.argv:
    ia.CLE = ""
ETAT = ICI / "donnees" / "etat.json"
SUJETS = ICI / "sujets"
UA = {"User-Agent": "Mozilla/5.0 (veille laffaire_france; RSS)"}
PARIS = timezone(timedelta(hours=1))  # heure d'hiver ; l'affichage n'a pas besoin de plus de précision
VIDES = set("""les des une est son ses sur aux par pour dans avec qui que quoi dont mais plus moins tres tout tous toute
toutes cette ces cet elle ils elles leur leurs etre avoir ete fait faire apres avant entre selon contre sans sous vers
chez comme quand alors deja encore aussi depuis pendant lors notre nos vos votre direct video videos photos infos info
quel quelle quels quelles comment pourquoi voici france francais francaise annee jour jours mardi mercredi jeudi
vendredi samedi dimanche lundi hier soir matin ans""".split())


def maintenant():
    return time.time()


def sans_accent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


SYNONYMES = {"ferroviaire": "train", "trains": "train", "collision": "accident", "deraillement": "accident",
             "morts": "mort", "tue": "mort", "tues": "mort", "tuee": "mort", "deces": "mort", "decede": "mort", "mortel": "mort",
             "mortelle": "mort", "feu": "incendie", "blesses": "blesse", "policiers": "police", "policier": "police"}


def mots(titre):
    m = re.findall(r"[a-z0-9]+", sans_accent(titre).replace("'", " "))
    m = [SYNONYMES.get(w, w) for w in m if len(w) >= 3 and w not in VIDES]
    return {w.rstrip("sx") if len(w) > 4 else w for w in m}


def nettoyer(html_txt):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_txt or "")).strip()


# ---------- 1. Collecte ----------

def article(nom, titre, lien, ts, pays, typ, resume=""):
    return {"id": hashlib.sha1((lien + titre).encode()).hexdigest()[:12], "titre": titre[:200], "source": nom, "lien": lien,
            "ts": ts, "pays": pays, "type": typ, "resume": resume[:600],
            "date": datetime.fromtimestamp(ts, PARIS).strftime("%d/%m %H:%M")}


def iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def lire_bluesky(nom, handle, pays, typ):
    r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed", timeout=20,
                     params={"actor": handle, "limit": 30, "filter": "posts_no_replies"})
    r.raise_for_status()
    res = []
    for it in r.json()["feed"]:
        p = it["post"]
        if it.get("reason"):  # repost
            continue
        ext = (p["record"].get("embed") or {}).get("external") or {}
        texte = re.sub(r"https?://\S+|▶️|🔴", " ", p["record"].get("text", "")).strip()
        titre = ext.get("title") or texte
        if "ALERTE" in p["record"].get("text", "") and ext.get("title"):
            titre = "ALERTE : " + ext["title"]
        lien = ext.get("uri") or f"https://bsky.app/profile/{handle}/post/{p['uri'].split('/')[-1]}"
        if titre:
            res.append(article(nom, nettoyer(titre), lien, iso(p["record"]["createdAt"]), pays, typ, texte + " " + ext.get("description", "")))
    return res


def lire_telegram(nom, canal, pays, typ):
    import html as h
    r = requests.get("https://t.me/s/" + canal, headers=UA, timeout=20)
    r.raise_for_status()
    res = []
    for bloc in r.text.split('class="tgme_widget_message_wrap')[1:]:
        post = re.search(r'data-post="([^"]+)"', bloc)
        t = re.search(r'<time datetime="([^"]+)"', bloc)
        txt = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', bloc, re.S)
        if not (post and t and txt):
            continue
        texte = h.unescape(nettoyer(txt.group(1).replace("<br/>", " ")))
        titre = texte[:160] if len(re.split(r"(?<=[.!?])\s", texte, 1)[0]) < 50 else re.split(r"(?<=[.!?])\s", texte, 1)[0]
        res.append(article(nom, titre, "https://t.me/" + post.group(1), iso(t.group(1)), pays, typ, texte))
    return res


def lire_youtube_api(nom, chaine, pays, typ, cle):
    """Dernières vidéos d'une chaîne via l'API officielle (1 unité de quota sur 10 000 par jour)."""
    r = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", timeout=20, params={
        "part": "snippet", "playlistId": "UU" + chaine[2:], "maxResults": 15, "key": cle})
    r.raise_for_status()
    import html as h
    return [article(nom, h.unescape(i["snippet"]["title"]), "https://www.youtube.com/watch?v=" + i["snippet"]["resourceId"]["videoId"],
                    iso(i["snippet"]["publishedAt"]), pays, typ, i["snippet"].get("description", "")) for i in r.json().get("items", [])]


def lire_flux(f):
    nom, url, pays, typ = f
    cle_yt = os.environ.get("YOUTUBE_API_KEY", "").strip()
    try:
        if "youtube.com/feeds" in url and cle_yt:  # les flux RSS YouTube sont bloqués depuis les serveurs GitHub
            return lire_youtube_api(nom, url.split("channel_id=")[1], pays, typ, cle_yt)
        if url.startswith("bsky:"):
            return lire_bluesky(nom, url[5:], pays, typ)
        if url.startswith("tg:"):
            return lire_telegram(nom, url[3:], pays, typ)
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        d = feedparser.parse(r.content)
    except Exception as ex:
        print(f"  ! {nom} : {ex}")
        return []
    res = []
    for x in d.entries:
        titre, source = nettoyer(x.get("title")), nom
        if "news.google" in url and " - " in titre:  # Google Actualités : « Titre - Média »
            titre, source = titre.rsplit(" - ", 1)
        t = x.get("published_parsed") or x.get("updated_parsed")
        ts = calendar.timegm(t) if t else maintenant()
        lien = x.get("link", "")
        if not titre or not lien:
            continue
        res.append({"id": hashlib.sha1((lien + titre).encode()).hexdigest()[:12], "titre": titre, "source": source,
                    "lien": lien, "ts": ts, "pays": pays, "type": typ,
                    "resume": nettoyer(x.get("summary"))[:600],
                    "date": datetime.fromtimestamp(ts, PARIS).strftime("%d/%m %H:%M")})
    return res


def collecter():
    with ThreadPoolExecutor(16) as p:
        tout = [a for lot in p.map(lire_flux, config.FLUX) for a in lot]
    limite = maintenant() - config.AGE_MAX_HEURES * 3600
    return [a for a in tout if a["ts"] >= limite]


# ---------- 2. Regroupement et note ----------

def similarite(a, b, poids):
    commun = a & b
    if len(commun) < 2:
        return 0.0
    pa, pb = sum(poids(w) for w in a), sum(poids(w) for w in b)
    return sum(poids(w) for w in commun) / max(1e-6, min(pa, pb))


def signature(ev):
    """Mots qui reviennent dans au moins un quart des titres de l'événement."""
    compte = {}
    for a in ev["articles"]:
        for w in mots(a["titre"]):
            compte[w] = compte.get(w, 0) + 1
    seuil = max(1, len(ev["articles"]) / 4) if len(ev["articles"]) > 2 else 1
    return {w for w, c in compte.items() if c >= seuil}


def regrouper(etat, nouveaux):
    evs = etat["evenements"]
    corpus = [mots(a["titre"]) for ev in evs.values() for a in ev["articles"]] + [mots(a["titre"]) for a in nouveaux]
    df = {}
    for s in corpus:
        for w in s:
            df[w] = df.get(w, 0) + 1
    n = len(corpus) + 1
    poids = lambda w: math.log(n / df.get(w, 1))
    sig = {eid: signature(ev) for eid, ev in evs.items()}
    touches = set()
    for a in sorted(nouveaux, key=lambda x: x["ts"]):
        ma = mots(a["titre"])
        meilleur, score = None, 0.0
        for eid, mb in sig.items():
            s = similarite(ma, mb, poids)
            if s > score:
                meilleur, score = eid, s
        if score < 0.4:
            meilleur = "e" + a["id"]
            evs[meilleur] = {"id": meilleur, "cree": a["ts"], "articles": [], "notifie": False, "statut": "nouveau",
                             "analyses": 0, "sources_analyse": 0}
        ev = evs[meilleur]
        ev["articles"].append(a)
        ev["maj"] = max(ev.get("maj", 0), a["ts"])
        sig[meilleur] = signature(ev)
        touches.add(meilleur)
    # fusion des événements qui parlent de la même chose (le plus ancien garde son identifiant)
    ids = sorted(touches, key=lambda e: -len(evs[e]["articles"]))
    for e1 in ids:
        if e1 not in evs:
            continue
        for e2 in list(evs):
            if e2 == e1 or e2 not in evs or e1 not in evs:
                continue
            if similarite(sig[e1], sig[e2], poids) >= 0.5:
                garde, part = (e1, e2) if evs[e1]["cree"] <= evs[e2]["cree"] else (e2, e1)
                g, p = evs[garde], evs.pop(part)
                g["articles"] += p["articles"]
                g["maj"] = max(g.get("maj", 0), p.get("maj", 0))
                g["notifie"] = g["notifie"] or p["notifie"]
                if p["statut"] != "nouveau":
                    g["statut"] = p["statut"]
                for k in ("analyse", "message_id", "dossier", "approfondi"):
                    g.setdefault(k, p.get(k))
                g["analyses"] = max(g["analyses"], p["analyses"])
                sig[garde] = signature(g)
                touches.discard(part); touches.add(garde)
                if part == e1:
                    break
    return {e for e in touches if e in evs}


def media(source):
    """« BFMTV (Bluesky) » et « BFMTV police-justice » = un seul média."""
    s = re.sub(r" \(.*|^YouTube | (police-justice|faits divers|France|flash actu|93)$", "", source).replace("BFM", "BFMTV").replace("BFMTVTV", "BFMTV")
    # même rédaction (groupe EBRA, groupe Dépêche) = une seule source
    if s in ("Le Progrès", "Le Dauphiné", "L'Est Républicain", "DNA", "Le Républicain lorrain", "Vosges Matin", "Le Bien Public", "Le JSL"):
        return "EBRA"
    if s in ("La Dépêche", "Midi Libre", "L'Indépendant", "Centre Presse"):
        return "La Dépêche"
    return s


CREATEURS = {f[0] for f in config.FLUX if f[0].startswith("YouTube ") and f[0].split(" ", 1)[1] in ("Inoxtag", "Squeezie", "Michou", "LeBouseuh", "Gotaga", "Fortnite", "Tibo InShape", "Cyprien", "Joyca", "Mastu")}


def noter(ev):
    texte = " " + sans_accent(" ".join(a["titre"] + " " + a["resume"][:200] for a in ev["articles"][:8])) + " "
    s = 0.0
    for pts, liste in config.MOTS.items():
        for m in liste:
            if re.search(r"(?<![a-z])" + re.escape(m) + r"(?![a-z])", texte):
                s += pts
    s = min(s, 12)
    nb_sources = len({media(a["source"]) for a in ev["articles"]})
    s += min(6, 1.5 * (nb_sources - 1))
    if any(a["type"] == "video" for a in ev["articles"]):
        s += 1
    if any(a["source"] in CREATEURS for a in ev["articles"]):
        s += 4  # annonce d'un créateur suivi : l'IA décide ensuite si c'est important ou banal
    if all(a["pays"] != "FR" for a in ev["articles"]):
        s -= 1
    ev["score"] = round(s, 1)
    ev["nb_sources"] = nb_sources
    return s


# ---------- 3. Alertes ----------

CONNUS = {f[0] for f in config.FLUX if "non vérifié" not in f[0]} | {"BFM", "BFMTV", "Le Monde", "Le Figaro", "Le Parisien", "franceinfo", "20 Minutes",
                                      "Ouest-France", "Libération", "France 24", "Euronews", "Sud Ouest", "Le Point", "L'Express",
                                      "TF1 Info", "LCI", "CNEWS", "RTL", "Europe 1", "RMC", "Nice-Matin", "Var-Matin", "Le Progrès",
                                      "La Voix du Nord", "Actu.fr", "actu.fr", "AFP", "Reuters", "Le JDD", "Mediapart", "Marianne"}


def doit_analyser(ev):
    if ev["statut"] != "nouveau" or ev["notifie"] or ev["analyses"] >= 3:
        return False
    if ev["nb_sources"] < 2 and ev["articles"][0]["source"] not in CONNUS:
        return False  # une seule source inconnue (site douteux remonté par Google) : on attend une confirmation
    if ev["analyses"] == 0:
        return ev["score"] >= config.SEUIL_ANALYSE
    return ev["nb_sources"] >= ev["sources_analyse"] + 3  # l'événement a beaucoup grossi : on redemande


try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Paris")  # erreur ici (et non plus tard) si la base des fuseaux manque
    HEURE_PARIS = lambda: datetime.now(_TZ)
except Exception:  # Windows sans base des fuseaux : heure d'hiver
    HEURE_PARIS = lambda: datetime.now(PARIS)


def rarete(textes):
    """Fréquence des mots dans une liste de titres : sert à repérer les mots RARES (noms propres, lieux…)."""
    df = {}
    for t in textes:
        for w in mots(t):
            df[w] = df.get(w, 0) + 1
    return df, max(3, len(textes) // 200)  # un mot est rare s'il apparaît dans au plus 0,5 % des titres (3 au minimum)


def meme_sujet(ma, texte, df, seuil):
    """Même sujet = au moins 2 mots rares en commun (ex. « maeva » + « ghennam »)."""
    return len({w for w in ma & mots(texte) if len(w) >= 4 and df.get(w, 0) <= seuil}) >= 2


def pourcentages(ev):
    """(% de viralité, % de couverture médias, nombre de médias).
    Viralité : note IA + vidéos disponibles + nombre de médias qui en parlent depuis 3 h (l'info s'emballe) + fait grave.
    Couverture : nombre de médias différents qui en parlent, 15 médias = 100 %."""
    a = ev.get("analyse") or {}
    n = len({media(x["source"]) for x in ev["articles"]})
    recents = len({media(x["source"]) for x in ev["articles"] if x["ts"] >= maintenant() - 3 * 3600})
    v = (a.get("score_tiktok") or 0) * 8 + (5 if any(x["type"] == "video" for x in ev["articles"]) or ev.get("videos_yt") else 0)
    v += min(12, recents * 2) + (4 if ev.get("urgent") else 0)
    # comptes TikTok d'actu (bot viral, 48 h) qui ont fait une vidéo sur le même sujet
    tt = 0
    f = ICI / "donnees" / "viral.json"
    if f.exists():
        ma = mots(" ".join(x["titre"] for x in ev["articles"][:6]) + " " + (a.get("titre") or ""))
        lim = maintenant() - 48 * 3600
        vids = [x for x in json.loads(f.read_text(encoding="utf-8-sig")).get("videos", {}).values() if x.get("compte") and x.get("ts", 0) >= lim]
        df, seuil = rarete([x.get("titre", "") for x in vids])
        tt = len({x["compte"] for x in vids if meme_sujet(ma, x.get("titre", ""), df, seuil)})
    return max(5, min(99, round(v))), min(100, round((n + tt) / 15 * 100)), n, tt


def est_urgent(ev):
    """Actu grave qui fait beaucoup de vues : l'IA le dit, ou les titres contiennent un mot grave (attentat, meurtre, racisme…)."""
    a = ev.get("analyse") or {}
    if (a.get("score_tiktok") or 0) < config.SEUIL_URGENT or a.get("zone") == "Monde":
        return False
    texte = " " + sans_accent(" ".join(x["titre"] for x in ev["articles"][:10])) + " "
    mots = any(re.search(r"(?<![a-z])" + re.escape(m.rstrip("*")) + ("" if m.endswith("*") else r"(?![a-z])"), texte) for m in config.MOTS_URGENTS)
    return bool(a.get("urgent")) or mots


def seuil_actuel(etat):
    """Note minimale pour alerter : /pause coupe tout, la nuit (0 h-7 h) seuls les 9-10/10 passent, sinon le /seuil choisi."""
    if etat.get("pause"):
        return 99
    s = etat.get("seuil", config.SEUIL_NOTIF_IA)
    return max(s, 9) if HEURE_PARIS().hour < 7 else s


def alerter(ev):
    try:
        ev["videos_yt"] = recherche_youtube(ev)[:4]  # vraies vidéos YouTube récentes sur le sujet (clé gratuite)
    except Exception as ex:
        print("  ! YouTube :", ex)
    msg = tg.texte_dernier(ev)
    a = ev.get("analyse") or {}
    art = next((x for x in ev["articles"] if x["type"] == "article"), ev["articles"][0])
    date_lieu = ", ".join(x for x in (a.get("date_faits"), a.get("lieu")) if x) or "date et lieu à vérifier"
    copie = selection.texte_copie(a.get("titre") or art["titre"], a.get("resume"), date_lieu, ev.get("score100"), ev.get("fiab"), art["lien"])
    if ESSAI:
        print("\n" + "=" * 70 + "\n" + re.sub(r"<[^>]+>", "", msg) + "\n[COPIER] " + copie)
        return
    ev["copie"] = copie
    ev["message_id"] = tg.envoyer(msg, clavier=tg.boutons_dernier(ev["id"], copie))


def gouts(etat):
    """Ce que l'utilisateur prépare ou ignore, par catégorie (appris de ses clics)."""
    p = etat.get("gouts", {})
    return "; ".join(f"{c} : {v.get('prep', 0)} préparé(s), {v.get('ign', 0)} ignoré(s)" for c, v in p.items()) or ""


def noter_clic(etat, ev, action):
    cat = (ev.get("analyse") or {}).get("categorie") or "autre"
    g = etat.setdefault("gouts", {}).setdefault(cat, {})
    g[action] = g.get(action, 0) + 1


def resume_du_matin(etat):
    """Vers 8 h (heure de Paris), un message avec les 5 sujets les plus forts des 12 dernières heures."""
    now = datetime.now(PARIS)
    if now.hour != 8 or etat.get("resume_jour") == now.strftime("%Y-%m-%d"):
        return
    depuis = maintenant() - 12 * 3600
    evs = [ev for ev in etat["evenements"].values() if ev.get("maj", 0) >= depuis and ev["statut"] != "ignore"]
    evs.sort(key=lambda ev: (-((ev.get("analyse") or {}).get("score_tiktok") or 0), -ev.get("score", 0)))
    lignes = [f"☀️ <b>Les sujets forts de la nuit</b> ({now.strftime('%d/%m')})"]
    for ev in evs[:5]:
        a = ev.get("analyse") or {}
        note = f"{a['score_tiktok']}/10" if a.get("score_tiktok") is not None else "—"
        lignes.append(f"\n• <b>{tg.e(a.get('titre') or ev['articles'][0]['titre'])}</b> — {note}, {ev['nb_sources']} sources")
    if len(lignes) > 1 and not ESSAI:
        tg.envoyer(tg.assembler(lignes))
    etat["resume_jour"] = now.strftime("%Y-%m-%d")


def decider(ev, etat, deja=()):
    """Bot « Dernière info » : envoie seulement 🟢 vert ou 🔴 rouge, une seule fois par affaire (sauf rebondissement majeur).
    Mémoire durable des alertes envoyées : etat["envoyes"] (branche « etat », survit aux redémarrages)."""
    a = ev.get("analyse") or {}
    titre = a.get("titre") or ev["articles"][0]["titre"]
    envoyes = etat.setdefault("envoyes", [])
    age_h = (maintenant() - min(x["ts"] for x in ev["articles"])) / 3600
    _, _, nb_medias, nb_tiktok = pourcentages(ev)
    recents = len({media(x["source"]) for x in ev["articles"] if x["ts"] >= maintenant() - 3 * 3600})
    rebond = bool(a.get("rebondissement_majeur"))
    precedent = selection.deja_envoye(a, envoyes, mots(titre))
    d = a.get("doublon_de")  # l'IA reconnaît aussi une alerte déjà envoyée (confirmé par des mots communs)
    if not precedent and isinstance(d, int) and 0 <= d < len(deja) and len(signature(ev) & signature(deja[d])) >= 2:
        precedent = {"id": deja[d]["id"], "titre": (deja[d].get("analyse") or {}).get("titre") or deja[d]["articles"][0]["titre"]}
    score, detail = selection.score100(ev, nb_medias, nb_tiktok, recents, age_h, a, deja_couvert=bool(precedent))
    fiab = selection.fiabilite(ev, a, nb_medias)
    nuit = HEURE_PARIS().hour < 7
    c = selection.couleur(score, a, fiab, nuit, etat.get("seuil100"))
    raison = ("doublon" if precedent and not rebond else "trop ancien" if age_h > selection.AGE_MAX_SANS_REBOND and not rebond
              else "pause" if etat.get("pause") else None if c else f"score {score} trop bas")
    print(f"  {score:3}/100 {c or '-':5} {fiab:12} {('→ ' + raison) if raison else '→ ENVOI'} | {titre[:70]}")
    ev.update(score100=score, detail100=detail, fiab=fiab, couleur=c)
    if raison:
        if precedent and not rebond:
            ev["notifie"], ev["doublon_de"] = True, precedent.get("id")
        return False
    ev["rebond_de"] = precedent.get("titre") if precedent else None
    ev["interet"] = selection.interet_mediatique(nb_medias, nb_tiktok)
    # verrou anti-doublon AVANT l'envoi : une 2e fiche de la même affaire dans ce tour sera reconnue
    pers, lieux = selection.entites(a)
    envoyes.append({"id": ev["id"], "ts": maintenant(), "titre": titre, "cle": selection.cle_affaire(a),
                    "personnes": sorted(pers), "lieux": sorted(lieux), "mots": sorted(mots(titre)), "couleur": c})
    del envoyes[:-300]
    ev["notifie"] = True
    alerter(ev)
    return True


def traiter_alertes(etat, touches, premier_tour):
    candidats = sorted((etat["evenements"][e] for e in touches), key=lambda ev: -ev["score"])
    candidats = [ev for ev in candidats if doit_analyser(ev)]
    if premier_tour:
        candidats = candidats[:3]  # pas d'avalanche au démarrage
    analyses = 0
    limite = maintenant() - 86400
    lot = candidats[:config.MAX_ANALYSES_PAR_TOUR] if ia.CLE else []
    deja_tous = [x for x in etat["evenements"].values() if x["notifie"] and x.get("maj", 0) >= limite]

    def analyse(ev):  # les analyses IA du tour partent en même temps (le tour cloud doit rester < 60 s)
        deja = [x for x in deja_tous if x is not ev]
        try:
            return ev, deja, ia.analyser(ev, [(x.get("analyse") or {}).get("titre") or x["articles"][0]["titre"] for x in deja], gouts(etat))
        except Exception as ex:
            return ev, deja, ex

    with ThreadPoolExecutor(4) as p:
        resultats = list(p.map(analyse, lot))
    for ev in candidats:
        if ia.CLE and analyses < len(resultats):
            _, deja, res = resultats[analyses]
            analyses += 1
            if isinstance(res, ia.QuotaEpuise):
                print("  ! quota IA atteint, on reprendra au prochain tour")
                continue
            if isinstance(res, Exception):
                print("  ! IA :", res)
                continue
            ev["analyse"] = res or ev.get("analyse")
            ev["analyses"] += 1
            ev["sources_analyse"] = ev["nb_sources"]
            decider(ev, etat, deja)
        elif not ia.CLE and ev["score"] >= config.SEUIL_NOTIF_SANS_IA:
            ev["analyses"] = 3; decider(ev, etat)


# ---------- 4. Boutons ----------

def recherche_gnews(ev):
    """Autres articles sur le même sujet via Google Actualités (sources réelles)."""
    a = ev.get("analyse") or {}
    cles = sorted(mots(a.get("titre") or ev["articles"][0]["titre"]), key=len, reverse=True)[:5]
    url = f"https://news.google.com/rss/search?q={quote(' '.join(cles))}+when:3d&hl=fr&gl=FR&ceid=FR:fr"
    return lire_flux(("Google Actualités", url, "FR", "article"))[:15]


def recherche_youtube(ev):
    cle = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not cle:
        return []
    a = ev.get("analyse") or {}
    q = (a.get("recherche_video") or [a.get("titre") or ev["articles"][0]["titre"]])[0]
    depuis = datetime.fromtimestamp(maintenant() - 4 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get("https://www.googleapis.com/youtube/v3/search", timeout=20, params={
        "part": "snippet", "q": q, "type": "video", "order": "relevance", "publishedAfter": depuis, "maxResults": 8,
        "relevanceLanguage": "fr", "key": cle})
    if r.status_code != 200:
        print("  ! YouTube :", r.text[:200])
        return []
    return [{"titre": i["snippet"]["title"], "chaine": i["snippet"]["channelTitle"],
             "lien": "https://www.youtube.com/watch?v=" + i["id"]["videoId"]} for i in r.json().get("items", [])]


def approfondir(ev):
    plus = {"articles": [], "videos_youtube": recherche_youtube(ev), "ia": None, "sources_web": []}
    deja = {a["lien"] for a in ev["articles"]}
    plus["articles"] = [a for a in recherche_gnews(ev) if a["lien"] not in deja]
    if ia.CLE:
        try:
            plus["ia"], plus["sources_web"] = ia.approfondir(ev)
        except Exception as ex:
            print("  ! IA approfondir :", ex)
        if not plus["ia"] and plus["articles"]:
            # recherche Google de l'IA indisponible (quota) : l'IA relit tous les articles, anciens + nouveaux trouvés
            try:
                a = ia.analyser({"articles": ev["articles"] + plus["articles"]}) or {}
                plus["ia"] = {"nouveaux_elements": [a["nouveau"]] if a.get("nouveau") else [], "faits_confirmes": a.get("faits_confirmes"),
                              "incertain": a.get("incertain"), "score_tiktok": a.get("score_tiktok"), "angle": a.get("angle")}
            except Exception as ex:
                print("  ! IA approfondir (articles) :", ex)
    ev["approfondi"] = plus
    return plus


def texte_approfondi(ev, p):
    e = tg.e
    t = ["🔎 <b>Recherche approfondie</b>"]
    r = p.get("ia") or {}
    for cle, titre in [("nouveaux_elements", "🆕 Nouveaux éléments"), ("officiel", "🏛️ Officiel"),
                       ("faits_confirmes", "✅ Confirmé"), ("incertain", "❓ Incertain")]:
        if r.get(cle):
            t.append(f"\n<b>{titre}</b>\n" + "\n".join("• " + e(x) for x in r[cle][:5]))
    if r.get("videos"):
        t.append("\n<b>🎥 Vidéos signalées</b>\n" + "\n".join(
            f"• {e(v.get('plateforme'))} {e(v.get('compte') or '')} : {e(v.get('description'))}" for v in r["videos"][:5]))
    if p["videos_youtube"]:
        t.append("\n<b>▶️ YouTube</b>\n" + "\n".join(f'• <a href="{e(v["lien"])}">{e(v["chaine"])} : {e(v["titre"][:60])}</a>' for v in p["videos_youtube"][:5]))
    sources = [(a["source"], a["lien"]) for a in p["articles"][:6]] + p["sources_web"][:6]
    if sources:
        t.append("\n<b>📰 Sources</b>\n" + "\n".join(f'• <a href="{e(u)}">{e(n or "lien")}</a>' for n, u in sources))
    if r.get("score_tiktok") is not None:
        t.append(f"\nNouvelle note TikTok : <b>{r['score_tiktok']}/10</b>")
    if len(t) == 1:
        t.append("Rien de nouveau trouvé pour l'instant.")
    return tg.assembler(t)


def nom_dossier(ev, titre):
    d = datetime.fromtimestamp(ev["cree"], PARIS).strftime("%Y-%m-%d")
    return d + "_" + (re.sub(r"[^a-z0-9]+", "-", sans_accent(titre)).strip("-")[:50] or ev["id"])


def preparer(ev, modele=2):
    """Crée sujets/<date>_<titre>/ avec le dossier de montage (modèle 1, 2 ou 3 choisi sur Telegram). Renvoie le chemin."""
    extra = ev.get("approfondi") or approfondir(ev)
    plan = None
    if ia.CLE:
        try:
            infos = {"articles": [a["titre"] + " (" + a["source"] + ")" for a in extra["articles"]], "ia": extra.get("ia")}
            plan = ia.preparer(ev, infos, modele)
            for _ in range(2):  # script trop court = vidéo de moins de 61 s : on redemande
                nb = sum(len(x.split()) for x in (plan or {}).get("parts") or [])
                if nb >= 160 or not plan:
                    break
                print(f"  script trop court ({nb} mots), on redemande")
                infos["consigne"] = f"Ta version précédente faisait {nb} mots : TROP COURT. Écris entre 170 et 190 mots, avec plus de détails tirés des articles (sans rien inventer)."
                plan = ia.preparer(ev, infos, modele) or plan
        except Exception as ex:
            print("  ! IA préparer :", ex)
    plan = plan or {}
    a = ev.get("analyse") or {}
    titre = plan.get("titre_court") or a.get("titre") or ev["articles"][0]["titre"]
    dos = SUJETS / nom_dossier(ev, titre)
    dos.mkdir(parents=True, exist_ok=True)
    articles = ev["articles"] + extra["articles"]
    videos = [x for x in articles if x["type"] == "video"] + [{"titre": v["titre"], "source": v["chaine"], "lien": v["lien"]} for v in extra["videos_youtube"]]
    sujet = {"id": ev["id"], "titre": titre, "modele": modele, "prepare_le": datetime.now(PARIS).isoformat(timespec="minutes"),
             "analyse": a, "plan": plan, "approfondi": extra.get("ia"), "sources_web": extra.get("sources_web"),
             "articles": [{k: x[k] for k in ("source", "titre", "lien", "date")} for x in articles if x["type"] == "article"],
             "videos": [{k: x[k] for k in ("source", "titre", "lien")} for x in videos],
             "recherche_video": plan.get("recherche_video") or a.get("recherche_video") or [titre]}
    (dos / "sujet.json").write_text(json.dumps(sujet, ensure_ascii=False, indent=1), encoding="utf-8")
    if plan.get("parts"):
        (dos / "parts.json").write_text(json.dumps(plan["parts"], ensure_ascii=False, indent=1), encoding="utf-8")
    if plan.get("description"):
        tags = " ".join([h for h in plan.get("hashtags", [])[:5] if h.lower() != "#laffaire_france"] + ["#laffaire_france"])
        (dos / "description_tiktok.txt").write_text(plan["description"] + "\n\n" + tags + "\n", encoding="utf-8")
    (dos / "dossier.md").write_text(dossier_md(sujet), encoding="utf-8")
    return dos


def dossier_md(s):
    a, p = s["analyse"], s["plan"]
    L = [f"# {s['titre']}", "", f"Préparé le {s['prepare_le']} par la veille automatique. **À vérifier avant montage : rien n'est publié automatiquement.**", ""]
    if a:
        L += ["## Ce qui se passe", a.get("resume") or "", "", f"- Lieu : {a.get('lieu')}", f"- Heure : {a.get('heure')}",
              f"- Potentiel TikTok : {a.get('score_tiktok')}/10 — {a.get('raison_score')}", ""]
        L += ["### Confirmé"] + [f"- {x}" for x in a.get("faits_confirmes") or []] + ["", "### Incertain"] + [f"- {x}" for x in a.get("incertain") or []] + [""]
    if s.get("approfondi"):
        r = s["approfondi"]
        L += ["## Recherche approfondie"] + [f"- {x}" for x in (r.get("nouveaux_elements") or []) + (r.get("officiel") or [])] + [""]
    if p:
        L += [f"## Modèle conseillé : n° {p.get('modele_conseille', 2)}", "", "## Titre à l'écran", f"**{p.get('titre_ecran')}**", f"_{p.get('ligne_grise')}_", "",
              "## Voix off (parts.json)"]
        L += [f"{i + 1}. {x}" for i, x in enumerate(p.get("parts") or [])]
        nb = sum(len(x.split()) for x in p.get("parts") or [])
        L += ["", f"({nb} mots — viser 155 à 185 pour 61 s minimum)", "", "## Plans, zooms, effets"]
        L += [f"- Partie {x.get('partie')} : {x.get('images')} — effet : {x.get('effet')} — texte : {x.get('incrustation')}" for x in p.get("plans") or []]
        m = p.get("miniature") or {}
        L += ["", "## Miniature", f"`\"{m.get('lignes')}\" \"{m.get('sous_titre')}\"`", "", "## Description TikTok", p.get("description") or "",
              " ".join(p.get("hashtags") or []) + " #laffaire_france", "", "## À vérifier"] + [f"- {x}" for x in p.get("a_verifier") or []]
    L += ["", "## Vidéos"] + [f"- [{v['source']} : {v['titre']}]({v['lien']})" for v in s["videos"]]
    L += ["", "Requêtes pour chercher la vidéo originale :"] + [f"- `{q}`" for q in s["recherche_video"]]
    L += ["", "## Sources"] + [f"- [{x['source']}]({x['lien']}) — {x['titre']} ({x['date']})" for x in s["articles"]]
    L += [f"- [{n or 'web'}]({u})" for n, u in s.get("sources_web") or []]
    return "\n".join(L) + "\n"


AIDE = """🤖 <b>Dernière info 🚨 — commandes</b> (réponse au prochain tour, 30 min max)
/statut — état de la veille
/pause — coupe les alertes · /reprise — les remet
/seuil 80 — alertes 🟢 seulement à partir de 80/100 (actuel : {seuil})
/sujets — derniers sujets préparés
Seulement 🟢 (fort potentiel) et 🔴 (urgent / rebondissement majeur). La nuit (0 h-7 h) : 🔴 et 🟢 très forts seulement."""


def demander(etat, eid, demande):
    """Note une demande (refaire / modifier) pour la tâche du PC dans sujets/demandes.json."""
    ev = etat["evenements"].get(eid)
    if not ev or not ev.get("dossier"):
        return False
    f = SUJETS / "demandes.json"
    d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    n = d.get(ev["dossier"], {}).get("n", 0) + 1
    d[ev["dossier"]] = {"n": n, "date": datetime.now(PARIS).isoformat(timespec="minutes"), **demande}
    SUJETS.mkdir(exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def commande(etat, texte, cite):
    attente = etat.setdefault("attente_modif", {})
    if cite and str(cite) in attente:  # réponse au message « ✏️ dis-moi quoi changer »
        eid = attente.pop(str(cite))
        ok = demander(etat, eid, {"type": "modif", "texte": texte})
        tg.envoyer("✏️ Modification notée : la vidéo sera refaite par la tâche du PC (PC + appli Claude ouverts)." if ok else "Sujet introuvable (trop ancien).")
        return
    mot, _, reste = texte.partition(" ")
    mot = mot.lower().split("@")[0]
    if not mot.startswith("/") and mot in ("start", "aide", "help", "pause", "reprise", "seuil", "statut", "sujets"):
        mot = "/" + mot  # « Statut » sans la barre marche aussi
    if mot in ("/start", "/aide", "/help"):
        tg.envoyer(AIDE.format(seuil=etat.get("seuil100", selection.SEUIL_VERT)))
    elif mot == "/pause":
        etat["pause"] = True; tg.envoyer("⏸️ Alertes en pause. Tape /reprise pour les remettre.")
    elif mot == "/reprise":
        etat["pause"] = False; tg.envoyer("▶️ Alertes reprises.")
    elif mot == "/seuil":
        try:
            n = int(reste.strip()); n = n * 10 if n <= 10 else n; assert 30 <= n <= 100
            etat["seuil100"] = n; tg.envoyer(f"🎚️ Seuil réglé : alertes 🟢 à partir de {n}/100 (le 🔴 urgent passe toujours).")
        except (ValueError, AssertionError):
            tg.envoyer("Écris par exemple : /seuil 80 (un nombre de 30 à 100).")
    elif mot == "/statut":
        h = maintenant() - 86400
        nb = sum(1 for v in etat["evenements"].values() if v["notifie"] and not v.get("doublon_de") and v.get("maj", 0) >= h)
        nuit = HEURE_PARIS().hour < 7
        tg.envoyer(f"📊 <b>Dernière info</b> : {'⏸️ en pause' if etat.get('pause') else '▶️ active'}{' · 🌙 mode nuit' if nuit else ''}\n"
                   f"Seuil 🟢 : {etat.get('seuil100', selection.SEUIL_VERT)}/100 · {len(etat['evenements'])} événements suivis · {nb} alertes en 24 h")
    elif mot == "/sujets":
        prep = sorted((v for v in etat["evenements"].values() if v["statut"] == "prepare"), key=lambda v: -v["cree"])[:10]
        tg.envoyer("🎬 <b>Sujets préparés</b>\n" + ("\n".join(f"• {tg.e(v['dossier'])}" for v in prep) or "aucun pour l'instant"))
    elif texte.startswith("/"):
        tg.envoyer("Commande inconnue. Tape /aide.")


def traiter_clics(etat):
    if ESSAI or not tg.TOKEN:
        return
    liste, msgs, etat["offset"] = tg.clics(etat.get("offset", 0))
    for texte, cite in msgs:
        commande(etat, texte, cite)
    for id_clic, action, eid, mid in liste:
        if action == "refaire":
            ok = demander(etat, eid, {"type": "refaire"})
            tg.repondre_clic(id_clic, "Vidéo à refaire : notée" if ok else "Sujet introuvable")
            if ok: tg.envoyer("🔁 Je refais la vidéo dès que le PC et l'appli Claude sont ouverts.", reponse_a=mid)
            continue
        if action == "modif":
            tg.repondre_clic(id_clic, "Dis-moi quoi changer")
            m = tg.api("sendMessage", chat_id=tg.CHAT, text="✏️ Réponds à CE message avec ce qu'il faut changer (texte, faits, images…).",
                       reply_markup={"force_reply": True, "input_field_placeholder": "Ce qu'il faut changer"})
            etat.setdefault("attente_modif", {})[str(m["message_id"])] = eid
            continue
        ev = etat["evenements"].get(eid)
        if not ev:
            tg.repondre_clic(id_clic, "Événement expiré (plus de 3 jours).")
            continue
        if action == "ign":
            ev["statut"] = "ignore"; noter_clic(etat, ev, "ign")
            tg.repondre_clic(id_clic, "Ignoré"); tg.marquer(mid, "✖️ Ignoré")
        elif action == "plus":
            tg.repondre_clic(id_clic, "Recherche en cours…")
            tg.envoyer(texte_approfondi(ev, approfondir(ev)), ev["id"], reponse_a=mid)
        elif action.startswith("prep"):  # prep1..prep4 = modèle de montage choisi (« prep » seul : anciennes alertes)
            modele = int(action[4:] or 2)
            if ev["statut"] == "prepare":  # double clic ou 2e modèle : pas de 2e génération du même sujet
                tg.repondre_clic(id_clic, f"Déjà lancé (modèle {ev.get('modele', '?')}) — dossier {ev.get('dossier', '')}")
                continue
            ev["statut"], ev["modele"] = "prepare", modele  # verrou posé AVANT le travail (clics répétés pendant la préparation)
            tg.repondre_clic(id_clic, f"Modèle {modele} : préparation du dossier…")
            try:
                dos = preparer(ev, modele)
            except Exception as ex:
                ev["statut"] = "nouveau"
                tg.envoyer(f"❌ Échec de la préparation (modèle {modele}) : {tg.e(str(ex)[:150])}", reponse_a=mid)
                continue
            ev["dossier"] = dos.name; noter_clic(etat, ev, "prep")
            tg.marquer(mid, f"⏳ Modèle {modele} : en attente du montage", ev.get("copie"))
            tg.envoyer_fichier(dos / "dossier.md", f"⏳ En attente — modèle {modele}\nDossier prêt : {dos.name}\n\nLe montage se fait sur ton PC "
                               f"(appli Claude ouverte). Pour le lancer tout de suite, dis à Claude : « prépare le sujet {dos.name} ».\n"
                               "Tu recevras ici « ⏳ en cours » puis la vidéo, la miniature et la description. Rien n'est publié sans toi.")


# ---------- Tour complet ----------

def main():
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {"vus": {}, "evenements": {}, "offset": 0}
    premier_tour = not etat["vus"]
    traiter_clics(etat)
    articles = collecter()
    nouveaux = [a for a in articles if a["id"] not in etat["vus"]]
    for a in nouveaux:
        etat["vus"][a["id"]] = a["ts"]
    print(f"{len(articles)} articles lus, {len(nouveaux)} nouveaux")
    touches = regrouper(etat, nouveaux)
    for eid in touches:
        noter(etat["evenements"][eid])
    traiter_alertes(etat, touches, premier_tour)
    resume_du_matin(etat)
    # ménage : on oublie ce qui est trop vieux
    limite = maintenant() - config.GARDER_HEURES * 3600
    etat["evenements"] = {k: v for k, v in etat["evenements"].items() if v.get("maj", v["cree"]) >= limite or v["statut"] == "prepare" and v["cree"] >= limite - 4 * 86400}
    etat["vus"] = {k: t for k, t in etat["vus"].items() if t >= limite - 86400}
    if not ESSAI:
        ETAT.parent.mkdir(exist_ok=True)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    top = sorted(etat["evenements"].values(), key=lambda ev: -ev.get("score", 0))[:12]
    print("\nÉvénements les mieux notés :")
    for ev in top:
        print(f"  {ev.get('score', 0):5.1f} | {ev['nb_sources']:2} sources | {ev['articles'][0]['titre'][:90]}")


if __name__ == "__main__":
    main()
