@echo off
rem Builds crdrive.dll (the Rust drivetrain DLL, 32-bit like game.exe) and refreshes bin\crdrive.dll.
rem Needs Rust (https://rustup.rs). No Visual Studio needed: the DLL links against nothing, so rust-lld does it.
setlocal
cd /d "%~dp0rust\crdrive"
where cargo >nul 2>&1 || (
    echo Rust is not installed. Get it from https://rustup.rs ^(or: winget install Rustlang.Rustup^), then run this again.
    echo Until then the tools use the prebuilt bin\crdrive.dll.
    pause
    exit /b 1
)
rustup target add i686-pc-windows-msvc
cargo test || (echo TESTS FAILED & pause & exit /b 1)
cargo build --release --target i686-pc-windows-msvc || (echo BUILD FAILED & pause & exit /b 1)
copy /y "target\i686-pc-windows-msvc\release\crdrive.dll" "%~dp0bin\crdrive.dll" >nul
echo.
echo crdrive.dll built and copied to bin\. Apply in the control panel installs it next to game.exe.
pause
