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
# dépôt privé : on s'identifie avec la connexion GitHub déjà faite (gh portable)
GH = Path(os.environ.get("LOCALAPPDATA", "")) / "outils" / "gh" / "bin" / "gh.exe"
jeton = os.environ.get("GITHUB_TOKEN", "")  # le Python du Microsoft Store ne voit pas toujours gh : passer $env:GITHUB_TOKEN = (gh auth token)
if not jeton:
    try:
        jeton = subprocess.run([str(GH), "auth", "token"], capture_output=True, text=True).stdout.strip()
    except OSError:
        pass
S = requests.Session()
if jeton:
    S.headers["Authorization"] = "Bearer " + jeton
requests = S  # toutes les requêtes ci-dessous passent par la session identifiée
liste = requests.get(API, timeout=30).json()
noms = sorted((x["name"] for x in liste if x.get("type") == "dir"), reverse=True) if isinstance(liste, list) else []
TRAITES = ICI / "traites.txt"  # sujets deja montes sur ce PC (pour la tache automatique)
faits = set(TRAITES.read_text(encoding="utf-8").split()) if TRAITES.exists() else set()
def demandes():
    """sujets/demandes.json : boutons « Refaire » / « Modifier le texte » cliques sous un message « Video prete »."""
    r = requests.get(f"{API}/demandes.json", timeout=30)
    if r.status_code != 200:
        return {}
    return json.loads(requests.get(r.json()["download_url"], timeout=30).content)


if sys.argv[1:2] == ["--nouveaux"]:  # liste ce qui reste a faire ; rien = rien a faire
    lignes = [n for n in noms if n not in faits]
    for nom, d in demandes().items():  # nouvelle demande = « nom#n » pas encore dans traites.txt
        if f"{nom}#{d['n']}" not in faits:
            lignes.append(f"{nom}#{d['n']}  ← DEMANDE « {d['type']} » : " + (d.get("texte") or "refaire la vidéo (mieux, sans changer les faits)"))
    print("\n".join(lignes))
    raise SystemExit
if sys.argv[1:2] == ["--fait"]:
    with open(TRAITES, "a", encoding="utf-8") as f:
        f.write(sys.argv[2] + "\n")
    raise SystemExit
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
print("Modèle choisi sur Telegram :", sujet.get("modele", "non précisé"))

# Vidéos : celles trouvées par la veille + recherche YouTube (yt-dlp, comme dans le workflow habituel)
videos = [v["lien"] for v in sujet["videos"] if any(d in v["lien"] for d in ("youtube.com", "youtu.be", "tiktok.com"))][:4]
candidats = []
for q in sujet["recherche_video"][:3]:
    r = subprocess.run(["yt-dlp", "--encoding", "utf-8", "--flat-playlist", "--print", "%(webpage_url)s | %(channel)s | %(title)s | %(duration)s s",
                        f"ytsearch8:{q}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    candidats += (r.stdout or "").splitlines()
    if r.returncode: print("  yt-dlp :", (r.stderr or "")[-300:])
(dos / "sources_video" / "candidats.txt").write_text("\n".join(candidats), encoding="utf-8")
for i, url in enumerate(videos):
    subprocess.run(["yt-dlp", "-f", "bv*[height<=1920]+ba/b", "--merge-output-format", "mp4", "--write-info-json",
                    "-o", str(dos / "sources_video" / f"veille{i + 1}.%(ext)s"), url])
print(f"{len(videos)} vidéo(s) téléchargée(s), {len(candidats)} candidates dans sources_video/candidats.txt")
