# buzztest.ps1 - the rotary buzzer on the real 32-bit DirectSound (buzztest.cs). Plays audibly (~1.2 s).
# Run: C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File buzztest.ps1
param([string]$Dll = (Join-Path (Split-Path -Parent $PSScriptRoot) "rust\crdrive\target\i686-pc-windows-msvc\release\crdrive.dll"))
if ([IntPtr]::Size -ne 4) { throw "run me with C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe" }
Add-Type -Path (Join-Path $PSScriptRoot "buzztest.cs")
$out = [BuzzTest]::Run($Dll)
Set-Content -Path (Join-Path $PSScriptRoot "buzztest_last.txt") -Value $out
