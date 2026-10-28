"""Appels à l'IA (Google Gemini, offre gratuite). Sans clé GEMINI_API_KEY, tout renvoie None."""
import json, os, re, time
import requests

CLE = os.environ.get("GEMINI_API_KEY", "").strip()
MODELES = [m for m in [os.environ.get("GEMINI_MODELE", "").strip(), "gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-lite-latest"] if m]
URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"


class QuotaEpuise(Exception):
    pass


def _json(txt):
    """Extrait le premier objet JSON d'une réponse texte."""
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        res = json.loads(txt)
    except ValueError:
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            res = json.loads(m.group(0)) if m else None
        except ValueError:
            return None
    if isinstance(res, list):  # Gemini renvoie parfois [ {...} ]
        res = next((x for x in res if isinstance(x, dict)), None)
    return res if isinstance(res, dict) else None


def appeler(prompt, recherche_web=False):
    """Renvoie (objet JSON, liste des sources web [(titre, url)]) ou (None, []) sans clé."""
    if not CLE:
        return None, []
    corps = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
    if recherche_web:
        corps["tools"] = [{"google_search": {}}]  # recherche Google : les sources renvoyées sont réelles
    else:
        corps["generationConfig"]["responseMimeType"] = "application/json"
    quota = 0
    for modele in MODELES * 2:  # 2 passages : un modèle saturé peut se libérer
        if True:
            try:
                r = requests.post(URL.format(modele), json=corps, headers={"x-goog-api-key": CLE}, timeout=90)
            except requests.RequestException:
                continue
            if r.status_code in (404, 429) or r.status_code >= 500:
                quota += r.status_code == 429  # 404 = modèle retiré, 429 = quota du modèle, 5xx = saturé
                time.sleep(2)
                continue
            r.raise_for_status()
            cand = r.json()["candidates"][0]
            txt = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            web = [(c["web"].get("title", ""), c["web"]["uri"]) for c in cand.get("groundingMetadata", {}).get("groundingChunks", []) if "web" in c]
            return _json(txt), web
    if quota:
        raise QuotaEpuise("quota gratuit atteint")
    raise RuntimeError("aucun modèle Gemini disponible : " + ", ".join(MODELES))


from datetime import date
REGLES = f"""Nous sommes le {date.today().strftime('%d/%m/%Y')}. Les dates des articles sont au format jour/mois heure de cette année : n'ajoute jamais d'autre année.
Règles absolues :
- N'utilise QUE les informations des articles fournis (ou des résultats de recherche). N'invente aucun fait, chiffre, nom, lieu, heure ni source.
- Un fait est « confirmé » s'il est rapporté par au moins deux médias différents ou par une source officielle (police, parquet, préfecture, pompiers, ministère). Sinon il va dans « incertain ».
- Si une information manque, écris null. Réponds en français."""


def analyser(evenement, deja=(), gouts=""):
    """Analyse un événement regroupé. deja = titres des alertes déjà envoyées (anti-doublon). Renvoie un dict ou None."""
    arts = sorted(evenement["articles"], key=lambda a: a["ts"])
    arts = arts[:4] + arts[4:][-11:]  # le début de l'histoire + les derniers rebondissements
    lignes = "\n".join(f"- [{a['source']}] {a['titre']} — {a.get('resume', '')[:400]} ({a['date']})" for a in arts)
    premier = arts[0]["date"]
    deja_txt = "\n".join(f"{i}. {t}" for i, t in enumerate(deja)) or "aucune"
    prompt = f"""Tu fais la veille d'actualité du compte TikTok « L'Affaire » (@laffaire_france) : faits divers, drames, accidents, catastrophes,
politique, insolite, célébrités/rappeurs/youtubeurs dans une situation inattendue, sujets qui deviennent viraux. Priorité : France, puis Europe.
Les vidéos qui marchent : « Terrible drame, … » / « On vient de l'apprendre, … » + « Voici ce que l'on sait. », récit chronologique sourcé, vraie vidéo virale du sujet à l'écran.

Voici les articles qui parlent du même événement, du plus ancien au plus récent (première info : {premier}) :
{lignes}
Si la première info date de plus de 12 h, ne note haut que s'il y a un VRAI nouveau rebondissement dans les articles récents ; sinon score_tiktok ≤ 4.

Goûts du créateur appris de ses clics (ajuste la note d'environ ±1 selon les catégories qu'il prépare ou ignore) : {gouts or 'pas encore de données'}

Alertes déjà envoyées ces dernières 24 h :
{deja_txt}

{REGLES}

Réponds avec ce JSON :
{{"doublon_de": numéro de l'alerte déjà envoyée qui raconte EXACTEMENT le même fait (pas un nouveau rebondissement) ou null,
"titre": "titre factuel court", "nouveau": "ce qui est nouveau dans les dernières heures, ou null si rien", "resume": "3 phrases maximum", "lieu": "ville, pays ou null", "heure": "date/heure de l'événement ou null",
"zone": "France" ou "Europe" ou "Monde", "categorie": "fait divers|accident|catastrophe|politique|insolite|celebrite|international|autre",
"faits_confirmes": ["..."], "incertain": ["..."], "score_tiktok": 0-10, "raison_score": "1 phrase",
"angle": "angle de vidéo pour L'Affaire en 1-2 phrases", "accroche": "1re phrase de la voix off", "recherche_video": ["2 ou 3 requêtes pour trouver la vidéo originale sur TikTok/X/YouTube"]}}
Barème score_tiktok : 9-10 = choc national avec vidéo virale ; 7-8 = fort potentiel en France ; 5-6 = intéressant ; 0-4 = peu adapté (économie, sport ordinaire, international lointain)."""
    res, _ = appeler(prompt)
    return res


def approfondir(evenement):
    """Recherche web réelle (Google) sur l'événement. Renvoie (dict, sources)."""
    a = evenement.get("analyse") or {}
    sujet = a.get("titre") or evenement["articles"][0]["titre"]
    prompt = f"""Fais une recherche approfondie sur cet événement : « {sujet} » ({a.get('lieu') or ''}, {a.get('heure') or ''}).
Cherche : les derniers éléments, les déclarations officielles (police, parquet, préfecture), les vidéos originales qui circulent (TikTok, X, Instagram, YouTube) et qui les a publiées.
{REGLES}
Réponds UNIQUEMENT avec ce JSON :
{{"nouveaux_elements": ["..."], "officiel": ["déclaration + qui"], "faits_confirmes": ["..."], "incertain": ["..."],
"videos": [{{"description": "...", "plateforme": "...", "compte": "@... ou null"}}], "score_tiktok": 0-10, "angle": "..."}}"""
    return appeler(prompt, recherche_web=True)


def preparer(evenement, extra):
    """Prépare le dossier de montage (script en parties + indications). Renvoie un dict ou None."""
    a = evenement.get("analyse") or {}
    lignes = "\n".join(f"- [{x['source']}] {x['titre']} — {x.get('resume', '')[:500]}" for x in evenement["articles"][:20])
    prompt = f"""Prépare une vidéo TikTok pour « L'Affaire » (@laffaire_france), style @actuchrono60 (modèle n° 2) :
- voix off de 170 à 190 mots au total (COMPTE-LES : moins de 160 mots = vidéo trop courte, interdit), découpée en 5 à 7 parties (une partie = un plan d'images) ;
- la 1re partie commence par « On vient de l'apprendre, » ou « Terrible drame, » et donne tout le fait en une phrase, la 2e commence par « Voici ce que l'on sait. » ;
- récit chronologique : date + lieu précis, qui, quoi, comment, chiffres, puis la source (« Selon … »), les réactions, et une FIN FACTUELLE (pas de question, pas d'« abonnez-vous ») ;
- ton journaliste neutre, sobre pour les drames, suspect non nommé, mineurs jamais nommés ;
- nombres et dates ÉCRITS EN LETTRES (la voix est générée par Fish Audio) ;
- titre à l'écran en bas à gauche (phrase courte qui finit par « ! ») + une ligne grise qui complète.

Articles :
{lignes}
Analyse : {json.dumps(a, ensure_ascii=False)}
Recherche complémentaire : {json.dumps(extra, ensure_ascii=False) if extra else 'aucune'}

{REGLES}

Réponds avec ce JSON :
{{"titre_court": "3-5 mots pour le nom du dossier", "titre_ecran": "...!", "ligne_grise": "...", "parts": ["partie 1", "..."],
"plans": [{{"partie": 1, "images": "quelles images montrer (vraie vidéo d'abord)", "effet": "zoom / arrêt sur image + flèche sur … / carte du lieu / capture d'article", "incrustation": "texte ou null"}}],
"miniature": {{"lignes": "LIGNE 1|LIGNE 2|LIGNE BLEUE", "sous_titre": "..."}},
"description": "description TikTok prête à coller (titre choc ! 🚨 + 2-3 phrases + une question au public)",
"hashtags": ["#...", "#...", "#...", "#...", "#..."], "recherche_video": ["requêtes yt-dlp / TikTok / X"],
"a_verifier": ["points à revérifier avant publication"], "modele_conseille": 2 ou 3}}"""
    res, _ = appeler(prompt)
    return res
