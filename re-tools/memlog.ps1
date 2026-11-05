# Read-only memory logger for game.exe (32-bit, NOT large-address-aware -> 2 GB limit).
# Waits up to $Hours for the game, logs EVERY session separately (memlog_s1.csv, s2, ...)
# until $MaxSessions sessions are done or the window closes. Each CSV row also records
# which extras were on at that moment, so "before view" and "after view" separate cleanly.
param([double]$Hours = 12, [int]$MaxSessions = 4)
$state = Join-Path (Split-Path -Parent $PSScriptRoot) "racemod_state.json"
$deadline = (Get-Date).AddHours($Hours)
for ($s = 1; $s -le $MaxSessions; $s++) {
    $p = $null
    while (-not $p -and (Get-Date) -lt $deadline) {
        $p = Get-Process -Name game -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $p) { Start-Sleep -Seconds 5 }
    }
    if (-not $p) { "no more sessions before the window closed"; break }
    $extras = try { ((Get-Content $state -Raw | ConvertFrom-Json).extras) -join "+" } catch { "?" }
    $out = Join-Path $PSScriptRoot "memlog_s$s.csv"
    "time,private_MB,working_MB,paged_MB,threads,handles,extras" | Set-Content $out
    "session $s started $(Get-Date -Format HH:mm:ss) pid $($p.Id) extras=$extras"
    $peak = 0
    while (-not $p.HasExited) {
        $p.Refresh()
        $priv = [math]::Round($p.PrivateMemorySize64 / 1MB, 1)
        if ($priv -gt $peak) { $peak = $priv }
        "{0},{1},{2},{3},{4},{5},{6}" -f (Get-Date -Format HH:mm:ss), $priv,
            [math]::Round($p.WorkingSet64 / 1MB, 1), [math]::Round($p.PagedMemorySize64 / 1MB, 1),
            $p.Threads.Count, $p.HandleCount, $extras | Add-Content $out
        Start-Sleep -Seconds 5
    }
    $rows = @(Import-Csv $out)
    $med = if ($rows.Count) { ($rows | ForEach-Object { [double]$_.private_MB } | Sort-Object)[[int]($rows.Count / 2)] } else { 0 }
    "session $s ended $(Get-Date -Format HH:mm:ss): $($rows.Count) samples, peak private $peak MB, median $med MB"
}
