"""Coach de @laffaire_france (messages via le bot Viral L'Affaire) : suit tes vidéos après publication + meilleures heures pour poster.

1. Suivi : à chaque tour (30 min), lit tes dernières vidéos avec yt-dlp. Pour chaque vidéo de moins de 48 h, compare ses vues à celles
   de tes vidéos habituelles AU MÊME ÂGE (courbes enregistrées tour après tour) et t'alerte sur Telegram aux moments clés
   (≈ 1 h, 3 h, 6 h, 24 h) : 🚀 ça décolle → réponds aux commentaires maintenant ; 📉 ça stagne → conseils. Alerte aussi si elle repart.
2. Meilleures heures : chaque matin (9 h), dit à quelle heure poster aujourd'hui, d'après tes vidéos ET celles des comptes d'actu
   surveillés par le bot viral (vues de chaque vidéo comparées à la médiane de son compte, selon l'heure de publication).
Rien n'est publié ni « boosté » artificiellement : ce sont des alertes et des conseils.
Options : --essai (affiche sans envoyer ni enregistrer), --heures (envoie tout de suite le message des meilleures heures)."""
import json, os, subprocess, sys, time
from datetime import datetime
from statistics import median
import veille as V
import telegram as tg

ESSAI = "--essai" in sys.argv
COMPTE = "laffaire_france"
ETAT = V.ICI / "donnees" / "suivi.json"
VIRAL = V.ICI / "donnees" / "viral.json"
CHAMPS = "%(.{id,view_count,like_count,comment_count,repost_count,timestamp,title})j"
PALIERS = [1, 3, 6, 24]  # heures après publication où l'on fait le point
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

tg.TOKEN = os.environ.get("TELEGRAM_TOKEN_VIRAL", "").strip()
tg.API = f"https://api.telegram.org/bot{tg.TOKEN}/"


def lire_mes_videos(n=30):
    try:
        r = subprocess.run(["yt-dlp", "--encoding", "utf-8", "--flat-playlist", "--playlist-items", f"1-{n}", "--print", CHAMPS,
                            f"https://www.tiktok.com/@{COMPTE}"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except (subprocess.TimeoutExpired, OSError) as ex:
        print("  ! lecture :", ex); return []
    vids = []
    for ligne in (r.stdout or "").splitlines():
        try:
            v = json.loads(ligne)
        except ValueError:
            continue
        if v.get("view_count") is not None and v.get("timestamp"):
            vids.append(v)
    if not vids:
        print("  ! rien lu :", (r.stderr or "").strip()[-200:])
    return vids


def vues_a(snap, ts, age_h):
    """Vues d'une vidéo à un âge donné, par interpolation de ses relevés [heure, vues]. None si pas de relevé autour."""
    pts = sorted(((t - ts) / 3600, v) for t, v, *_ in snap)
    for (a1, v1), (a2, v2) in zip(pts, pts[1:]):
        if a1 <= age_h <= a2:
            return v1 + (v2 - v1) * (age_h - a1) / max(a2 - a1, 1e-6)
    if pts and abs(pts[0][0] - age_h) <= max(0.5, age_h * 0.25):  # relevé tout proche
        return pts[0][1]
    return None


def reference(etat, vid, age_h):
    """Vues médianes de tes autres vidéos au même âge (courbes enregistrées), sinon médiane de leurs vues finales."""
    autres = [x for k, x in etat["videos"].items() if k != vid]
    au_meme_age = [v for v in (vues_a(x["snap"], x["ts"], age_h) for x in autres) if v is not None]
    if len(au_meme_age) >= 3:
        return median(au_meme_age), "tes vidéos au même âge"
    finales = [x["snap"][-1][1] for x in autres if time.time() - x["ts"] > 48 * 3600 and x["snap"]]
    if len(finales) >= 3:
        return median(finales), "tes vidéos habituelles (vues finales)"
    return None, ""


def fmt(n):
    return f"{n / 1e6:.1f} M" if n >= 1e6 else f"{n / 1e3:.1f} k".replace(".0 k", " k") if n >= 1e3 else str(int(n))


def message_suivi(x, age_h, ref, quoi, palier, repart=False):
    e = tg.e
    s = x["snap"][-1]
    vues, com = s[1], s[2]
    ratio = vues / ref if ref else None
    lien = f"https://www.tiktok.com/@{COMPTE}/video/{x['id']}"
    if repart:
        tete, conseils = "🔥 <b>TA VIDÉO REPART !</b>", ["Elle reprend de la vitesse : c'est le moment de répondre aux commentaires et d'épingler le meilleur.",
                                                        "Partage-la en story / sur tes autres réseaux tant qu'elle monte."]
    elif ratio is not None and ratio >= 1.5:
        tete = "🚀 <b>TA VIDÉO DÉCOLLE</b>"
        conseils = ["Réponds vite aux commentaires (une réponse = un nouveau commentaire, l'algorithme adore).",
                    "Épingle le commentaire qui fait le plus débattre.",
                    "Pose une question en réponse pour relancer la discussion.",
                    "Une suite sur le même sujet dans les 24 h profitera de l'élan."]
    elif ratio is not None and ratio < 0.5:
        tete = "📉 <b>Ta vidéo stagne</b>"
        conseils = ["Ne la supprime pas : TikTok la pousse parfois plus tard.",
                    "Réponds aux premiers commentaires pour relancer.",
                    "Pour la prochaine : accroche plus forte dans les 2 premières secondes, et poste à une meilleure heure."]
    else:
        tete = "📊 <b>Point sur ta vidéo</b>"
        conseils = ["Dans la moyenne. Répondre aux commentaires maintenant peut la faire passer au-dessus."]
    t = [tete + "\n", f"🎥 <b>{e(x['titre'][:120])}</b>",
         f"⏱️ Publiée il y a {age_h:.0f} h" + (f" (point des {palier} h)" if palier else ""),
         f"👀 <b>{fmt(vues)} vues</b> · ❤️ {fmt(s[3])} · 💬 {com} · 🔁 {fmt(s[4])}"]
    if ratio is not None:
        t.append(f"📐 <b>{ratio:.1f}×</b> {e(quoi)} ({fmt(ref)} vues)")
    if len(x["snap"]) >= 2:
        p = x["snap"][-2]
        dh = (s[0] - p[0]) / 3600
        if dh > 0:
            t.append(f"⚡ {fmt((vues - p[1]) / dh)} vues/heure en ce moment" + (f" · +{com - p[2]} commentaire(s)" if com > p[2] else ""))
    t.append("\n💡 <b>À faire</b>\n" + "\n".join("• " + c for c in conseils))
    t.append(f'\n▶️ <a href="{e(lien)}">Ouvrir la vidéo</a>')
    return tg.assembler(t)


def suivre(etat, vids):
    now = time.time()
    msgs = []
    for v in vids:
        x = etat["videos"].setdefault(v["id"], {"id": v["id"], "ts": v["timestamp"], "snap": [], "paliers": []})
        x["titre"] = (v.get("title") or "").strip()
        s = [now, int(v["view_count"]), int(v.get("comment_count") or 0), int(v.get("like_count") or 0), int(v.get("repost_count") or 0)]
        age_h = (now - x["ts"]) / 3600
        if age_h > 72 and x["snap"]:  # vidéo mûre : un relevé par jour suffit
            if now - x["snap"][-1][0] > 86400:
                x["snap"].append(s)
            continue
        x["snap"].append(s); del x["snap"][:-60]
        if age_h > 48 or len(x["snap"]) < 1:
            continue
        ref, quoi = reference(etat, v["id"], age_h)
        dus = [p for p in PALIERS if age_h >= p * 0.9 and p not in x["paliers"]]
        if dus and age_h <= max(dus) * 1.6:  # pas de vieux paliers en rattrapage
            x["paliers"] += dus
            msgs.append(message_suivi(x, age_h, ref, quoi, max(dus)))
            continue
        x["paliers"] += dus
        if len(x["snap"]) >= 3 and age_h >= 2 and not x.get("repart_alerte"):  # accélération nette entre deux tours
            (t0, v0), (t1, v1), (t2, v2) = [(a[0], a[1]) for a in x["snap"][-3:]]
            avant, apres = (v1 - v0) / max((t1 - t0) / 3600, 0.1), (v2 - v1) / max((t2 - t1) / 3600, 0.1)
            if apres >= 2 * max(avant, 1) and apres >= 2000:
                x["repart_alerte"] = True
                msgs.append(message_suivi(x, age_h, ref, quoi, None, repart=True))
    return msgs


def creneaux(etat):
    """Score par heure de publication (heure de Paris) : vues de chaque vidéo / médiane de son compte, vidéos de plus de 24 h.
    Les vidéos des comptes d'actu (bot viral) s'ajoutent au fil des jours dans etat["actu"] (gardées 60 jours)."""
    now = time.time()
    if VIRAL.exists():
        vir = json.loads(VIRAL.read_text(encoding="utf-8"))["videos"]
        for k, x in vir.items():
            # dernier relevé pris au moins 20 h après la publication (sinon les vues ne sont pas encore « finales »)
            if x.get("compte") and x.get("ts") and x.get("snap") and x["snap"][-1][0] - x["ts"] > 20 * 3600:
                etat["actu"][k] = [x["compte"], x["ts"], x["snap"][-1][1]]
    etat["actu"] = {k: a for k, a in etat["actu"].items() if now - a[1] < 60 * 86400}
    lignes = [(a[0], a[1], a[2]) for a in etat["actu"].values()]
    lignes += [(COMPTE, x["ts"], x["snap"][-1][1]) for x in etat["videos"].values() if x["snap"] and now - x["ts"] > 24 * 3600]
    par_compte = {}
    for c, _, vues in lignes:
        par_compte.setdefault(c, []).append(vues)
    meds = {c: median(l) for c, l in par_compte.items() if len(l) >= 3}
    heures = {h: [] for h in range(24)}
    a_moi = {h: [] for h in range(24)}
    for c, ts, vues in lignes:
        if c in meds and meds[c] > 0:
            h = datetime.fromtimestamp(ts, V.PARIS).hour
            r = min(vues / meds[c], 10)  # une vidéo exceptionnelle ne doit pas tout fausser
            heures[h].append(r)
            if c == COMPTE:
                a_moi[h].append(r)
    return heures, a_moi, len(lignes)


def meilleures(heures, mini):
    """Fenêtres de 2 h (heure h et h+1) classées par score médian, sans chevauchement."""
    fen = []
    for h in range(7, 24):  # pas de conseil entre minuit et 7 h
        l = heures[h] + heures[(h + 1) % 24]
        if len(l) >= mini:
            fen.append((median(l), h, len(l)))
    fen.sort(reverse=True)
    res = []
    for f in fen:
        if all(abs(f[1] - g[1]) >= 2 for g in res):
            res.append(f)
    return res


def message_heures(etat):
    heures, a_moi, n = creneaux(etat)
    top = meilleures(heures, 8)
    if not top:
        return None
    jour = JOURS[datetime.now(V.PARIS).weekday()]
    t = [f"🕒 <b>Quand poster aujourd'hui ({jour})</b>\n"]
    for i, (sc, h, nb) in enumerate(top[:3]):
        t.append(f"{'🥇🥈🥉'[i]} <b>{h} h – {h + 2} h</b> : {sc:.1f}× les vues habituelles ({nb} vidéos)")
    pire = min(meilleures(heures, 8))
    t.append(f"🚫 À éviter : {pire[1]} h – {pire[1] + 2} h ({pire[0]:.1f}×)")
    mt = meilleures(a_moi, 2)
    if mt:
        t.append(f"\n📱 <b>Sur ton compte</b>, tes meilleures heures jusqu'ici : " + ", ".join(f"{h} h – {h + 2} h ({sc:.1f}×)" for sc, h, _ in mt[:2]))
    t.append(f"\n<i>D'après {n} vidéos d'actu (tes vidéos + les comptes surveillés). Poste ~15 min avant le début du créneau. "
             "Une grosse actu chaude passe avant l'horaire : poste-la tout de suite.</i>")
    return "\n".join(t)


def envoyer(texte):
    if ESSAI or not tg.TOKEN:
        print(texte.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "") + "\n" + "=" * 60)
    else:
        tg.envoyer(texte)


def main():
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    etat.setdefault("videos", {}); etat.setdefault("actu", {})
    vids = lire_mes_videos()
    premier = not etat["videos"]
    msgs = suivre(etat, vids)
    print(f"{len(vids)} vidéos de @{COMPTE} lues, {len(msgs)} alerte(s) de suivi")
    if not premier:  # premier tour : on enregistre seulement (pas d'alertes en rafale sur les anciennes vidéos)
        for m in msgs:
            envoyer(m)
    auj = datetime.now(V.PARIS).strftime("%Y-%m-%d")
    if "--heures" in sys.argv or (datetime.now(V.PARIS).hour >= 9 and etat.get("heures_envoye") != auj):
        m = message_heures(etat)
        if m:
            envoyer(m); etat["heures_envoye"] = auj
        else:
            print("pas encore assez de données pour les heures")
    else:
        creneaux(etat)  # accumule quand même les vidéos d'actu
    limite = time.time() - 120 * 86400  # tes vidéos : on garde 4 mois de courbes
    etat["videos"] = {k: x for k, x in etat["videos"].items() if x["ts"] >= limite}
    if not ESSAI:
        ETAT.parent.mkdir(exist_ok=True)
        ETAT.write_text(json.dumps(etat, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
