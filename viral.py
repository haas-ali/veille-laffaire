"""Bot « Viral L'Affaire » (@laffaire_viral_bot) : repère les vidéos qui explosent en France en très peu de temps.

Source : API officielle YouTube (tendances France par catégorie + chaînes suivies), car TikTok/Instagram/X ne laissent pas lire leurs
tendances gratuitement. Pour chaque vidéo : vues par heure (et accélération entre deux tours), taux d'interaction, vues comparées au
nombre d'abonnés. L'IA explique pourquoi elle buzze et comment la refaire pour @laffaire_france. Boutons Modèle 1/2/3 = même chemin
que la veille (dossier dans sujets/, puis tâche automatique du PC).
Lancé après veille.py dans le même tour GitHub Actions. Option : --essai (n'envoie rien, n'enregistre rien)."""
import json, math, os, re, sys, time
from datetime import datetime, timezone
import requests
import veille as V  # charge .env, mots(), preparer()…
import config, ia
import telegram as tg

ESSAI = "--essai" in sys.argv
ETAT = V.ICI / "donnees" / "viral.json"
CLE_YT = os.environ.get("YOUTUBE_API_KEY", "").strip()
YT = "https://www.googleapis.com/youtube/v3/"
CATEGORIES = ["0", "25", "24", "22", "23", "17"]  # tout, actu/politique, divertissement, gens & blogs, humour, sport
EXCLUS = re.compile(r"trailer|bande[- ]annonce|official (music )?video|clip officiel|lyrics|audio officiel|teaser", re.I)
FRANCAIS = re.compile(r"\b(le|la|les|des|une|est|pour|avec|dans|sur|qui|pas|c'est|il|elle)\b|[éèàçù]", re.I)
DUREE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

# le bot viral a son propre jeton (meme discussion)
tg.TOKEN = os.environ.get("TELEGRAM_TOKEN_VIRAL", "").strip()
tg.API = f"https://api.telegram.org/bot{tg.TOKEN}/"


def yt(chemin, **p):
    r = requests.get(YT + chemin, params={**p, "key": CLE_YT}, timeout=20)
    if r.status_code != 200:  # message sans l'URL (elle contient la clé)
        raise requests.HTTPError(f"YouTube {chemin} {r.status_code} : {r.text[:150]}")
    return r.json().get("items", [])


def secondes(d):
    m_ = DUREE.search(d or "")  # « P1DT2H… » pour les longs directs
    if not m_:
        return 0
    h, m, s = (int(x or 0) for x in m_.groups())
    return h * 3600 + m * 60 + s + (86400 if "D" in (d or "").split("T")[0] else 0)


def collecter():
    vids = {}
    for cat in CATEGORIES:
        p = {"part": "snippet,statistics,contentDetails", "chart": "mostPopular", "regionCode": "FR", "maxResults": 50}
        if cat != "0":
            p["videoCategoryId"] = cat
        try:
            for v in yt("videos", **p):
                vids[v["id"]] = v
        except requests.HTTPError as ex:
            print("  ! tendances", cat, ex)
    # dernières vidéos des chaînes d'info suivies par la veille (1 unité par chaîne)
    ids = []
    for nom, url, pays, typ in config.FLUX:
        if "channel_id=" in url:
            try:
                ids += [i["snippet"]["resourceId"]["videoId"] for i in yt("playlistItems", part="snippet", maxResults=10,
                                                                         playlistId="UU" + url.split("channel_id=")[1][2:])]
            except requests.HTTPError:
                pass
    ids = [i for i in ids if i not in vids]
    for k in range(0, len(ids), 50):
        for v in yt("videos", part="snippet,statistics,contentDetails", id=",".join(ids[k:k + 50])):
            vids[v["id"]] = v
    # abonnés des chaînes (pour repérer les vidéos qui font bien plus de vues que d'habitude)
    chaines = list({v["snippet"]["channelId"] for v in vids.values()})
    abonnes = {}
    for k in range(0, len(chaines), 50):
        for c in yt("channels", part="statistics", id=",".join(chaines[k:k + 50])):
            s = c["statistics"]
            if not s.get("hiddenSubscriberCount"):
                abonnes[c["id"]] = int(s.get("subscriberCount", 0))
    return vids, abonnes


def francais(v):
    sn = v["snippet"]
    lang = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
    return lang.startswith("fr") or (not lang and len(FRANCAIS.findall(sn["title"] + " " + sn.get("description", "")[:300])) >= 3)


def mesurer(v, abonnes, etat):
    sn, st = v["snippet"], v["statistics"]
    now = time.time()
    age = max((now - V.iso(sn["publishedAt"])) / 3600, 0.3)
    vues = int(st.get("viewCount", 0)); inter = int(st.get("likeCount", 0)) + int(st.get("commentCount", 0))
    mem = etat["videos"].setdefault(v["id"], {"snap": []})
    snap = mem["snap"]
    vitesse = vues / age
    if snap and now - snap[-1][0] >= 1200:  # accélération réelle depuis le dernier tour (≥ 20 min)
        vitesse = max(vitesse, (vues - snap[-1][1]) / ((now - snap[-1][0]) / 3600))
    if not snap or now - snap[-1][0] >= 1200:
        snap.append([now, vues]); del snap[:-6]
    ab = abonnes.get(sn["channelId"])
    ratio = vues / ab if ab else None
    eng = inter / max(vues, 1)
    note = min(5, max(0, (math.log10(max(vitesse, 1)) - 3) * 2.5))   # 1 000 vues/h → 0 ; 10 000 → 2,5 ; 100 000 → 5
    note += min(3, ratio * 2) if ratio else 0                          # autant de vues que d'abonnés → +2
    note += min(2, max(0, (eng - 0.02) * 50))                          # 6 % d'interactions → +2
    mem.update(titre=sn["title"], maj=now)
    return {"id": v["id"], "titre": sn["title"], "chaine": sn["channelTitle"], "desc": sn.get("description", "")[:900],
            "tags": sn.get("tags", [])[:15], "cat": sn.get("categoryId"), "age": age, "vues": vues, "vitesse": vitesse,
            "eng": eng, "ratio": ratio, "abonnes": ab, "duree": secondes(v["contentDetails"].get("duration")),
            "pub": sn["publishedAt"], "note": round(note, 1), "lien": f"https://www.youtube.com/watch?v={v['id']}"}


def analyser(m):
    prompt = f"""Tu aides le créateur TikTok « L'Affaire » (@laffaire_france, actu France : faits divers, politique, célébrités, insolite).
Cette vidéo YouTube explose en France en ce moment :
- titre : {m['titre']}
- chaîne : {m['chaine']} ({m['abonnes'] or 'abonnés inconnus'} abonnés)
- publiée il y a {m['age']:.1f} h, {m['vues']} vues ({m['vitesse']:.0f} vues/heure), {m['eng'] * 100:.1f} % d'interactions, durée {m['duree']} s
- description : {m['desc']}
- mots-clés : {', '.join(m['tags'])}

{ia.REGLES}
Tu ne vois PAS la vidéo : déduis seulement de ces informations, et dis « d'après le titre » quand c'est une déduction.

Réponds avec ce JSON :
{{"sujet": "de quoi parle la vidéo en 1 phrase", "pourquoi_viral": ["2 à 4 raisons concrètes (sujet, émotion, accroche du titre, format, personnalité…)"],
"format": "type de vidéo (short, interview, réaction, compilation…)", "comment_refaire": "comment @laffaire_france peut refaire ce succès (angle actu, accroche, format, durée)",
"accroche": "1re phrase de voix off proposée", "titre_tiktok": "titre choc proposé", "note_refaire": 0-10 (intérêt pour un compte d'actu FR : 0 = musique/jeu vidéo sans rapport, 10 = actu choc parfaite),
"categorie": "fait divers|politique|celebrite|insolite|sport|divertissement|autre"}}"""
    res, _ = ia.appeler(prompt, modeles=ia.RAPIDES)
    return res


def couleur(m):
    if m["note"] >= 8:
        return "🟢 <b>VIDÉO QUI EXPLOSE</b>"
    if m["note"] >= 6.5:
        return "🟠 <b>Vidéo qui monte fort</b>"
    return "🟡 <b>Vidéo qui monte</b>"


def fmt(n):
    return f"{n / 1e6:.1f} M" if n >= 1e6 else f"{n / 1e3:.0f} k" if n >= 1e3 else str(int(n))


def texte(m, a):
    e = tg.e
    forme = "⚡ Short" if m["duree"] <= 180 else f"{m['duree'] // 60} min"
    t = [couleur(m) + "\n", f"🎥 <b>{e(m['titre'])}</b>", f"📺 {e(m['chaine'])} · {forme}",
         f"\n📈 <b>{fmt(m['vues'])} vues</b> en {m['age']:.0f} h · <b>{fmt(m['vitesse'])} vues/heure</b>",
         f"💬 {m['eng'] * 100:.1f} % d'interactions" + (f" · 🚀 {m['ratio']:.1f}× ses abonnés" if m["ratio"] else ""),
         f"Score viral : <b>{m['note']}/10</b>" + (f" · Intérêt pour L'Affaire : <b>{a.get('note_refaire')}/10</b>" if a else "")]
    if a:
        t.append(f"\n🧐 <b>De quoi ça parle :</b> {e(a.get('sujet'))}")
        if a.get("pourquoi_viral"):
            t.append("🔥 <b>Pourquoi ça buzze</b>\n" + "\n".join("• " + e(x) for x in a["pourquoi_viral"][:4]))
        t.append(f"🎬 <b>Comment le refaire :</b> {e(a.get('comment_refaire'))}")
        if a.get("accroche"):
            t.append(f"🎙️ <b>Accroche :</b> « {e(a['accroche'])} »")
    t.append(f'\n▶️ <a href="{e(m["lien"])}">Voir la vidéo</a>')
    return tg.assembler(t)


def boutons(vid):
    return {"inline_keyboard": [[{"text": f"🎬 Refaire · Modèle {n}", "callback_data": f"vprep{n}:{vid}"} for n in (1, 2, 3)],
                                [{"text": "✖️ IGNORER", "callback_data": f"vign:{vid}"}]]}


def preparer(etat, vid, modele):
    """Transforme la vidéo virale en sujet pour le pipeline habituel (dossier sujets/ + événement dans l'état de la veille)."""
    m, a = etat["videos"][vid]["mesure"], etat["videos"][vid].get("analyse") or {}
    ts = time.time()
    ev = {"id": "v" + vid, "cree": ts, "maj": ts, "statut": "nouveau", "notifie": True, "analyses": 3, "sources_analyse": 0,
          "nb_sources": 1, "score": m["note"],
          "articles": [{"id": vid, "titre": m["titre"], "source": "YouTube · " + m["chaine"], "lien": m["lien"], "ts": V.iso(m["pub"]),
                        "pays": "FR", "type": "video", "resume": m["desc"][:600], "date": datetime.fromtimestamp(V.iso(m["pub"]), V.PARIS).strftime("%d/%m %H:%M")}],
          "analyse": {"titre": a.get("titre_tiktok") or a.get("sujet") or m["titre"], "resume": a.get("sujet"), "angle": a.get("comment_refaire"),
                      "accroche": a.get("accroche"), "categorie": a.get("categorie"), "score_tiktok": a.get("note_refaire"),
                      "recherche_video": [m["titre"]], "faits_confirmes": [], "incertain": ["Vidéo virale : faits à vérifier dans des sources fiables"]}}
    dos = V.preparer(ev, modele)
    ev["statut"], ev["dossier"] = "prepare", dos.name
    # l'événement rejoint l'état de la veille : boutons Refaire / Modifier et /sujets marchent pareil
    ev_etat = json.loads(V.ETAT.read_text(encoding="utf-8")) if V.ETAT.exists() else {"vus": {}, "evenements": {}, "offset": 0}
    ev_etat["evenements"][ev["id"]] = ev
    if not ESSAI:
        V.ETAT.write_text(json.dumps(ev_etat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return dos


def traiter_clics(etat):
    if ESSAI or not tg.TOKEN:
        return
    liste, msgs, etat["offset"] = tg.clics(etat.get("offset", 0))
    for texte_msg, _ in msgs:
        if texte_msg.lower().lstrip("/") in ("start", "aide", "help", "statut"):
            nb = sum(1 for v in etat["videos"].values() if v.get("alerte") and v.get("maj", 0) > time.time() - 86400)
            tg.envoyer(f"🚀 <b>Viral L'Affaire</b> : je surveille les vidéos qui explosent en France (tendances YouTube + chaînes d'actu), "
                       f"toutes les 30 min.\n🟢 explose · 🟠 monte fort · 🟡 monte\n{nb} alerte(s) ces dernières 24 h.\n"
                       "Boutons « Refaire · Modèle 1/2/3 » = la vidéo est préparée puis montée par ton PC.")
    for id_clic, action, vid, mid in liste:
        if vid not in etat["videos"] or "mesure" not in etat["videos"][vid]:
            tg.repondre_clic(id_clic, "Vidéo expirée"); continue
        if action == "vign":
            etat["videos"][vid]["ignore"] = True
            tg.repondre_clic(id_clic, "Ignoré"); tg.marquer(mid, "✖️ Ignoré")
        elif action.startswith("vprep"):
            modele = int(action[5:] or 2)
            tg.repondre_clic(id_clic, f"Préparation (modèle {modele})…")
            dos = preparer(etat, vid, modele)
            tg.marquer(mid, f"🎬 Sujet préparé — modèle {modele}")
            tg.envoyer_fichier(dos / "dossier.md", f"🎬 Dossier prêt : {dos.name} (modèle {modele})\nSi ton PC et l'appli Claude sont ouverts, "
                               "la vidéo démarre toute seule. (rien n'est publié sans toi)")


def main():
    if not CLE_YT:
        print("pas de YOUTUBE_API_KEY"); return
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {"videos": {}, "offset": 0}
    premier = not etat["videos"]
    traiter_clics(etat)
    vids, abonnes = collecter()
    mesures = [mesurer(v, abonnes, etat) for v in vids.values()]
    cand = [m for m in mesures if m["age"] <= 48 and m["vues"] >= 30000 and m["cat"] != "10" and not EXCLUS.search(m["titre"])
            and francais(vids[m["id"]]) and not etat["videos"][m["id"]].get("alerte") and m["note"] >= 5]
    cand.sort(key=lambda m: -m["note"])
    print(f"{len(vids)} vidéos lues, {len(cand)} candidates virales")
    envoyees = 0
    for m in cand[:1 if premier else 4]:
        mem = etat["videos"][m["id"]]
        try:
            a = analyser(m) if ia.CLE else None
        except Exception as ex:
            print("  ! IA :", ex); a = None
        mem.update(mesure=m, analyse=a)
        interet = (a or {}).get("note_refaire") or 0
        print(f"  {m['note']:4.1f} | intérêt {interet} | {fmt(m['vitesse'])}/h | {m['titre'][:70]}")
        if a and interet < 5 and m["note"] < 8:
            mem["alerte"] = "écartée"; continue  # sans rapport avec un compte d'actu (musique, jeux vidéo…)
        if ESSAI:
            print(re.sub(r"<[^>]+>", "", texte(m, a)) + "\n" + "=" * 60)
        else:
            tg.envoyer(texte(m, a), clavier=boutons(m["id"]))
        mem["alerte"] = True; envoyees += 1
    # ménage : on garde 4 jours
    limite = time.time() - 4 * 86400
    etat["videos"] = {k: v for k, v in etat["videos"].items() if v.get("maj", 0) >= limite}
    if not ESSAI:
        ETAT.parent.mkdir(exist_ok=True)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(envoyees, "alerte(s) virale(s)")


if __name__ == "__main__":
    main()
