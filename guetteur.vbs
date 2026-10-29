' Lance guetteur.ps1 sans ouvrir de fenetre (utilise par la tache Windows « Guetteur laffaire »)
Set sh = CreateObject("WScript.Shell")
dossier = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & dossier & "\guetteur.ps1""", 0, True
