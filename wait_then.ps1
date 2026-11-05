# Wait (up to $WaitMinutes) for game.exe to start, give it $Settle seconds to load, then run a
# read-only Python monitor from the work folder until the game exits.
param([Parameter(Mandatory)][string]$Script, [string]$Arg = "", [int]$WaitMinutes = 90, [int]$Settle = 15)
$work = $PSScriptRoot
$py = if (Test-Path "$work\.venv\Scripts\python.exe") { "$work\.venv\Scripts\python.exe" } else { (Get-Command python).Source }
$deadline = (Get-Date).AddMinutes($WaitMinutes)
while (-not (Get-Process game -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $deadline) { "game did not start within $WaitMinutes min"; exit 1 }
    Start-Sleep -Seconds 2
}
Start-Sleep -Seconds $Settle
"game started; running $Script"
if ($Arg) { & $py -u (Join-Path $work $Script) $Arg } else { & $py -u (Join-Path $work $Script) }
