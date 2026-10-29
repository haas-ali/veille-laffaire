"""Bot « Viral L'Affaire » (@laffaire_viral_bot) : repère les vidéos TikTok D'ACTUALITÉ qui percent en très peu de temps.

Source : les dernières vidéos des comptes TikTok d'actu FR (config.COMPTES_TIKTOK), lues avec yt-dlp (vues, likes, commentaires,
partages, date). Une vidéo « perce » quand elle va beaucoup plus vite que d'habitude pour ce compte : vues par heure, vues comparées
à la médiane du compte, accélération entre deux tours, taux d'interaction. L'IA vérifie que c'est de l'actualité, explique pourquoi
ça buzze et comment la refaire pour @laffaire_france. Boutons Modèle 1/2/3 = même chemin que la veille (dossier sujets/ → tâche du PC).
Lancé après veille.py dans le même tour GitHub Actions. Option : --essai (n'envoie rien, n'enregistre rien)."""
import json, math, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from statistics import median
import veille as V  # charge .env, preparer()…
import config, ia
import telegram as tg

ESSAI = "--essai" in sys.argv
ETAT = V.ICI / "donnees" / "viral.json"
CHAMPS = "%(.{id,view_count,like_count,comment_count,repost_count,timestamp,title,duration})j"

# le bot viral a son propre jeton (meme discussion)
tg.TOKEN = os.environ.get("TELEGRAM_TOKEN_VIRAL", "").strip()
tg.API = f"https://api.telegram.org/bot{tg.TOKEN}/"


def lire_compte(compte):
    """Les 12 dernières vidéos d'un compte TikTok (yt-dlp, sans connexion)."""
    try:
        r = subprocess.run(["yt-dlp", "--encoding", "utf-8", "--flat-playlist", "--playlist-items", "1-12", "--print", CHAMPS,
                            f"https://www.tiktok.com/@{compte}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (subprocess.TimeoutExpired, OSError) as ex:
        print(f"  ! @{compte} : {ex}"); return []
    vids = []
    for ligne in (r.stdout or "").splitlines():
        try:
            v = json.loads(ligne)
        except ValueError:
            continue
        if v.get("view_count") is not None and v.get("timestamp"):
            v["compte"] = compte
            vids.append(v)
    if not vids:
        print(f"  ! @{compte} : rien lu ({(r.stderr or '').strip()[-120:]})")
    return vids


def mesurer(v, med, etat):
    now = time.time()
    age = max((now - v["timestamp"]) / 3600, 0.3)
    vues = int(v["view_count"]); inter = sum(int(v.get(k) or 0) for k in ("like_count", "comment_count", "repost_count"))
    mem = etat["videos"].setdefault(v["id"], {"snap": []})
    snap = mem["snap"]
    vitesse = vues / age
    if snap and now - snap[-1][0] >= 1200:  # accélération réelle depuis le dernier tour (≥ 20 min)
        vitesse = max(vitesse, (vues - snap[-1][1]) / ((now - snap[-1][0]) / 3600))
    if not snap or now - snap[-1][0] >= 1200:
        snap.append([now, vues]); del snap[:-6]
    ratio = vues / med if med else None
    eng = inter / max(vues, 1)
    note = min(4, max(0, (math.log10(max(vitesse, 1)) - 2.7) * 2))  # 500 vues/h → 0 ; 5 000 → 2 ; 50 000 → 4
    note += min(4, max(0, (ratio - 1) * 1.3)) if ratio else 0      # 2× la médiane du compte → +1,3 ; 4× → +3,9
    note += min(2, max(0, (eng - 0.03) * 40))                       # 8 % d'interactions → +2
    mem.update(titre=v.get("title", ""), maj=now)
    return {"id": v["id"], "titre": (v.get("title") or "").strip(), "chaine": "@" + v["compte"], "age": age, "vues": vues,
            "vitesse": vitesse, "eng": eng, "ratio": ratio, "duree": int(v.get("duration") or 0), "ts": v["timestamp"],
            "note": round(note, 1), "lien": f"https://www.tiktok.com/@{v['compte']}/video/{v['id']}"}


def analyser(m):
    prompt = f"""Tu aides le créateur TikTok « L'Affaire » (@laffaire_france, actualité France : faits divers, politique, société, célébrités dans l'actu).
Cette vidéo TikTok d'un compte d'info perce en ce moment :
- compte : {m['chaine']}
- légende : {m['titre']}
- publiée il y a {m['age']:.1f} h, {m['vues']} vues ({m['vitesse']:.0f} vues/heure), {m['ratio'] or 0:.1f} fois plus que d'habitude pour ce compte,
  {m['eng'] * 100:.1f} % d'interactions, durée {m['duree']} s

{ia.REGLES}
Tu ne vois PAS la vidéo : déduis seulement de la légende et des chiffres, et dis « d'après la légende » quand c'est une déduction.

Réponds avec ce JSON :
{{"actualite": true si c'est une vraie info d'actualité (fait divers, politique, société, international, célébrité dans l'actu), false si c'est du divertissement, une recette, un sketch, une pub…,
"sujet": "de quoi parle la vidéo en 1 phrase", "pourquoi_viral": ["2 à 4 raisons concrètes (sujet, émotion, accroche, images, personnalité…)"],
"comment_refaire": "comment @laffaire_france peut faire mieux sur ce sujet (angle, accroche, images à chercher, durée)",
"accroche": "1re phrase de voix off proposée", "titre_tiktok": "titre choc proposé", "note_refaire": 0-10,
"categorie": "fait divers|politique|societe|international|celebrite|autre"}}"""
    res, _ = ia.appeler(prompt, modeles=ia.RAPIDES)
    return res


def couleur(m):
    if m["note"] >= 8:
        return "🟢 <b>VIDÉO QUI EXPLOSE</b>"
    if m["note"] >= 6.5:
        return "🟠 <b>Vidéo qui perce</b>"
    return "🟡 <b>Vidéo qui monte</b>"


def fmt(n):
    return f"{n / 1e6:.1f} M" if n >= 1e6 else f"{n / 1e3:.0f} k" if n >= 1e3 else str(int(n))


def texte(m, a):
    e = tg.e
    t = [couleur(m) + "\n", f"🎥 <b>{e(m['titre'][:200])}</b>", f"📱 TikTok · {e(m['chaine'])} · {m['duree']} s",
         f"\n📈 <b>{fmt(m['vues'])} vues</b> en {m['age']:.0f} h · <b>{fmt(m['vitesse'])} vues/heure</b>",
         f"💬 {m['eng'] * 100:.1f} % d'interactions" + (f" · 🚀 {m['ratio']:.1f}× plus que d'habitude" if m["ratio"] else ""),
         f"Score viral : <b>{m['note']}/10</b>" + (f" · Intérêt pour L'Affaire : <b>{a.get('note_refaire')}/10</b>" if a else "")]
    if a:
        t.append(f"\n🧐 <b>De quoi ça parle :</b> {e(a.get('sujet'))}")
        if a.get("pourquoi_viral"):
            t.append("🔥 <b>Pourquoi ça perce</b>\n" + "\n".join("• " + e(x) for x in a["pourquoi_viral"][:4]))
        t.append(f"🎬 <b>Comment faire mieux :</b> {e(a.get('comment_refaire'))}")
        if a.get("accroche"):
            t.append(f"🎙️ <b>Accroche :</b> « {e(a['accroche'])} »")
    t.append(f'\n▶️ <a href="{e(m["lien"])}">Voir la vidéo TikTok</a>')
    return tg.assembler(t)


def boutons(vid):
    return {"inline_keyboard": [[{"text": f"🎬 Refaire · Modèle {n}", "callback_data": f"vprep{n}:{vid}"} for n in (1, 2, 3)],
                                [{"text": "✖️ IGNORER", "callback_data": f"vign:{vid}"}]]}


def preparer(etat, vid, modele):
    """Transforme la vidéo virale en sujet pour le pipeline habituel (dossier sujets/ + événement dans l'état de la veille)."""
    m, a = etat["videos"][vid]["mesure"], etat["videos"][vid].get("analyse") or {}
    ts = time.time()
    ev = {"id": "v" + vid[-12:], "cree": ts, "maj": ts, "statut": "nouveau", "notifie": True, "analyses": 3, "sources_analyse": 0,
          "nb_sources": 1, "score": m["note"],
          "articles": [{"id": vid, "titre": m["titre"][:200], "source": "TikTok · " + m["chaine"], "lien": m["lien"], "ts": m["ts"],
                        "pays": "FR", "type": "video", "resume": m["titre"], "date": datetime.fromtimestamp(m["ts"], V.PARIS).strftime("%d/%m %H:%M")}],
          "analyse": {"titre": a.get("titre_tiktok") or a.get("sujet") or m["titre"][:120], "resume": a.get("sujet"), "angle": a.get("comment_refaire"),
                      "accroche": a.get("accroche"), "categorie": a.get("categorie"), "score_tiktok": a.get("note_refaire"),
                      "recherche_video": [a.get("sujet") or m["titre"][:100]], "faits_confirmes": [],
                      "incertain": ["Sujet venu d'une vidéo TikTok virale : chaque fait est à vérifier dans des sources fiables"]}}
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
            nb = sum(1 for v in etat["videos"].values() if v.get("alerte") is True and v.get("maj", 0) > time.time() - 86400)
            tg.envoyer(f"🚀 <b>Viral L'Affaire</b> : je surveille les vidéos TikTok d'actualité qui percent ({len(config.COMPTES_TIKTOK)} comptes d'info), "
                       f"toutes les 30 min.\n🟢 explose · 🟠 perce · 🟡 monte\n{nb} alerte(s) ces dernières 24 h.\n"
                       "« Refaire · Modèle 1/2/3 » = le sujet est préparé puis monté par ton PC.")
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
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {"videos": {}, "offset": 0}
    etat["videos"] = {k: v for k, v in etat["videos"].items() if k.isdigit() or "mesure" not in v}  # oublie l'ancienne version YouTube
    premier = not etat["videos"]
    traiter_clics(etat)
    with ThreadPoolExecutor(len(config.COMPTES_TIKTOK)) as p:
        par_compte = list(p.map(lire_compte, config.COMPTES_TIKTOK))
    mesures = []
    for vids in par_compte:
        anciennes = [int(v["view_count"]) for v in vids if time.time() - v["timestamp"] > 12 * 3600]  # référence : vidéos déjà « mûres »
        med = median(anciennes) if len(anciennes) >= 3 else None
        mesures += [mesurer(v, med, etat) for v in vids]
    cand = [m for m in mesures if m["age"] <= 36 and m["vues"] >= 50000 and m["note"] >= 5
            and ((m["ratio"] or 0) >= 2 or m["vitesse"] >= 20000) and not etat["videos"][m["id"]].get("alerte")]
    cand.sort(key=lambda m: -m["note"])
    print(f"{len(mesures)} vidéos TikTok lues ({sum(1 for v in par_compte if v)}/{len(config.COMPTES_TIKTOK)} comptes), {len(cand)} candidates")
    envoyees = 0
    for m in cand[:2 if premier else 4]:
        mem = etat["videos"][m["id"]]
        try:
            a = analyser(m) if ia.CLE else None
        except Exception as ex:
            print("  ! IA :", ex); a = None
        mem.update(mesure=m, analyse=a)
        print(f"  {m['note']:4.1f} | actu={(a or {}).get('actualite')} | {fmt(m['vitesse'])}/h | {m['chaine']} | {m['titre'][:60]}")
        if a and not a.get("actualite"):
            mem["alerte"] = "pas d'actu"; continue  # seulement l'actualité
        if ESSAI:
            print(re.sub(r"<[^>]+>", "", texte(m, a)) + "\n" + "=" * 60)
        else:
            tg.envoyer(texte(m, a), clavier=boutons(m["id"]))
        mem["alerte"] = True; envoyees += 1
    limite = time.time() - 4 * 86400  # ménage : on garde 4 jours
    etat["videos"] = {k: v for k, v in etat["videos"].items() if v.get("maj", 0) >= limite}
    if not ESSAI:
        ETAT.parent.mkdir(exist_ok=True)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(envoyees, "alerte(s) virale(s)")


if __name__ == "__main__":
    main()
