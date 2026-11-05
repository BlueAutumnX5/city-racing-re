# perflog.ps1 - READ-ONLY performance logger for game.exe (2026-11-01: the player sees drops to ~10 FPS).
# Every second: the game's own FPS (float 0x005b28c4, what the debug overlay prints), vehicles (0x02649490 /
# 0x02649494), humans (0x0255d2f0 / 0x0255d2f4), lights (0x02647d8c), process CPU (% of all cores), the busiest
# thread (% of ONE core: ~100 = that thread is the limit), GPU 3D load per adapter. Writes perflog.csv next to
# this script (or -CsvPath); stops when the game exits or after -Minutes. Opens the game with PROCESS_VM_READ only.
# paused = the frame clock dt (0x012d04a8) is exactly 0 (the FPS float then FREEZES at its last value - a paused
# game looks like a drop); front = the game's window is the foreground window.
param([int]$Minutes = 30, [string]$Rtx = "0x00013e3a", [string]$Intel = "0x000139fa", [string]$CsvPath = "")
[System.Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class Rd {
  [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(int a, bool i, int pid);
  [DllImport("kernel32.dll")] public static extern bool ReadProcessMemory(IntPtr h, IntPtr a, byte[] b, int n, out IntPtr r);
  public static byte[] Get(IntPtr h, long a, int n) { var b = new byte[n]; IntPtr r; ReadProcessMemory(h, (IntPtr)a, b, n, out r); return b; }
  [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern int GetWindowThreadProcessId(IntPtr w, out int pid);
  public static bool Front(int pid) { int p; GetWindowThreadProcessId(GetForegroundWindow(), out p); return p == pid; }
}
"@
$p = Get-Process game -ErrorAction Stop
$h = [Rd]::OpenProcess(0x0010, $false, $p.Id)
# adapter LUIDs can change after a reboot / driver reset: the NVIDIA one is the only one with an "ofa" engine
$eng = (Get-Counter "\GPU Engine(pid_$($p.Id)_*)\Utilization Percentage" -ErrorAction SilentlyContinue).CounterSamples |
  ForEach-Object { if ($_.InstanceName -match 'luid_0x[0-9a-f]+_(0x[0-9a-f]+)_.*engtype_(\w+)') { [pscustomobject]@{ L = $matches[1]; E = $matches[2] } } }
$nv = ($eng | Where-Object E -like 'ofa*' | Select-Object -First 1).L
$ig = ($eng | Where-Object { $_.L -ne $nv } | Select-Object -First 1).L
if ($nv) { $Rtx = $nv }; if ($ig) { $Intel = $ig }
$cores = [Environment]::ProcessorCount
$out = if ($CsvPath) { $CsvPath } else { Join-Path $PSScriptRoot "perflog.csv" }
"time,fps,vehicles,vehicles2,humans,humans2,lights,cpu_pct,top_thread_pct,top_thread_id,gpu_rtx,gpu_intel,paused,front" | Set-Content $out
$prevT = @{}; $prevCpu = $p.TotalProcessorTime.TotalMilliseconds; $prevWall = [DateTime]::Now
$end = [DateTime]::Now.AddMinutes($Minutes)
while ([DateTime]::Now -lt $end) {
  $c = Get-Counter "\GPU Engine(pid_$($p.Id)_*engtype_3d)\Utilization Percentage" -ErrorAction SilentlyContinue
  $p.Refresh()
  if ($p.HasExited) { break }
  $now = [DateTime]::Now; $wall = ($now - $prevWall).TotalMilliseconds; $prevWall = $now
  $cpu = $p.TotalProcessorTime.TotalMilliseconds
  $cpuPct = [math]::Round(100 * ($cpu - $prevCpu) / ($wall * $cores), 1); $prevCpu = $cpu
  $top = 0; $topId = 0
  foreach ($t in $p.Threads) {
    try { $ms = $t.TotalProcessorTime.TotalMilliseconds } catch { continue }
    if ($prevT.ContainsKey($t.Id)) { $d = 100 * ($ms - $prevT[$t.Id]) / $wall; if ($d -gt $top) { $top = $d; $topId = $t.Id } }
    $prevT[$t.Id] = $ms
  }
  # NOT $rtx: PowerShell names ignore case, so that IS the [string]$Rtx parameter (2026-11-01 bug: the GPU
  # columns were text glued together and the Intel column always 0)
  $gpuR = 0.0; $gpuI = 0.0
  foreach ($s in $c.CounterSamples) {
    if ($s.InstanceName -like "*$Rtx*") { $gpuR += $s.CookedValue } elseif ($s.InstanceName -like "*$Intel*") { $gpuI += $s.CookedValue }
  }
  $fps = [BitConverter]::ToSingle([Rd]::Get($h, 0x005B28C4, 4), 0)
  $v = [Rd]::Get($h, 0x02649490, 8); $hu = [Rd]::Get($h, 0x0255D2F0, 8); $l = [Rd]::Get($h, 0x02647D8C, 4)
  $paused = [int]([BitConverter]::ToSingle([Rd]::Get($h, 0x012D04A8, 4), 0) -eq 0)
  "{0},{1:N0},{2},{3},{4},{5},{6},{7},{8:N0},{9},{10:N0},{11:N0},{12},{13}" -f $now.ToString("HH:mm:ss"), $fps,
    [BitConverter]::ToInt32($v, 0), [BitConverter]::ToInt32($v, 4), [BitConverter]::ToInt32($hu, 0),
    [BitConverter]::ToInt32($hu, 4), [BitConverter]::ToInt32($l, 0), $cpuPct, $top, $topId, $gpuR, $gpuI,
    $paused, [int][Rd]::Front($p.Id) | Add-Content $out
}
"stopped $([DateTime]::Now.ToString('HH:mm:ss'))" | Add-Content $out
