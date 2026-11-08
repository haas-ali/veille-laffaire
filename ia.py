"""Appels à l'IA (Google Gemini, offre gratuite). Sans clé GEMINI_API_KEY, tout renvoie None."""
import json, os, re, time
import requests

CLE = os.environ.get("GEMINI_API_KEY", "").strip()
MODELES = [m for m in [os.environ.get("GEMINI_MODELE", "").strip(), "gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-lite-latest"] if m]
RAPIDES = ["gemini-flash-lite-latest", "gemini-3.5-flash"]  # analyses courantes : rapide, quota gratuit plus large
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


def appeler(prompt, recherche_web=False, modeles=None):
    """Renvoie (objet JSON, liste des sources web [(titre, url)]) ou (None, []) sans clé."""
    if not CLE:
        return None, []
    corps = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
    if recherche_web:
        corps["tools"] = [{"google_search": {}}]  # recherche Google : les sources renvoyées sont réelles
    else:
        corps["generationConfig"]["responseMimeType"] = "application/json"
    quota = 0
    for modele in (modeles or MODELES) * 2:  # 2 passages : un modèle saturé peut se libérer
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
    prompt = f"""Tu es l'éditeur du bot « Dernière info 🚨 » du compte TikTok « L'Affaire » (@laffaire_france). Question à trancher :
« Cette info mérite-t-elle VRAIMENT une vidéo TikTok, ou faut-il l'ignorer ? » Mieux vaut 3 excellentes alertes que 30 inutiles.
Ce qui intéresse : faits divers graves ou aux circonstances inhabituelles, POLÉMIQUES et scandales qui font réagir (propos, clashs,
accusations et réponses), people/influenceurs (séparations, disputes, révélations, rebondissements), youtubeurs/streamers/gaming
(grosse annonce, projet, sortie très attendue, polémique), manifestations/lois/décisions qui touchent les Français, et tout sujet
inattendu qui s'emballe. Priorité France, puis Europe. À IGNORER (banal=true) : décès isolé ou accident ordinaire sans élément
particulier, petite déclaration politique, simple désaccord, petite manif locale, simple nouvelle vidéo d'un créateur.
Ne confonds jamais une accusation avec un fait établi ; un suspect n'est pas coupable avant une décision définitive.

Voici les articles qui parlent du même événement, du plus ancien au plus récent (première info : {premier}) :
{lignes}
Si la première info date de plus de 12 h, ne note haut que s'il y a un VRAI nouveau rebondissement dans les articles récents ; sinon score_tiktok ≤ 4.

Goûts du créateur appris de ses clics (ajuste la note d'environ ±1 selon les catégories qu'il prépare ou ignore) : {gouts or 'pas encore de données'}

Alertes déjà envoyées ces dernières 24 h :
{deja_txt}

{REGLES}

Réponds avec ce JSON :
{{"doublon_de": numéro de l'alerte déjà envoyée qui raconte EXACTEMENT le même fait (pas un nouveau rebondissement) ou null,
"urgent": true si c'est une actu grave qui fait énormément de vues (attaque, attentat, meurtre, crime, agression raciste ou antisémite, fusillade, prise d'otages, émeute, enlèvement, viol, terrorisme, catastrophe meurtrière) et qui touche beaucoup de monde en France, sinon false,
"titre": "titre factuel court (8 mots max)", "nouveau": "ce qui est nouveau dans les dernières heures, ou null si rien", "resume": "2 phrases maximum, mots simples",
"lieu": "ville, région, pays ; null si sans objet (annonce d'un créateur…)", "heure": "date/heure de l'événement ou null",
"date_faits": "JJ/MM ou null si inconnue", "heure_faits": "HH:MM ou null si inconnue",
"personnes": ["noms propres des personnes concernées (personnalités, victimes nommées publiquement, suspects déjà nommés par les médias)"],
"lieux": ["villes / lieux précis"],
"zone": "France" ou "Europe" ou "Monde", "categorie": "fait divers|polemique|people|createurs|politique|international|catastrophe|insolite|autre",
"sous_scores": {{"narratif": 0-10, "interet_public": 0-10, "visuels": 0-10, "explicable": 0-10}},
"fiabilite": "confirme" (au moins 2 médias fiables ou source officielle) | "partiel" | "verification" (rumeur, une seule source, réseaux sociaux),
"source_officielle": true si police/parquet/préfecture/ministère/la personne elle-même s'exprime, sinon false,
"banal": true si sans intérêt particulier (voir À IGNORER), "exceptionnel": true seulement pour un événement urgent et exceptionnel en France (attentat, catastrophe meurtrière, fait d'une ampleur nationale) — jamais pour attirer l'attention,
"rebondissement_majeur": true si les articles récents apportent un fait nouveau MAJEUR (arrestation, aveu, preuve, réponse officielle, décision de justice), sinon false,
"pourquoi": "1 phrase : pourquoi ça peut marcher sur TikTok", "nouveaute": "1 phrase : pourquoi alerter MAINTENANT",
"faits_confirmes": ["..."], "incertain": ["..."], "score_tiktok": 0-10, "raison_score": "1 phrase",
"angle": "angle de vidéo pour L'Affaire en 1-2 phrases", "accroche": "1re phrase de la voix off", "recherche_video": ["2 ou 3 requêtes COURTES (2-4 mots, noms propres) pour trouver la vidéo originale sur TikTok/X/YouTube ; la 1re en français, une dans la langue du pays si c'est à l'étranger"],
"verdict": "VA PERCER" | "PEUT PERCER" | "NE VA PAS PERCER" (sur TikTok en France, honnête, sans gonfler),
"pour": ["2 ou 3 raisons concrètes qui font que ça peut faire des vues (émotion, choc, personnalité connue, vidéo choc qui circule, débat…)"],
"contre": ["1 à 3 risques concrets (déjà vu partout, pas d'images, trop compliqué, sujet lointain, info pas confirmée…)"],
"images_dispo": "1 phrase : quelles vraies images existent probablement (vidéo amateur, caméra de surveillance, conférence de presse, photos…) ou 'aucune image connue'"}}
Barème score_tiktok : 9-10 = choc national avec vidéo virale ; 7-8 = fort potentiel en France ; 5-6 = intéressant ; 0-4 = peu adapté (économie, sport ordinaire, international lointain)."""
    res, _ = appeler(prompt, modeles=RAPIDES)
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


STYLES_MODELES = {
    1: "modèle n° 1 (prompt maître L'Affaire) : gros titre d'accroche, carte du lieu, schéma 3D si utile, question au public au milieu et à la fin",
    2: "modèle n° 2 (style @actuchrono60) : vidéo réelle plein écran, récit chronologique sourcé, fin factuelle sans question",
    3: "modèle n° 3 : comme le 2, avec arrêts sur image, zooms et flèches sur les extraits, son d'origine entre les parties de voix",
    4: "modèle n° 4 (méthode @minutepeople.fr) : script dense ~210-235 mots, 7 temps (fait complet, déroulé une info par phrase, autre camp, contexte à la fin), carte graphique toutes les 10-15 s, preuves en flou puis net",
}


def preparer(evenement, extra, modele=2):
    """Prépare le dossier de montage (script en parties + indications). Renvoie un dict ou None."""
    a = evenement.get("analyse") or {}
    lignes = "\n".join(f"- [{x['source']}] {x['titre']} — {x.get('resume', '')[:500]}" for x in evenement["articles"][:20])
    style = STYLES_MODELES.get(modele, STYLES_MODELES[2])
    mots = "210 à 235" if modele == 4 else "170 à 190"
    debut = ("la 1re partie donne tout le fait en une phrase, la 2e commence par « Voici ce que l'on sait. »" if modele == 4 else
             "la 1re phrase entre DIRECTEMENT dans le vif du sujet (le fait nouveau, sans préambule ni « On vient de l'apprendre »)")
    prompt = f"""Prépare une vidéo TikTok pour « L'Affaire » (@laffaire_france), {style} :
- voix off de {mots} mots au total (COMPTE-LES : une vidéo de moins de 61 s est interdite), découpée en 5 à 8 parties (une partie = un plan d'images) ;
- {debut} ;
- déroulé : date + lieu précis, qui, quoi, comment, chiffres, la source (« Selon … »), les réactions, et le CONTEXTE (rappel des faits, bilan) À LA FIN ;
- fin factuelle, sauf modèle 1 (question au public + « Abonne-toi à L'Affaire ») ;
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
