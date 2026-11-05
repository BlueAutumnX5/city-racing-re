# Wait for game.exe, let it settle, then report which GPU adapter its 3D engine runs on (read-only).
# LUIDs from DXGI on 2026-09-26: 0x13ad0 = Intel UHD, 0x13f3c = RTX 3050 (they can change after a reboot).
param([int]$WaitMinutes = 60, [int]$SettleSeconds = 20)
$names = @{ "0x00013ad0" = "Intel UHD Graphics (iGPU)"; "0x00013f3c" = "NVIDIA RTX 3050 (dGPU)" }
$deadline = (Get-Date).AddMinutes($WaitMinutes)
if ($old = Get-Process game -ErrorAction SilentlyContinue) {
    "a game session is running now (pid $($old.Id)); waiting for it to close, then for the NEXT start"
    while (Get-Process -Id $old.Id -ErrorAction SilentlyContinue) {
        if ((Get-Date) -gt $deadline) { "gave up: the running session never closed"; exit 1 }
        Start-Sleep -Seconds 2
    }
}
while (-not ($p = Get-Process game -ErrorAction SilentlyContinue)) {
    if ((Get-Date) -gt $deadline) { "gave up: game not started within $WaitMinutes minutes"; exit 1 }
    Start-Sleep -Seconds 2
}
"game.exe started (pid $($p.Id)) at $(Get-Date -Format HH:mm:ss); settling $SettleSeconds s"
Start-Sleep -Seconds $SettleSeconds
for ($round = 1; $round -le 3; $round++) {
    $s = (Get-Counter "\GPU Engine(pid_$($p.Id)_*engtype_3D)\Utilization Percentage" -SampleInterval 2 -MaxSamples 1 -ErrorAction SilentlyContinue).CounterSamples
    $by = @{}
    foreach ($x in $s) {
        if ($x.InstanceName -match "luid_0x[0-9a-f]+_(0x[0-9a-f]+)_") { $l = $Matches[1]; $by[$l] = [math]::Max(($by[$l] | ForEach-Object { $_ }), $x.CookedValue) }
    }
    $line = ($by.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object {
        $n = $names[$_.Key]; if (-not $n) { $n = "unknown adapter $($_.Key)" }; "{0}: {1:N0}% 3D" -f $n, $_.Value }) -join " | "
    "sample $round : $line"
    Start-Sleep -Seconds 3
}
