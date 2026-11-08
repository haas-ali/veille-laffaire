"""Bot « Dernière info 🚨 » : décide QUOI envoyer (seulement 🟢 vert et 🔴 rouge), avec un score éditorial sur 100,
un niveau de fiabilité et un anti-doublons par AFFAIRE (personnes, lieux, faits), pas seulement par titre.

Tout ici est pur (pas de réseau) pour pouvoir être testé : voir tests/test_selection.py."""
import re, time, unicodedata

# ---------- Grille du score (sur 100, réglable) ----------
# Ce n'est PAS une probabilité de devenir viral : c'est une estimation éditoriale à partir des données disponibles.
POIDS = {
    "fraicheur": 15,     # l'info a moins de quelques heures (ou un vrai rebondissement récent)
    "narratif": 15,      # IA : une histoire qui se raconte (personnages, tension, rebondissement)
    "interet": 15,       # IA : intérêt du public français
    "reactions": 15,     # observé : nombre de médias + comptes TikTok d'actu qui en parlent
    "propagation": 10,   # observé : médias qui en parlent depuis 3 h (l'info s'emballe)
    "visuels": 10,       # IA + vidéos trouvées : images exploitables
    "nouveaute": 10,     # pas déjà couvert, ou rebondissement majeur
    "explicable": 10,    # IA : se raconte en 60 s
}
SEUIL_VERT = 72          # en dessous : aucune notification
SEUIL_VERT_NUIT = 85     # de 0 h à 7 h (Paris) : seuls les sujets très forts et le rouge passent
AGE_MAX_SANS_REBOND = 8   # heures (08/11, avant 24) : une info sortie il y a plus de 8 h n'est plus envoyée, sauf rebondissement majeur
ECART_REBOND = 6         # heures minimum entre deux alertes sur la même affaire (même si l'IA voit un rebondissement)
MAX_REBONDS = 1          # rebondissements envoyés au maximum par affaire (sur FENETRE_DOUBLON)
FENETRE_DOUBLON = 72     # heures : on compare avec les alertes envoyées pendant cette durée

CATEGORIES = {"fait divers": "🚓 Fait divers", "polemique": "💥 Polémique", "people": "⭐ People",
              "createurs": "🎮 Créateurs / gaming", "politique": "🏛️ Politique / société", "international": "🌍 International",
              "catastrophe": "🌪️ Catastrophe / accident", "insolite": "🤯 Insolite", "autre": "📰 Actu"}
FIABILITE = {"confirme": "Confirmé par des sources fiables", "partiel": "Partiellement confirmé", "verification": "En cours de vérification"}


def borne(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def sous_score(a, cle):
    """Sous-note IA 0-10 → 0-1 (absente = prudence : 0,4)."""
    v = ((a.get("sous_scores") or {}).get(cle))
    return borne(v / 10) if isinstance(v, (int, float)) else 0.4


def score100(ev, nb_medias, nb_tiktok, recents, age_h, a, deja_couvert=False):
    """Score éditorial sur 100 + détail par critère (pour l'expliquer et le tester)."""
    rebond = bool(a.get("rebondissement_majeur"))
    d = {
        "fraicheur": 1.0 if age_h <= 2 else 0.75 if age_h <= 4 else 0.45 if age_h <= 6 else 0.2 if age_h <= AGE_MAX_SANS_REBOND else 0.0,
        "narratif": sous_score(a, "narratif"),
        "interet": sous_score(a, "interet_public"),
        "reactions": borne((nb_medias + 1.5 * nb_tiktok) / 12),
        "propagation": borne(recents / 5),
        "visuels": max(sous_score(a, "visuels"), 0.8 if ev.get("videos_yt") or any(x["type"] == "video" for x in ev["articles"]) else 0),
        "nouveaute": 1.0 if not deja_couvert else (0.8 if rebond else 0.0),
        "explicable": sous_score(a, "explicable"),
    }
    if rebond:  # un vrai rebondissement redonne de la fraîcheur à une affaire ancienne
        d["fraicheur"] = max(d["fraicheur"], 0.75)
    total = round(sum(POIDS[k] * v for k, v in d.items()))
    if a.get("banal"):  # décès isolé, accident banal, déclaration ordinaire : plafonné sous le seuil
        total = min(total, SEUIL_VERT - 10)
    return total, d


def fiabilite(ev, a, nb_medias):
    """Confirmé (≥ 2 médias fiables ou source officielle) / partiel / en cours de vérification. L'IA ne peut que baisser le niveau."""
    officiel = bool(a.get("source_officielle"))
    base = "confirme" if (nb_medias >= 2 or officiel) else "partiel" if nb_medias == 1 else "verification"
    ia = a.get("fiabilite") if a.get("fiabilite") in FIABILITE else base
    ordre = ["verification", "partiel", "confirme"]
    return ordre[min(ordre.index(base), ordre.index(ia))]


def couleur(score, a, fiab, nuit=False, seuil=None):
    """🔴 rouge = exceptionnel/urgent ou rebondissement majeur d'une affaire forte (jamais pour attirer l'attention) ;
    🟢 vert = fort potentiel ; None = pas de notification. La couleur dépend du SUJET, jamais de la catégorie.
    seuil : seuil vert choisi par l'utilisateur (/seuil), sinon SEUIL_VERT."""
    s = seuil or SEUIL_VERT
    exceptionnel = bool(a.get("exceptionnel")) or (bool(a.get("rebondissement_majeur")) and score >= s + 5)
    if exceptionnel and fiab != "verification" and score >= s - 15:
        return "rouge"  # une urgence passe même si son score « viral » est un peu sous le seuil
    if score >= (max(s, SEUIL_VERT_NUIT) if nuit else s):
        return "vert"
    return None


def interet_mediatique(nb_medias, nb_tiktok):
    n = nb_medias + nb_tiktok
    return "très fort" if n >= 12 else "fort" if n >= 6 else "moyen" if n >= 3 else "faible"


# ---------- Anti-doublons par affaire ----------
def norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).split()


def entites(a):
    """Personnes et lieux nommés par l'IA, normalisés (« Maëva Ghennam » → {maeva, ghennam})."""
    pers = {w for p in (a.get("personnes") or []) for w in norm(p) if len(w) >= 3}
    lieux = {w for p in (a.get("lieux") or []) + ([a["lieu"]] if a.get("lieu") else []) for w in norm(p) if len(w) >= 3}
    lieux -= {"france", "paris", "europe", "est", "ouest", "nord", "sud", "grand", "haute", "haut", "bas", "basse", "cote", "saint",
              "sainte", "sur", "les", "lycee", "college", "ecole", "rue", "avenue", "rhone", "alpes", "provence", "azur", "loire",
              "etats", "unis", "royaume", "uni", "ile", "region", "departement"}  # trop larges pour identifier une affaire
    return pers, lieux


def cle_affaire(a):
    """Clé stable d'une affaire : personnes + lieux triés (indépendante de la formulation du titre)."""
    pers, lieux = entites(a)
    return "|".join(sorted(pers)) + "@" + "|".join(sorted(lieux))


MOTS_GENERIQUES = {"janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre",
                   "decembre", "proces", "proce", "ouverture", "manifestations", "manifestation", "violences", "enquete", "ouverte", "mort",
                   "morts", "mortel", "mortelle", "blesse", "blesses", "accuse", "plainte", "ministre", "interieur", "police",
                   "policiers", "gendarmes", "victime", "victimes", "drame", "affaire", "nouvelle", "france", "francais"}


def meme_affaire(a, envoye, mots_titre=set(), mots_envoye=set()):
    """Même affaire si : même clé, ou ≥ 2 mots de noms de personnes en commun, ou 1 personne + 1 lieu en commun,
    ou (sans personne nommée) lieu commun + ≥ 3 mots du titre en commun."""
    pers, lieux = entites(a)
    p2, l2 = set(envoye.get("personnes", [])), set(envoye.get("lieux", []))
    if cle_affaire(a) == envoye.get("cle") and (pers or lieux):
        return True
    cp, cl = pers & p2, lieux & l2
    commun = (mots_titre & mots_envoye) - MOTS_GENERIQUES
    # une personnalité seule ne suffit pas (un ministre est dans plein d'affaires différentes) : il faut aussi un lieu ou un mot du titre
    if cp and (cl or len(commun - cp) >= 1):
        return True
    if bool(cl) and len(commun) >= 2:
        return True
    # sans personne ni lieu reconnus (ex. « Cyberattaque EFS ») : les titres eux-mêmes
    return len(commun) >= 3 or len({w for w in commun if len(w) >= 7}) >= 2


def affaire(a, envoyes, mots_titre=set(), maintenant=None):
    """Toutes les alertes déjà envoyées sur la même affaire (fenêtre FENETRE_DOUBLON), de la plus ancienne à la plus récente."""
    lim = (maintenant or time.time()) - FENETRE_DOUBLON * 3600
    return [e for e in envoyes if e.get("ts", 0) >= lim and meme_affaire(a, e, mots_titre, set(e.get("mots", [])))]


def rebond_autorise(precedents, maintenant=None):
    """Un rebondissement ne repart que si la dernière alerte date d'au moins ECART_REBOND heures
    et qu'on n'a pas déjà envoyé MAX_REBONDS rebondissements sur cette affaire."""
    if not precedents:
        return True
    now = maintenant or time.time()
    return (now - precedents[-1]["ts"] >= ECART_REBOND * 3600
            and sum(1 for e in precedents if e.get("rebond")) < MAX_REBONDS)


def deja_envoye(a, envoyes, mots_titre=set(), maintenant=None):
    """Renvoie l'alerte déjà envoyée sur la même affaire (fenêtre FENETRE_DOUBLON), ou None."""
    lim = (maintenant or time.time()) - FENETRE_DOUBLON * 3600
    for e in reversed(envoyes):
        if e.get("ts", 0) >= lim and meme_affaire(a, e, mots_titre, set(e.get("mots", []))):
            return e
    return None


def texte_copie(titre, resume, date_lieu, score, fiab, lien):
    """Texte du bouton « Copier » : prêt à coller dans Claude (Telegram limite copy_text à 256 caractères)."""
    t = f"Claude, fais une vidéo L'Affaire : {titre}. {resume or ''}"
    fin = f" ({date_lieu}) {score}/100, {FIABILITE.get(fiab, fiab).lower()}. Revérifie les faits. Source : {lien.split('?')[0]}"
    if len(fin) > 150:  # lien trop long : on garde le nom du site
        fin = fin.split(" Source : ")[0] + " Source : " + (lien.split("/")[2] if "://" in lien else "")
    return (t[:256 - len(fin)].rstrip() + fin)[:256]
