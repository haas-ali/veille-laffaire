"""Sur le PC : ramène un sujet validé (bouton PRÉPARER LA VIDÉO) dans un dossier de montage.

python recuperer_sujet.py            -> liste les sujets préparés
python recuperer_sujet.py <nom>      -> crée « TikTok laffaire_france <titre> » et télécharge les vidéos trouvées

Le nom du dépôt GitHub est lu dans .env (VEILLE_DEPOT=compte/depot). Ne publie rien."""
import json, os, subprocess, sys
from pathlib import Path
import requests

ICI = Path(__file__).parent
for ligne in (ICI / ".env").read_text(encoding="utf-8").splitlines() if (ICI / ".env").exists() else []:
    if "=" in ligne and not ligne.startswith("#"):
        k, v = ligne.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
DEPOT = os.environ.get("VEILLE_DEPOT", "")
RACINE = ICI.parent  # dossier « claude voix »
API = f"https://api.github.com/repos/{DEPOT}/contents/sujets"

if not DEPOT:
    raise SystemExit("Ajoute VEILLE_DEPOT=compte/depot dans veille_laffaire/.env")
liste = requests.get(API, timeout=30).json()
noms = sorted((x["name"] for x in liste if x.get("type") == "dir"), reverse=True) if isinstance(liste, list) else []
if len(sys.argv) < 2:
    print("\n".join(noms) or "Aucun sujet préparé pour l'instant.")
    raise SystemExit
nom = next((n for n in noms if sys.argv[1] in n), None)
if not nom:
    raise SystemExit("Sujet introuvable. Sujets : " + ", ".join(noms))

fichiers = requests.get(f"{API}/{nom}", timeout=30).json()
sujet = json.loads(requests.get(next(f["download_url"] for f in fichiers if f["name"] == "sujet.json"), timeout=30).content)
dos = RACINE / f"TikTok laffaire_france {sujet['titre']}"
(dos / "sources_video").mkdir(parents=True, exist_ok=True)
for f in fichiers:
    cible = dos / ("v2" if f["name"] == "parts.json" else "") / f["name"]
    cible.parent.mkdir(exist_ok=True)
    cible.write_bytes(requests.get(f["download_url"], timeout=60).content)
print("Dossier :", dos)

# Vidéos : celles trouvées par la veille + recherche YouTube (yt-dlp, comme dans le workflow habituel)
videos = [v["lien"] for v in sujet["videos"] if "youtube.com" in v["lien"] or "youtu.be" in v["lien"]][:4]
candidats = []
for q in sujet["recherche_video"][:3]:
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--print", "%(webpage_url)s | %(channel)s | %(title)s | %(duration)s s",
                        f"ytsearch8:{q}"], capture_output=True, text=True, encoding="utf-8")
    candidats += r.stdout.splitlines()
(dos / "sources_video" / "candidats.txt").write_text("\n".join(candidats), encoding="utf-8")
for i, url in enumerate(videos):
    subprocess.run(["yt-dlp", "-f", "bv*[height<=1920]+ba/b", "--merge-output-format", "mp4", "--write-info-json",
                    "-o", str(dos / "sources_video" / f"veille{i + 1}.%(ext)s"), url])
print(f"{len(videos)} vidéo(s) téléchargée(s), {len(candidats)} candidates dans sources_video/candidats.txt")
