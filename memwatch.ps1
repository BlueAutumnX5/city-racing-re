# READ-ONLY memory watch for game.exe (32-bit, NOT large-address-aware: the hard ceiling is
# 2048 MB of VIRTUAL address space). Waits up to 30 min for the game to start, then samples
# every 2 s until it exits. Writes memwatch_HHMMSS.csv and prints a line every 30 s plus peaks.
param([int]$WaitMinutes = 30)
$work = $PSScriptRoot
$deadline = (Get-Date).AddMinutes($WaitMinutes)
while (-not ($p = Get-Process game -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $deadline) { "game did not start within $WaitMinutes min"; exit 1 }
    Start-Sleep -Seconds 2
}
$csv = Join-Path $work ("memwatch_{0}.csv" -f (Get-Date -Format HHmmss))
"t,private_mb,working_mb,virtual_mb" | Set-Content $csv
"attached to game.exe pid $($p.Id); log -> $csv"
$t0 = Get-Date; $peakV = 0; $peakP = 0; $next = 30
while ($true) {
    $p = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
    if (-not $p) { break }
    $v = [math]::Round($p.VirtualMemorySize64 / 1MB); $pr = [math]::Round($p.PrivateMemorySize64 / 1MB)
    $w = [math]::Round($p.WorkingSet64 / 1MB); $t = [math]::Round(((Get-Date) - $t0).TotalSeconds)
    "$t,$pr,$w,$v" | Add-Content $csv
    if ($v -gt $peakV) { $peakV = $v }; if ($pr -gt $peakP) { $peakP = $pr }
    if ($v -gt 1800) { "[$t s] WARNING virtual $v MB (ceiling 2048)" }
    if ($t -ge $next) { "[$t s] virtual $v MB (peak $peakV), private $pr MB (peak $peakP)"; $next += 30 }
    Start-Sleep -Seconds 2
}
"game exited. PEAK virtual $peakV MB of 2048, PEAK private $peakP MB"
