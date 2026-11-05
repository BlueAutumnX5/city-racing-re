# dmtest.ps1 - DirectMusic engine-loop gap test (2026-09-26). Replays game.exe's engine sound calls against the
# real 32-bit DirectMusic and records the output (WASAPI loopback). Cases: "file,pitch,seconds,mode" joined by ";"
# (mode 0 = stock DirectMusic path, 1 = the engineloop fix: a looping DirectSound buffer). Plays audibly.
# Run: C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File dmtest.ps1
param([string]$Cases = "E01.wav,1.0,4;E01.wav,1.5,4;E01.wav,1.75,4", [string]$Audio = (Join-Path (Split-Path -Parent $PSScriptRoot) "extracted\SD\files\Data\Audio"))
# Must run in 32-bit Windows PowerShell: DirectMusic ships only in SysWOW64 on Windows 11.
if ([IntPtr]::Size -ne 4) { throw "run me with C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" }
Add-Type -Path (Join-Path $PSScriptRoot "dmtest.cs")
$out = [DmTest]::Run($Audio, $Cases)
Set-Content -Path (Join-Path $PSScriptRoot "dmtest_last.txt") -Value $out
