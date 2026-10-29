# Guetteur du PC (tache Windows toutes les 10 min, PC allume) : regarde les comptes de config.COMPTES_ESPION avec yt-dlp.
# Des qu'une NOUVELLE video apparait, il lance tout de suite le tour « Observateur » sur GitHub (alerte + fiche en 1-2 min).
# Il n'envoie rien lui-meme : le cloud garde la memoire des alertes, donc jamais de doublon. Ne consomme aucun token Claude.
# Journal : donnees\guetteur.log
$ErrorActionPreference = "Continue"
$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$gh = "$env:LOCALAPPDATA\outils\gh\bin\gh.exe"
$vusFichier = "$ici\donnees\guetteur_vus.txt"
$log = "$ici\donnees\guetteur.log"
New-Item -ItemType Directory -Force "$ici\donnees" | Out-Null
function Ecrire($t) { Add-Content $log ("{0:dd/MM HH:mm} {1}" -f (Get-Date), $t) -Encoding utf8 }

# comptes lus dans config.py (une seule liste a tenir a jour)
$ligne = (Get-Content "$ici\config.py" -Encoding utf8 | Where-Object { $_ -match '^COMPTES_ESPION\s*=' })
$comptes = [regex]::Matches($ligne, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
if (-not $comptes) { Ecrire "! COMPTES_ESPION introuvable"; exit 1 }

$premier = -not (Test-Path $vusFichier)
$vus = @{}
if (-not $premier) { Get-Content $vusFichier | ForEach-Object { $vus[$_] = 1 } }
$maintenant = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$nouveaux = @()
$lus = @()
foreach ($c in $comptes) {
    $sortie = & yt-dlp --flat-playlist --playlist-items 1-8 --print "%(id)s %(timestamp)s" "https://www.tiktok.com/@$c" 2>$null
    if (-not $sortie) { Ecrire "! @$c : rien lu"; continue }
    foreach ($l in $sortie) {
        $id, $ts = $l -split " "
        if ($id -notmatch '^\d+$') { continue }
        $lus += $id
        if (-not $vus.ContainsKey($id) -and $ts -match '^\d+$' -and ($maintenant - [long]$ts) -lt 6 * 3600) { $nouveaux += "@$c/$id" }
    }
}

if ($nouveaux -and -not $premier) {
    & $gh workflow run observateur.yml --repo haas-ali/veille-laffaire 2>$null
    if ($LASTEXITCODE -eq 0) { Ecrire ("nouvelle(s) video(s) : " + ($nouveaux -join ", ") + " -> tour Observateur lance") }
    else { Ecrire ("! nouvelle(s) video(s) " + ($nouveaux -join ", ") + " mais lancement GitHub rate"); $lus = @() }  # on reessaiera dans 10 min
} elseif ($premier) { Ecrire "premier passage : $($lus.Count) videos enregistrees" }

# memoire : 600 identifiants max ; journal : 300 lignes max
$tout = @((Get-Content $vusFichier -ErrorAction SilentlyContinue) + $lus | Select-Object -Unique | Select-Object -Last 600)
if ($tout.Count) { Set-Content $vusFichier $tout -Encoding ascii }
if (Test-Path $log) { $j = Get-Content $log -Encoding utf8; if ($j.Count -gt 300) { Set-Content $log ($j | Select-Object -Last 300) -Encoding utf8 } }
