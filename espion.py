"""Observateur de comptes (messages via le bot Viral L'Affaire) : alerte dès qu'un compte de config.COMPTES_ESPION poste,
puis l'IA (Gemini) REGARDE la vidéo et explique comment elle retient les gens : accroche des 3 premières secondes, rythme des plans,
textes à l'écran, structure / suspense, voix et son, fin. Le nombre de coupes est mesuré pour de vrai (ffmpeg, détection de plans).
Le dimanche à 20 h : bilan des méthodes communes aux vidéos qui ont le plus marché. But : s'INSPIRER des méthodes, jamais recopier.
Lancé en même temps que viral.py (le tour cloud doit rester < 60 s) : budget de temps limité, ce qui n'est pas fini repart au tour suivant.
Options : --essai (affiche sans envoyer ni enregistrer), --bilan (envoie le bilan tout de suite), --analyser <url> (fiche d'une vidéo)."""
import base64, json, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import requests
import veille as V
import config, ia
import telegram as tg

ESSAI = "--essai" in sys.argv
ETAT = V.ICI / "donnees" / "espion.json"
CHAMPS = "%(.{id,view_count,like_count,comment_count,repost_count,timestamp,title,duration})j"
DEBUT = time.time()
BUDGET = 30  # secondes par tour (viral.py dure ~32 s en parallèle) ; téléchargement ~3 s + plans ~2 s + Gemini 14-20 s
MODELES_VIDEO = ["gemini-3.5-flash", "gemini-flash-lite-latest"]

tg.TOKEN = os.environ.get("TELEGRAM_TOKEN_VIRAL", "").strip()
tg.API = f"https://api.telegram.org/bot{tg.TOKEN}/"


def reste():
    return BUDGET - (time.time() - DEBUT)


def lire_compte(compte):
    try:
        r = subprocess.run(["yt-dlp", "--encoding", "utf-8", "--flat-playlist", "--playlist-items", "1-5", "--print", CHAMPS,
                            f"https://www.tiktok.com/@{compte}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
    except (subprocess.TimeoutExpired, OSError) as ex:
        print(f"  ! @{compte} : {ex}"); return compte, []
    vids = []
    for ligne in (r.stdout or "").splitlines():
        try:
            v = json.loads(ligne)
        except ValueError:
            continue
        if v.get("timestamp"):
            vids.append(v)
    return compte, vids


def telecharger(lien, dossier):
    """Vidéo en 720p max (assez pour l'analyse, et < 20 Mo pour l'envoyer directement à Gemini)."""
    sortie = Path(dossier) / "v.mp4"
    subprocess.run(["yt-dlp", "-q", "--no-warnings", "-S", "res:720,ext:mp4", "--max-filesize", "19M", "-o", str(sortie), lien],
                   capture_output=True, timeout=max(5, reste()))
    return sortie if sortie.exists() and sortie.stat().st_size > 0 else None


def mesurer_plans(fichier):
    """(nombre de plans, durée en s) : détection des changements de plan, image réduite pour aller vite."""
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(fichier), "-vf", "scale=160:-2,select='gt(scene,0.15)',metadata=print",
                            "-an", "-f", "null", "-"], capture_output=True, text=True, errors="replace", timeout=max(5, reste()))
        coupes = r.stderr.count("lavfi.scene_score")
        d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
        duree = int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]) if d else None
        return coupes + 1, duree
    except (subprocess.TimeoutExpired, OSError):
        return None, None


PROMPT = """Tu analyses une vidéo TikTok d'actualité du compte @{compte} pour le créateur « L'Affaire » (@laffaire_france), qui veut comprendre
COMMENT cette vidéo retient les gens jusqu'au bout, pour s'en INSPIRER (pas la recopier).
Légende : {titre}
Chiffres : {vues} vues, {likes} likes, {com} commentaires, {partages} partages. Mesure automatique : {plans} plans en {duree} s.

Regarde et écoute TOUTE la vidéo. Décris seulement ce que tu vois et entends vraiment (si tu n'es pas sûr, dis-le). Réponds en français avec ce JSON :
{{"sujet": "1 phrase",
"accroche_3s": {{"dit": "phrase exacte dite au début ou null", "ecrit": "texte à l'écran au début ou null", "image": "ce qu'on voit", "pourquoi_ca_accroche": "..."}},
"structure": [{{"t": "0-3 s", "quoi": "étape du récit + procédé (révélation, question, chiffre choc, image forte…)"}}],
"rythme": "vitesse des plans, zooms, coupes, arrêts sur image, effets",
"textes_ecran": "titre, sous-titres (mot à mot ? couleurs ? position ? mots surlignés ?), logos",
"voix_son": "voix (humaine/IA, ton, débit), musique, bruitages, son d'origine des vidéos",
"suspense": ["procédés qui donnent envie de rester (promesse, info retenue, « voici ce que l'on sait », rebondissement…)"],
"fin": "comment ça se termine (boucle vers le début ? question ? appel à l'action ?)",
"pourquoi_on_reste": ["3 à 5 raisons concrètes"],
"a_reprendre": ["3 à 5 idées concrètes et précises pour les vidéos de L'Affaire (sans copier leur script)"],
"a_eviter": ["ce qui est faible dans cette vidéo"],
"note_retention": 0-10}}"""


def demander_gemini(fichier, m):
    if not ia.CLE:
        return None
    data = base64.b64encode(Path(fichier).read_bytes()).decode()
    corps = {"contents": [{"parts": [{"inline_data": {"mime_type": "video/mp4", "data": data}},
                                     {"text": PROMPT.format(compte=m["compte"], titre=m["titre"], vues=m["vues"], likes=m["likes"],
                                                            com=m["com"], partages=m["partages"], plans=m.get("plans") or "?",
                                                            duree=round(m.get("duree") or 0))}]}],
             "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    # 3.5-flash ≈ 20 s, lite ≈ 14 s (mesuré le 29/10) : s'il reste peu de temps, directement le lite
    for modele in MODELES_VIDEO if reste() >= 22 else MODELES_VIDEO[1:]:
        if reste() < 4:
            return None
        try:
            r = requests.post(ia.URL.format(modele), json=corps, headers={"x-goog-api-key": ia.CLE}, timeout=max(4, reste()))
        except requests.RequestException as ex:
            print("  ! Gemini :", type(ex).__name__); continue
        if r.status_code != 200:
            print("  ! Gemini", modele, r.status_code); continue
        cand = r.json()["candidates"][0]
        return ia._json("".join(p.get("text", "") for p in cand.get("content", {}).get("parts", [])))
    return None


def analyser(m):
    with tempfile.TemporaryDirectory() as d:
        f = telecharger(m["lien"], d)
        if not f:
            print("  ! téléchargement raté :", m["lien"]); return None
        plans, duree = mesurer_plans(f)  # ~2 s (image réduite), donné ensuite à Gemini
        m["plans"], m["duree"] = plans, m.get("duree") or duree  # durée TikTok d'abord (ffmpeg se trompe parfois : 245 s pour 95 s)
        return demander_gemini(f, m)


def fmt(n):
    return f"{n / 1e6:.1f} M" if n >= 1e6 else f"{n / 1e3:.0f} k" if n >= 1e3 else str(int(n))


def texte_alerte(m):
    e = tg.e
    return (f"👀 <b>@{e(m['compte'])} vient de poster</b>\n\n🎥 {e(m['titre'][:200])}\n"
            f"⏱️ il y a {(time.time() - m['ts']) / 60:.0f} min · {m.get('duree') or '?'} s · 👀 {fmt(m['vues'])} vues\n"
            f"🔬 Analyse de la méthode en cours…\n\n▶️ <a href=\"{e(m['lien'])}\">Voir la vidéo</a>")


def texte_fiche(m, a):
    e = tg.e
    l = lambda xs: "\n".join("• " + e(x) for x in (xs or [])[:5])
    acc = a.get("accroche_3s") or {}
    pm = f" · {m['plans']} plans ({m['duree'] / m['plans']:.1f} s par plan)" if m.get("plans") and m.get("duree") else ""
    t = [f"🔬 <b>Méthode de @{e(m['compte'])}</b> — rétention {a.get('note_retention', '?')}/10",
         f"🧐 {e(a.get('sujet'))}", f"⏱️ {round(m.get('duree') or 0)} s{pm}",
         "\n🎣 <b>Accroche (0-3 s)</b>" + (f"\n🗣️ « {e(acc.get('dit'))} »" if acc.get("dit") else "")
         + (f"\n🔤 écrit : {e(acc.get('ecrit'))}" if acc.get("ecrit") else "") + f"\n🖼️ {e(acc.get('image'))}\n💡 {e(acc.get('pourquoi_ca_accroche'))}"]
    if a.get("structure"):
        t.append("\n🧱 <b>Structure</b>\n" + "\n".join(f"• <b>{e(s.get('t'))}</b> {e(s.get('quoi'))}" for s in a["structure"][:8]))
    t += [f"\n✂️ <b>Rythme :</b> {e(a.get('rythme'))}", f"🔤 <b>Textes :</b> {e(a.get('textes_ecran'))}",
          f"🎙️ <b>Voix / son :</b> {e(a.get('voix_son'))}", f"🔚 <b>Fin :</b> {e(a.get('fin'))}"]
    if a.get("suspense"):
        t.append("\n⏳ <b>Suspense</b>\n" + l(a["suspense"]))
    if a.get("pourquoi_on_reste"):
        t.append("🧲 <b>Pourquoi on reste</b>\n" + l(a["pourquoi_on_reste"]))
    if a.get("a_reprendre"):
        t.append("\n✅ <b>À reprendre pour L'Affaire</b>\n" + l(a["a_reprendre"]))
    if a.get("a_eviter"):
        t.append("❌ <b>À éviter</b>\n" + l(a["a_eviter"]))
    return tg.assembler(t)


def envoyer(texte, reponse_a=None):
    if ESSAI or not tg.TOKEN:
        print(re.sub(r"<[^>]+>", "", texte) + "\n" + "=" * 60); return None
    try:
        return tg.envoyer(texte, reponse_a=reponse_a)
    except RuntimeError as ex:
        print("  ! Telegram :", ex); return None


def mesure(compte, v):
    return {"id": v["id"], "compte": compte, "titre": (v.get("title") or "").strip(), "ts": v["timestamp"], "duree": v.get("duration"),
            "vues": int(v.get("view_count") or 0), "likes": int(v.get("like_count") or 0), "com": int(v.get("comment_count") or 0),
            "partages": int(v.get("repost_count") or 0), "lien": f"https://www.tiktok.com/@{compte}/video/{v['id']}"}


def bilan(etat):
    """Méthodes communes aux vidéos analysées cette semaine qui ont le plus marché (vues / médiane du compte)."""
    sem = [x for x in etat["videos"].values() if x.get("analyse") and time.time() - x["ts"] < 7 * 86400]
    if len(sem) < 3:
        return None
    par = {}
    for x in sem:
        par.setdefault(x["compte"], []).append(x["vues"])
    from statistics import median
    for x in sem:
        x["_r"] = x["vues"] / max(median(par[x["compte"]]), 1)
    sem.sort(key=lambda x: -x["_r"])
    fiches = "\n\n".join(f"### @{x['compte']} — {x['vues']} vues ({x['_r']:.1f}× sa médiane) — {x.get('plans') or '?'} plans / {round(x.get('duree') or 0)} s\n"
                         + json.dumps({k: x["analyse"].get(k) for k in ("accroche_3s", "rythme", "textes_ecran", "suspense", "fin", "pourquoi_on_reste")},
                                      ensure_ascii=False) for x in sem[:12])
    prompt = f"""Voici les analyses des vidéos TikTok d'actu de la semaine des comptes que @laffaire_france observe, de la plus performante à la moins performante.
{fiches}

Trouve les MÉTHODES qui reviennent dans les vidéos qui marchent le mieux (et qui manquent dans les moins bonnes). Concret, chiffré quand possible.
Réponds en français avec ce JSON : {{"methodes": ["5 à 7 méthodes communes, chacune en 1 phrase concrète"], "accroches_types": ["3 tournures d'accroche qui marchent (modèles réutilisables, pas de copie)"],
"rythme_ideal": "durée et nombre de plans conseillés", "a_tester": ["3 idées à tester dans les prochaines vidéos de L'Affaire"]}}"""
    try:
        a, _ = ia.appeler(prompt)
    except Exception as ex:
        print("  ! bilan :", ex); return None
    if not a:
        return None
    e = tg.e
    l = lambda xs: "\n".join("• " + e(x) for x in (xs or []))
    top = "\n".join(f"• @{e(x['compte'])} : {fmt(x['vues'])} vues ({x['_r']:.1f}×) — {e(x['titre'][:60])}" for x in sem[:3])
    return tg.assembler([f"📚 <b>Bilan de la semaine : ce qui retient les gens</b>\n({len(sem)} vidéos analysées)\n", "🏆 <b>Top</b>\n" + top,
                         "\n🧠 <b>Méthodes qui reviennent</b>\n" + l(a.get("methodes")), "\n🎣 <b>Accroches qui marchent</b>\n" + l(a.get("accroches_types")),
                         f"\n✂️ <b>Rythme conseillé :</b> {e(a.get('rythme_ideal'))}", "\n🧪 <b>À tester</b>\n" + l(a.get("a_tester"))])


def main():
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    etat.setdefault("videos", {})
    premier = not etat["videos"]
    with ThreadPoolExecutor(8) as p:
        lus = list(p.map(lire_compte, config.COMPTES_ESPION))
    now = time.time()
    for compte, vids in lus:
        for v in vids:
            m = mesure(compte, v)
            x = etat["videos"].get(m["id"])
            if x:  # vidéo connue : on met juste les chiffres à jour
                x.update({k: m[k] for k in ("vues", "likes", "com", "partages")}); continue
            nouveau = not premier and now - m["ts"] < 6 * 3600
            m.update(essais=0, a_faire=nouveau or (premier and v is vids[0] and now - m["ts"] < 48 * 3600))
            etat["videos"][m["id"]] = m
            if nouveau:
                m["msg"] = envoyer(texte_alerte(m))
    rates = [c for c, v in lus if not v]
    print(f"{sum(len(v) for _, v in lus)} vidéos lues sur {len(lus)} comptes" + (f" (en échec : {', '.join(rates)})" if rates else ""))
    a_faire = sorted((x for x in etat["videos"].values() if x.get("a_faire") and now - x["ts"] < 48 * 3600), key=lambda x: -x["ts"])[:3]
    if a_faire and reste() > 10:
        with ThreadPoolExecutor(3) as p:
            res = list(p.map(lambda x: (x, analyser(x)), a_faire))
        for x, a in res:
            x["essais"] += reste() > 0  # manque de temps = pas un vrai échec, on réessaie au tour suivant
            if a:
                x.update(analyse=a, a_faire=False)
                envoyer(texte_fiche(x, a), reponse_a=x.get("msg"))
                print(f"  fiche @{x['compte']} : {x['titre'][:50]}")
            elif x["essais"] >= 3:
                x["a_faire"] = False
    paris = datetime.now(V.PARIS)
    semaine = paris.strftime("%G-%V")
    if "--bilan" in sys.argv or (paris.weekday() == 6 and paris.hour >= 20 and etat.get("bilan") != semaine):
        b = bilan(etat)
        if b:
            envoyer(b); etat["bilan"] = semaine
    limite = time.time() - 30 * 86400
    etat["videos"] = {k: x for k, x in etat["videos"].items() if x["ts"] >= limite}
    for x in etat["videos"].values():
        x.pop("_r", None)
    if not ESSAI:
        ETAT.parent.mkdir(exist_ok=True)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--analyser"]:  # python espion.py --analyser <lien TikTok> : fiche d'une vidéo, sans limite de temps
        BUDGET = 600
        u = sys.argv[2]
        c, i = re.search(r"@([^/]+)/video/(\d+)", u).groups()
        _, vids = lire_compte(c)
        v = next((v for v in vids if v["id"] == i), {"id": i, "timestamp": time.time()})
        m = mesure(c, v)
        a = analyser(m)
        print(re.sub(r"<[^>]+>", "", texte_fiche(m, a)) if a else "analyse impossible")
    else:
        main()
