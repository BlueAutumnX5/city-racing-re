# Wait for game.exe to exit, then back up the live exe, rebuild with racemod (current state)
# and verify against an independent build. Gives up after $WaitMinutes minutes without touching anything.
param([string]$Label = "chunk-activation", [string[]]$Extra = @("view"), [int]$WaitMinutes = 30)
# -Extra takes several: -Extra nodamage,panini (each becomes its own argument to racemod)
$work = Split-Path -Parent $PSScriptRoot
$py = if (Test-Path "$work\.venv\Scripts\python.exe") { "$work\.venv\Scripts\python.exe" } else { (Get-Command python).Source }
$deadline = (Get-Date).AddMinutes($WaitMinutes)
while (Get-Process game -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $deadline) { "gave up: game still running after $WaitMinutes minutes, nothing installed"; exit 1 }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 2
"game closed at $(Get-Date -Format HH:mm:ss); installing"
$bk = "$work\backups\$(Get-Date -Format yyyy-MM-dd)_before-$Label"
New-Item -ItemType Directory -Force $bk | Out-Null
$gameExe = (& $py -c "import sys; sys.path.insert(0, r'$work'); import crpaths; print(crpaths.GAME_EXE)")
Copy-Item $gameExe $bk -Force
Copy-Item "$work\racemod_state.json" $bk -Force
"backup: $bk (sha $((Get-FileHash "$bk\game.exe").Hash.Substring(0,16)))"
Set-Location $work
& $py racemod.py extras on @Extra 2>&1 | Where-Object { $_ -notmatch "^\s+patched 0x|^note:" }
& $py "$work\re-tools\verify_install.py"
"done at $(Get-Date -Format HH:mm:ss)"
