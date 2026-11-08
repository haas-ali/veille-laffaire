"""Envoi des alertes Telegram et lecture des clics sur les boutons.

Lancé seul (python telegram.py), il affiche ton identifiant de discussion et envoie un message de test."""
import html, os, sys
from pathlib import Path
import requests

_env = Path(__file__).with_name(".env")
for _l in _env.read_text(encoding="utf-8").splitlines() if _env.exists() else []:
    if "=" in _l and not _l.startswith("#"):
        os.environ.setdefault(_l.split("=", 1)[0].strip(), _l.split("=", 1)[1].strip())

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}/"
e = lambda s: html.escape(str(s or ""), quote=False)


def api(methode, fichiers=None, **params):
    r = requests.post(API + methode, data=params if fichiers else None, json=None if fichiers else params, files=fichiers, timeout=60)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram {methode} : {j.get('description')}")
    return j["result"]


def bouton_copier(texte, libelle="📋 Copier pour Claude"):
    """Copie le texte dans le presse-papiers du téléphone dès l'appui (sans attendre le prochain tour), à coller ensuite dans Claude.
    Bouton officiel « copy_text » (Bot API 7.11, nov. 2024) : 256 caractères au maximum."""
    return {"text": libelle, "copy_text": {"text": texte[:256]}}


def boutons_dernier(eid, copie):
    """Bot « Dernière info » : exactement 5 boutons (Modèle 1 | 2 / Modèle 3 | 4 / Copier le texte)."""
    m = lambda n: {"text": f"🎬 MODÈLE {n}", "callback_data": f"prep{n}:{eid}"}
    return {"inline_keyboard": [[m(1), m(2)], [m(3), m(4)], [bouton_copier(copie, "📋 COPIER LE TEXTE")]]}


def texte_dernier(ev):
    """Format court du 29/10 (lisible sur téléphone). Aucun champ inventé : « inconnue » / « non applicable »."""
    a = ev.get("analyse") or {}
    import selection as S
    rouge = ev.get("couleur") == "rouge"
    titre = a.get("titre") or ev["articles"][0]["titre"]
    maj = max(ev["articles"], key=lambda x: x["ts"])
    sans_lieu = a.get("categorie") in ("createurs", "people") and not a.get("lieu")
    t = [f"{'🔴' if rouge else '🟢'} <b>{e(titre)}</b>"]
    if ev.get("rebond_de"):
        t.append(f"🔄 <b>Rebondissement</b> (affaire déjà signalée : {e(ev['rebond_de'][:70])})")
    t.append(f"📂 Catégorie : {S.CATEGORIES.get(a.get('categorie'), '📰 Actu').split(' ', 1)[1]}\n"
             f"📅 Date des faits : {e(a.get('date_faits') or 'inconnue')}\n"
             f"🕒 Heure des faits : {e(a.get('heure_faits') or 'inconnue')}\n"
             f"📍 Lieu : {e(a.get('lieu') or ('non applicable' if sans_lieu else 'inconnu'))}\n"
             f"📰 Dernière mise à jour : {e(maj['date'])} ({e(maj['source'])})\n"
             f"🔥 Potentiel TikTok : <b>{ev.get('score100', '?')}/100</b> (estimation éditoriale)\n"
             f"📈 Intérêt médiatique : {e(ev.get('interet') or 'inconnu')}\n"
             f"✅ Fiabilité : {e(S.FIABILITE.get(ev.get('fiab'), 'En cours de vérification'))}")
    t.append(f"\n<b>CE QUI S'EST PASSÉ</b>\n{e(a.get('resume') or titre)}")
    if a.get("verdict") or a.get("pour"):
        ic = {"VA PERCER": "🚀", "PEUT PERCER": "🤔", "NE VA PAS PERCER": "🧊"}.get(a.get("verdict"), "🤔")
        v = [f"\n<b>VERDICT : {ic} {e(a.get('verdict') or 'PEUT PERCER')}</b>"]
        v += [f"➕ {e(x)}" for x in (a.get("pour") or [])[:3]]
        v += [f"➖ {e(x)}" for x in (a.get("contre") or [])[:3]]
        if a.get("images_dispo"):
            v.append(f"🎬 Images : {e(a['images_dispo'])}")
        t.append("\n".join(v))
    elif a.get("pourquoi"):
        t.append(f"\n<b>POURQUOI ÇA PEUT MARCHER</b>\n{e(a['pourquoi'])}")
    t.append(f"\n<b>NOUVEAUTÉ</b>\n{e(a.get('nouveaute') or a.get('nouveau') or 'première alerte sur ce sujet')}")
    vus, lignes = set(), []
    for x in sorted(ev["articles"], key=lambda x: -x["ts"]):
        if x["source"] not in vus and len(lignes) < 4:
            vus.add(x["source"]); lignes.append(f'• <a href="{e(x["lien"])}">{e(x["source"])}</a>')
    for v in (ev.get("videos_yt") or [])[:1]:
        lignes.append(f'• 🎥 <a href="{e(v["lien"])}">{e(v["chaine"])}</a>')
    t.append("\n<b>SOURCES</b>\n" + "\n".join(lignes))
    t.append(liens_ressources(a, titre))
    return assembler(t)


def liens_ressources(a, titre):
    """Liens de recherche directe (vidéos + ressources), un appui depuis le téléphone."""
    from urllib.parse import quote
    req = [r for r in (a.get("recherche_video") or []) if r][:2] or [titre]
    q, q2 = quote(req[0]), quote(req[-1])
    tag = "".join(w for w in req[0].title().split() if w.isalnum())
    liens = [("TikTok", f"https://www.tiktok.com/search/video?q={q}"),
             ("X (direct)", f"https://x.com/search?q={q2}&f=live"),
             ("YouTube (récent)", f"https://www.youtube.com/results?search_query={q}&sp=CAI%253D"),
             ("Instagram", f"https://www.instagram.com/explore/tags/{quote(tag.lower())}/"),
             ("Google Actu", f"https://news.google.com/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"),
             ("Google Images", f"https://www.google.com/search?q={q}&tbm=isch"),
             ("Reddit", f"https://www.reddit.com/search/?q={q2}&sort=new"),
             ("Pixabay (plans libres)", f"https://pixabay.com/videos/search/{quote(req[0].split()[0]) if req[0].split() else q}/")]
    return "\n<b>🎥 VIDÉOS ET RESSOURCES</b>\n" + " · ".join(f'<a href="{e(u)}">{n}</a>' for n, u in liens)


def contexte(titre, lien, extra=""):
    """Demande prête à coller dans Claude (256 caractères max, limite de Telegram)."""
    debut = (f"Claude, fais une vidéo L'Affaire sur : {titre}" + (f" ({extra})" if extra else "") + ".")[:200]
    lien = lien.split("?")[0].split("#")[0]
    fin = f" Source : {lien}"
    if len(debut) + len(fin) > 256:  # lien trop long : le titre passe avant, on garde juste le nom du site
        fin = " Source : " + lien.split("/")[2] if "://" in lien else ""
    return (debut + fin)[:256]


def boutons(eid, ctx=None):
    # 29/10 : plus de boutons Modèle 1/2/3 (l'utilisateur copie la demande et la colle dans Claude)
    lignes = [[{"text": "🔎 APPROFONDIR", "callback_data": f"plus:{eid}"},
               {"text": "✖️ IGNORER", "callback_data": f"ign:{eid}"}]]
    if ctx:
        lignes.insert(0, [bouton_copier(ctx)])
    return {"inline_keyboard": lignes}


def barre(p):
    n = round(p / 10)
    return "▰" * n + "▱" * (10 - n)


def jauges(viral, couv, nb=None, nb_tiktok=None):
    """Deux jauges : chances que ça perce, et à quel point on en parle déjà (presse + comptes TikTok d'actu surveillés)."""
    detail = []
    if nb is not None:
        detail.append(f"{nb} média{'s' if nb > 1 else ''}")
    if nb_tiktok is not None:
        detail.append(f"{nb_tiktok} compte{'s' if nb_tiktok > 1 else ''} TikTok")
    m = f"{couv} %" + (f" ({' · '.join(detail)})" if detail else "")
    if couv == 0:
        m += " — personne n'en parle encore 👀"
    return f"🔥 Viralité : <b>{viral} %</b> {barre(viral)}\n📰 Déjà traité : <b>{m}</b> {barre(couv)}"


def niveau(ev):
    """Code couleur : 🔴 urgente, 🟢 très importante (8-10/10), 🟠 moyenne (7/10), 🟡 faible (6/10 ou moins)."""
    note = (ev.get("analyse") or {}).get("score_tiktok")
    if ev.get("urgent"):
        return "🔴🔴🔴 <b>ACTU URGENTE</b> 🔴🔴🔴"
    if note is not None and note >= 8:
        return "🟢 <b>ACTU TRÈS IMPORTANTE</b>"
    if note is not None and note >= 7:
        return "🟠 <b>Actu moyenne</b>"
    return "🟡 <b>Actu faible</b>"


def texte_alerte(ev):
    a = ev.get("analyse") or {}
    note = a.get("score_tiktok")
    t = [niveau(ev) + "\n"]
    t.append(f"{'‼️' if ev.get('urgent') else '📰'} <b>{e(a.get('titre') or ev['articles'][0]['titre'])}</b>")
    t.append(f"Potentiel TikTok : <b>{note}/10</b>" if note is not None else f"(sans analyse IA — score mots-clés {ev['score']:.0f})")
    if ev.get("pct_viral") is not None:
        t.append(jauges(ev["pct_viral"], ev["pct_medias"], ev.get("nb_medias"), ev.get("nb_tiktok")))
    lieu = " · ".join(x for x in [a.get("lieu") and f"📍 {e(a['lieu'])}", a.get("heure") and f"🕒 {e(a['heure'])}"] if x)
    if lieu:
        t.append(lieu)
    premier = min(ev["articles"], key=lambda x: x["ts"])
    t.append(f"🗓️ Première info : {e(premier['date'])} ({e(premier['source'])})")
    if a.get("nouveau"):
        t.append(f"🆕 <b>Nouveau :</b> {e(a['nouveau'])}")
    if a.get("resume"):
        t.append("\n" + e(a["resume"]))
    if a.get("faits_confirmes"):
        t.append("\n✅ <b>Confirmé</b>\n" + "\n".join("• " + e(x) for x in a["faits_confirmes"][:4]))
    if a.get("incertain"):
        t.append("❓ <b>Incertain</b>\n" + "\n".join("• " + e(x) for x in a["incertain"][:3]))
    if a.get("angle"):
        t.append(f"\n🎬 <b>Sujet proposé :</b> {e(a['angle'])}")
    srcs = [x for x in ev["articles"] if x["type"] == "article"]
    vus, lignes = set(), []
    for x in srcs:
        if x["source"] not in vus and len(lignes) < 6:
            vus.add(x["source"]); lignes.append(f'• <a href="{e(x["lien"])}">{e(x["source"])}</a>')
    t.append(f"\n📰 <b>Sources ({len({x['source'] for x in srcs})})</b>\n" + "\n".join(lignes))
    vids = [(x["source"], x["titre"], x["lien"]) for x in ev["articles"] if x["type"] == "video"][:3]
    vids += [("YouTube · " + v["chaine"], v["titre"], v["lien"]) for v in ev.get("videos_yt") or [] if v["lien"] not in {l for _, _, l in vids}][:4]
    if vids:
        t.append("🎥 <b>Vidéos trouvées</b>\n" + "\n".join(f'• <a href="{e(l)}">{e(s)} : {e(ti[:60])}</a>' for s, ti, l in vids))
    t.append("🔍 Chercher la vidéo : " + liens_recherche(a.get("recherche_video") or [a.get("titre") or ev["articles"][0]["titre"]]))
    return assembler(t)


def assembler(blocs, maxi=4000):
    """Joint les blocs sans dépasser la limite Telegram, sans jamais couper un lien en deux."""
    res = []
    for b in blocs:
        if len("\n".join(res + [b])) > maxi:
            break
        res.append(b)
    return "\n".join(res)


def liens_recherche(requetes):
    from urllib.parse import quote
    q = quote(requetes[0])
    return (f'<a href="https://www.tiktok.com/search/video?q={q}">TikTok</a> · <a href="https://x.com/search?q={q}&amp;f=live">X</a> · '
            f'<a href="https://www.youtube.com/results?search_query={q}&amp;sp=CAI%253D">YouTube</a>')


def envoyer(texte, eid=None, reponse_a=None, clavier=None):
    p = {"chat_id": CHAT, "text": texte, "parse_mode": "HTML", "disable_web_page_preview": True}
    if eid:
        p["reply_markup"] = boutons(eid)
    if clavier:
        p["reply_markup"] = clavier
    if reponse_a:
        p["reply_parameters"] = {"message_id": reponse_a, "allow_sending_without_reply": True}
    return api("sendMessage", **p)["message_id"]


def envoyer_fichier(chemin, legende=""):
    with open(chemin, "rb") as f:
        api("sendDocument", fichiers={"document": f}, chat_id=CHAT, caption=legende[:1000])


def clics(offset):
    """Renvoie (clics [(id_clic, action, eid, message_id)], messages [(texte, id_message_cite)], nouvel offset).
    Ignore tout ce qui ne vient pas de la discussion de l'utilisateur."""
    maj = api("getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query", "message"])
    res, msgs = [], []
    for u in maj:
        offset = u["update_id"] + 1
        c = u.get("callback_query")
        if c and str(c["message"]["chat"]["id"]) == CHAT and ":" in c.get("data", ""):
            action, eid = c["data"].split(":", 1)
            res.append((c["id"], action, eid, c["message"]["message_id"]))
        m = u.get("message")
        if m and str(m["chat"]["id"]) == CHAT and m.get("text"):
            msgs.append((m["text"].strip(), (m.get("reply_to_message") or {}).get("message_id")))
    return res, msgs, offset


def boutons_video(eid):
    """Sous le message « Vidéo prête » : refaire ou modifier, traité par la veille puis par la tâche du PC."""
    return {"inline_keyboard": [[{"text": "🔁 Refaire", "callback_data": f"refaire:{eid}"},
                                 {"text": "✏️ Modifier le texte", "callback_data": f"modif:{eid}"}]]}


def repondre_clic(id_clic, texte):
    try:
        api("answerCallbackQuery", callback_query_id=id_clic, text=texte)
    except RuntimeError:
        pass  # clic trop ancien (plus de 15 min) : sans gravité


def marquer(message_id, etiquette, copie=None):
    """Remplace les boutons du message par un statut (en gardant « Copier le texte » si fourni)."""
    lignes = [[{"text": etiquette, "callback_data": "rien:0"}]] + ([[bouton_copier(copie, "📋 COPIER LE TEXTE")]] if copie else [])
    try:
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=message_id, reply_markup={"inline_keyboard": lignes})
    except RuntimeError:
        pass


if __name__ == "__main__":
    if sys.argv[1:2] == ["--message"]:  # utilise par la tache automatique du PC : python telegram.py --message "texte"
        envoyer(e(" ".join(sys.argv[2:])))
        raise SystemExit
    if sys.argv[1:2] == ["--video"]:  # python telegram.py --video <mp4> [miniature.png] : envoie la video (allegee si > 49 Mo, limite des bots)
        import subprocess, tempfile
        mp4 = sys.argv[2]
        if os.path.getsize(mp4) > 49e6:
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout)
            kbps = int(47e6 * 8 / dur / 1000) - 192  # taille visee ~47 Mo, audio 192 k
            tmp = os.path.join(tempfile.gettempdir(), "telegram_" + os.path.basename(mp4))
            log = os.path.join(tempfile.gettempdir(), "tg2pass")
            base = ["ffmpeg", "-v", "error", "-y", "-i", mp4, "-c:v", "libx264", "-preset", "slow", "-b:v", f"{kbps}k", "-passlogfile", log]
            subprocess.run(base + ["-pass", "1", "-an", "-f", "null", os.devnull], check=True)
            subprocess.run(base + ["-pass", "2", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp], check=True)
            mp4 = tmp
        fichiers = {"video": open(mp4, "rb")}
        if len(sys.argv) > 3:  # miniature en apercu (Telegram veut un JPEG <= 320 px)
            vign = os.path.join(tempfile.gettempdir(), "tg_vignette.jpg")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", sys.argv[3], "-vf", "scale=-2:320", vign], check=True)
            fichiers["thumbnail"] = open(vign, "rb")
        api("sendVideo", fichiers=fichiers, chat_id=CHAT, supports_streaming="true", width=1080, height=1920,
            caption=f"🎬 {os.path.basename(sys.argv[2])} ({os.path.getsize(mp4) / 1e6:.0f} Mo)")
        if len(sys.argv) > 3:
            with open(sys.argv[3], "rb") as f:
                api("sendDocument", fichiers={"document": f}, chat_id=CHAT, caption="🖼️ Miniature")
        for f in fichiers.values():
            f.close()
        if mp4 != sys.argv[2]:
            os.remove(mp4)  # version allegee temporaire
        raise SystemExit
    if sys.argv[1:2] == ["--pret"]:  # python telegram.py --pret description_tiktok.txt "texte d'en-tete"
        desc = open(sys.argv[2], encoding="utf-8").read().strip()
        # id du sujet (sujet.json du dossier) pour les boutons Refaire / Modifier
        sj = os.path.join(os.path.dirname(os.path.abspath(sys.argv[2])), "sujet.json")
        eid = __import__("json").load(open(sj, encoding="utf-8")).get("id") if os.path.exists(sj) else None
        envoyer(f"{e(' '.join(sys.argv[3:]))}\n\n📋 <b>Description à copier</b> (appuie dessus pour copier) :\n<pre>{e(desc)}</pre>"[:4000],
                clavier=boutons_video(eid) if eid else None)
        raise SystemExit
    if not TOKEN:
        raise SystemExit("Mets TELEGRAM_TOKEN dans le fichier .env")
    print("Bot :", api("getMe")["username"])
    if not CHAT:
        for u in api("getUpdates"):
            m = u.get("message")
            if m:
                print("TELEGRAM_CHAT_ID =", m["chat"]["id"], "(", m["chat"].get("first_name"), ")")
        print("Si rien ne s'affiche : envoie « /start » à ton bot sur Telegram, puis relance.")
    else:
        print("Message test envoyé :", envoyer("✅ Veille L'Affaire : connexion Telegram OK."))
