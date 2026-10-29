"""Réglages de la veille @laffaire_france : sources, mots-clés, seuils."""

# Flux RSS testés le 28/10/2026 (tous répondent en HTTP 200).
# (nom affiché, url, pays, type)  type : "article" ou "video"
FLUX = [
    ("franceinfo", "https://www.francetvinfo.fr/titres.rss", "FR", "article"),
    ("franceinfo faits divers", "https://www.francetvinfo.fr/faits-divers.rss", "FR", "article"),
    ("Le Monde", "https://www.lemonde.fr/rss/une.xml", "FR", "article"),
    ("Le Figaro", "https://www.lefigaro.fr/rss/figaro_actualites.xml", "FR", "article"),
    ("20 Minutes", "https://www.20minutes.fr/feeds/rss-une.xml", "FR", "article"),
    ("BFMTV", "https://www.bfmtv.com/rss/news-24-7/", "FR", "article"),
    ("Le Parisien", "https://feeds.leparisien.fr/leparisien/rss", "FR", "article"),
    ("Ouest-France", "https://www.ouest-france.fr/rss/une", "FR", "article"),
    ("Libération", "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml", "FR", "article"),
    ("La Dépêche", "https://www.ladepeche.fr/rss.xml", "FR", "article"),
    ("Actu17", "https://actu17.fr/feed/", "FR", "article"),
    ("France 24", "https://www.france24.com/fr/rss", "EU", "article"),
    ("France 24 Europe", "https://www.france24.com/fr/europe/rss", "EU", "article"),
    ("Euronews", "https://fr.euronews.com/rss", "EU", "article"),
    ("Google Actualités", "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr", "FR", "article"),
    ("Google Actualités (alertes)", "https://news.google.com/rss/search?q=incendie+OR+accident+OR+fusillade+OR+explosion+OR+drame+OR+interpell%C3%A9+when:2h&hl=fr&gl=FR&ceid=FR:fr", "FR", "article"),
    ("Google Actualités (vidéo virale)", "https://news.google.com/rss/search?q=%22vid%C3%A9o%22+(virale+OR+%22r%C3%A9seaux+sociaux%22)+when:6h&hl=fr&gl=FR&ceid=FR:fr", "FR", "article"),
    # Chaînes YouTube d'info (flux officiels YouTube, sans clé)
    ("YouTube BFMTV", "https://www.youtube.com/feeds/videos.xml?channel_id=UCXwDLMDV86ldKoFVc_g8P0g", "FR", "video"),
    ("YouTube franceinfo", "https://www.youtube.com/feeds/videos.xml?channel_id=UCO6K_kkdP-lnSCiO3tPx7WA", "FR", "video"),
    ("YouTube Le Parisien", "https://www.youtube.com/feeds/videos.xml?channel_id=UCfHn_8-ehdem86fEvlFg-Gw", "FR", "video"),
    ("YouTube CLPRESS", "https://www.youtube.com/feeds/videos.xml?channel_id=UChjC3WOBMIm9QVVSEBtIkWA", "FR", "video"),
    ("YouTube Brut", "https://www.youtube.com/feeds/videos.xml?channel_id=UCSKdvgqdnj72_SLggp7BDTg", "FR", "video"),
    ("YouTube TF1 Info", "https://www.youtube.com/feeds/videos.xml?channel_id=UCsrPUA0ZSDCNZC6wyRlR7ZA", "FR", "video"),
    ("YouTube LCI", "https://www.youtube.com/feeds/videos.xml?channel_id=UCewhc0fvja891XkpIPGRMxQ", "FR", "video"),
    ("YouTube Le Figaro", "https://www.youtube.com/feeds/videos.xml?channel_id=UCCDz_XYeKWd0OIyjp95dqyQ", "FR", "video"),
    ("YouTube CNEWS", "https://www.youtube.com/feeds/videos.xml?channel_id=UCciBAhIME9MQEmGbBPnh44g", "FR", "video"),
    ("YouTube Euronews", "https://www.youtube.com/feeds/videos.xml?channel_id=UCW2QcKZiU8aUGg4yxCIditg", "EU", "video"),
    # Flux « en continu » / rubriques rapides (testés le 28/10/2026)
    ("Le Monde (en continu)", "https://www.lemonde.fr/rss/en_continu.xml", "FR", "article"),
    ("Le Figaro (flash actu)", "https://www.lefigaro.fr/rss/figaro_flash-actu.xml", "FR", "article"),
    ("franceinfo France", "https://www.francetvinfo.fr/france.rss", "FR", "article"),
    ("BFMTV police-justice", "https://www.bfmtv.com/rss/police-justice/", "FR", "article"),
    ("Le Parisien faits divers", "https://www.leparisien.fr/faits-divers/rss.xml", "FR", "article"),
    ("Libération police-justice", "https://www.liberation.fr/arc/outboundfeeds/rss-all/category/societe/police-justice/?outputType=xml", "FR", "article"),
    ("CNEWS", "https://www.cnews.fr/rss.xml", "FR", "article"),
    ("Europe 1", "https://www.europe1.fr/rss.xml", "FR", "article"),
    ("Sud Ouest", "https://www.sudouest.fr/rss.xml", "FR", "article"),
    ("Ouest-France France", "https://www.ouest-france.fr/rss/france", "FR", "article"),
    # Presse régionale (faits divers locaux, souvent en premier) — testés le 28/10/2026
    ("actu.fr faits divers", "https://actu.fr/faits-divers/rss.xml", "FR", "article"),
    ("France Bleu", "https://www.francebleu.fr/rss/infos.xml", "FR", "article"),
    ("Le Progrès faits divers", "https://www.leprogres.fr/faits-divers-justice/rss", "FR", "article"),
    ("Le Dauphiné faits divers", "https://www.ledauphine.com/faits-divers-justice/rss", "FR", "article"),
    ("Nice-Matin faits divers", "https://www.nicematin.com/faits-divers/rss", "FR", "article"),
    ("La Dépêche faits divers", "https://www.ladepeche.fr/faits-divers/rss.xml", "FR", "article"),
    ("Midi Libre", "https://www.midilibre.fr/rss.xml", "FR", "article"),
    ("L'Indépendant", "https://www.lindependant.fr/rss.xml", "FR", "article"),
    ("L'Est Républicain", "https://www.estrepublicain.fr/rss", "FR", "article"),
    ("DNA", "https://www.dna.fr/rss", "FR", "article"),
    ("Le Républicain lorrain", "https://www.republicain-lorrain.fr/rss", "FR", "article"),
    ("Vosges Matin", "https://www.vosgesmatin.fr/rss", "FR", "article"),
    ("Le Bien Public", "https://www.bienpublic.com/rss", "FR", "article"),
    ("Le JSL", "https://www.lejsl.com/rss", "FR", "article"),
    ("Le Parisien 93", "https://www.leparisien.fr/seine-saint-denis-93/rss.xml", "FR", "article"),
    # Bluesky : comptes officiels (handle = nom de domaine du média, donc vérifié), lus sans clé
    ("AFP (Bluesky)", "bsky:afp.com", "FR", "article"),
    ("franceinfo (Bluesky)", "bsky:franceinfo.fr", "FR", "article"),
    ("BFMTV (Bluesky)", "bsky:bfmtv.com", "FR", "article"),
    ("Le Monde (Bluesky)", "bsky:lemonde.fr", "FR", "article"),
    ("Le Parisien (Bluesky)", "bsky:leparisien.fr", "FR", "article"),
    ("Le Figaro (Bluesky)", "bsky:lefigaro.fr", "FR", "article"),
    ("Libération (Bluesky)", "bsky:liberation.fr", "FR", "article"),
    ("Le Point (Bluesky)", "bsky:lepoint.fr", "FR", "article"),
    ("France 24 (Bluesky)", "bsky:france24.com", "EU", "article"),
    # Chaînes Telegram publiques (page t.me/s, sans clé)
    ("Actu17 (Telegram)", "tg:actu17", "FR", "article"),
    # Agrégateur non officiel : sert seulement de signal rapide, jamais de source seule (absent de la liste des médias connus)
    ("Infos Françaises (Telegram, non vérifié)", "tg:infosfrancaises", "FR", "article"),
]

# Mots-clés (sans accents, en minuscules) -> points. Sert à trier avant l'IA.
MOTS = {
    3.0: ["drame", "tragique", "mort", "morts", "tue", "tues", "tuee", "deces", "decede", "victime", "victimes",
          "incendie", "explosion", "effondrement", "inondation", "inondations", "seisme", "tempete", "catastrophe", "crash",
          "accident", "collision", "deraillement", "fusillade", "coups de feu", "attaque", "poignarde", "couteau", "agression",
          "meurtre", "homicide", "enlevement", "disparition", "disparu", "disparue", "retrouve mort", "retrouvee morte", "attentat"],
    2.5: ["rappeur", "youtubeur", "influenceur", "influenceuse", "tiktokeur", "tiktokeuse", "chanteur", "chanteuse", "star",
          "jul", "nekfeu", "ninho", "aya nakamura", "squeezie", "inoxtag", "mbappe", "orelsan", "booba", "gims"],
    2.0: ["video", "images", "viral", "virale", "reseaux sociaux", "filme", "filmee", "scene", "insolite", "incroyable",
          "improbable", "etonnant", "heros", "course-poursuite", "rodeo", "emeute", "emeutes", "evacue", "evacuation"],
    1.5: ["police", "policier", "gendarmerie", "gendarme", "pompiers", "interpelle", "interpelles", "garde a vue", "prefet",
          "procureur", "enquete", "suspect", "macron", "gouvernement", "ministre", "premier ministre", "assemblee", "lfi",
          "melenchon", "bardella", "le pen", "retailleau", "manifestation", "greve", "blocage"],
    1.0: ["en direct", "alerte", "urgent", "ce que l'on sait", "ce que l on sait"],
    -3.0: ["bourse", "cac 40", "recette", "bon plan", "promo", "horoscope", "soldes", "test :", "comparatif", "mots croises",
           "programme tv", "quiz"],
}

# « ACTU URGENTE » : faits graves qui font le plus de vues (bandeau rouge, passe la nuit et le /seuil, pas la /pause)
# mot entier, sauf ceux finissant par * (début de mot : racis* = raciste, racisme…)
MOTS_URGENTS = ["attentat*", "attaque", "attaques", "terroris*", "meurtre*", "meurtri*", "tue", "tues", "tuee", "tuees", "assassin*", "poignard*",
                "couteau", "fusillade*", "coups de feu", "crime", "crimes", "racis*", "antisemit*", "agression*", "viol", "viols", "enlevement*",
                "otage*", "emeute*", "lynch*", "egorge*", "decapit*", "explosion*", "massacre*"]
SEUIL_URGENT = 7         # note IA minimale pour une actu urgente

# Bot viral : comptes TikTok d'actualité FR surveillés (lisibles avec yt-dlp, testés le 29/10/2026)
COMPTES_TIKTOK = ["actuchrono60", "hugodecrypte", "brutofficiel", "konbini", "lemondefr", "franceinfo", "bfmtv", "leparisien",
                  "cnews", "tf1info", "loopsider", "ouestfrance", "europe1",
                  # comptes d'actu suivis par @laffaire_france (relevés le 29/10/2026)
                  "minutepeople.fr", "minute.politique.2027", "le.pouls2", "micronuit", "politiquepixels", "20minutesfrance", "rudy.actu",
                  "ajplusfrancais", "tesprevenu", "lejournal.actu", "souley_28", "rtsinfo", "mathildepanot", "captelinfo", "bonnequestion.tv",
                  "quotidienofficiel", "jeunessedanslarue", "afpfr", "unmomentactu", "infofrance.tv",
                  # suite des abonnements (captures du 29/10/2026, identifiants retrouvés par la recherche TikTok)
                  "la.derniereinfo", "alerte.min", "lavoixdunord", "actu24h00", "le_progres_", "info.direct44", "france24actu", "usabrief0",
                  "actudivers.fr", "noahdecrypte", "france24infos", "actuenbref.tv", "le20hfrancetelevisions", "ladepechedumidi", "f3cvdl",
                  "faisdivers.fr", "actufrance_33", "lestrepublicain", "parismatch", "m6info_", "larochesuryonactu", "lejournal.actu2",
                  "franceecho", "faits.divers.fr5", "journalsudouest", "journalfrancetv", "raison.patriote", "lehuffpostfr", "nextenews",
                  "laprovence_", "20minutesonline", "kat_info", "newo.telop", "lefigaro", "mediapartfr", "lepointactuu", "tera24_24",
                  "actuone.tv1", "tiktok.ragot", "infoexpress35", "actuexpress23", "france3nouvelleaquitaine", "france3grandest",
                  "streetpress_", "midilibre", "infoglobale.media", "stupmedia", "flashinfosoff", "ostor227", "actufrance14", "flash_actu24",
                  "lesignal.actu", "reclist", "zoomdefrance", "askyp.france", "letiktokinfo", "josselin.journaliste", "actucru",
                  "actunowtv", "tera24_usa", "tera24_england"]
# pour garder le tour cloud sous 60 s, chaque tour lit une moitié des comptes (en alternance) : chaque compte est lu toutes les heures
MOITIE_PAR_TOUR = True

SEUIL_ANALYSE = 5.0      # score mots-clés à partir duquel on demande l'avis de l'IA
SEUIL_NOTIF_IA = 7       # note TikTok (sur 10) minimale pour envoyer une alerte (29/10 : plus de 🟡 faibles, seulement 🟠 🟢 🔴)
SEUIL_NOTIF_SANS_IA = 9  # si pas de clé IA : score mots-clés minimal pour alerter
MAX_ANALYSES_PAR_TOUR = 4  # protège le quota gratuit de l'IA
AGE_MAX_HEURES = 36      # on ignore les articles plus vieux
GARDER_HEURES = 72       # durée de vie d'un événement en mémoire
