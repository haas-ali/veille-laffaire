"""Envoi des alertes Telegram et lecture des clics sur les boutons.

Lancé seul (python telegram.py), il affiche ton identifiant de discussion et envoie un message de test."""
import html, os
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


def boutons(eid):
    return {"inline_keyboard": [[{"text": "🎬 PRÉPARER LA VIDÉO", "callback_data": f"prep:{eid}"}],
                                [{"text": "🔎 APPROFONDIR", "callback_data": f"plus:{eid}"},
                                 {"text": "✖️ IGNORER", "callback_data": f"ign:{eid}"}]]}


def texte_alerte(ev):
    a = ev.get("analyse") or {}
    note = a.get("score_tiktok")
    t = [f"🚨 <b>{e(a.get('titre') or ev['articles'][0]['titre'])}</b>"]
    t.append(f"Potentiel TikTok : <b>{note}/10</b>" if note is not None else f"(sans analyse IA — score mots-clés {ev['score']:.0f})")
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


def envoyer(texte, eid=None, reponse_a=None):
    p = {"chat_id": CHAT, "text": texte, "parse_mode": "HTML", "disable_web_page_preview": True}
    if eid:
        p["reply_markup"] = boutons(eid)
    if reponse_a:
        p["reply_parameters"] = {"message_id": reponse_a, "allow_sending_without_reply": True}
    return api("sendMessage", **p)["message_id"]


def envoyer_fichier(chemin, legende=""):
    with open(chemin, "rb") as f:
        api("sendDocument", fichiers={"document": f}, chat_id=CHAT, caption=legende[:1000])


def clics(offset):
    """Renvoie (liste de (id_clic, action, eid, message_id), nouvel offset). Ignore les autres discussions."""
    maj = api("getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query", "message"])
    res = []
    for u in maj:
        offset = u["update_id"] + 1
        c = u.get("callback_query")
        if c and str(c["message"]["chat"]["id"]) == CHAT and ":" in c.get("data", ""):
            action, eid = c["data"].split(":", 1)
            res.append((c["id"], action, eid, c["message"]["message_id"]))
    return res, offset


def repondre_clic(id_clic, texte):
    try:
        api("answerCallbackQuery", callback_query_id=id_clic, text=texte)
    except RuntimeError:
        pass  # clic trop ancien (plus de 15 min) : sans gravité


def marquer(message_id, etiquette):
    """Remplace les boutons du message par un statut."""
    try:
        api("editMessageReplyMarkup", chat_id=CHAT, message_id=message_id,
            reply_markup={"inline_keyboard": [[{"text": etiquette, "callback_data": "rien:0"}]]})
    except RuntimeError:
        pass


if __name__ == "__main__":
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
