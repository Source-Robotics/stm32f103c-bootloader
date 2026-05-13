@echo off
REM End-to-end CAN soak test via slcan adapter: 20 consecutive flash cycles.

set ITERATIONS=20
set FW=..\..\..\<your-app-repo>\.pio\build\genericSTM32F103CB\firmware.bin
set LOG=soak_can_slcan.log
set CHANNEL=COM6

echo Starting CAN (slcan) soak test: %ITERATIONS% iterations on %CHANNEL% > %LOG%
echo Start: %date% %time% >> %LOG%

set PASS=0
set FAIL=0

for /L %%i in (1,1,%ITERATIONS%) do (
    echo.
    echo === Iteration %%i / %ITERATIONS% ===
    echo === Iteration %%i / %ITERATIONS% === >> %LOG%
    py bl_flash.py --transport can --can-interface slcan --channel %CHANNEL% flash "%FW%" --board 0 --app-node 3 --erase-first >> %LOG% 2>&1
    if errorlevel 1 (
        echo Iteration %%i: FAIL
        echo Iteration %%i: FAIL >> %LOG%
        set /a FAIL=FAIL+1
    ) else (
        echo Iteration %%i: PASS
        echo Iteration %%i: PASS >> %LOG%
        set /a PASS=PASS+1
    )
    C:\Windows\System32\timeout.exe /t 5 /nobreak > nul
)

echo.
echo End:   %date% %time% >> %LOG%
echo. >> %LOG%
echo Total: %PASS% PASS, %FAIL% FAIL out of %ITERATIONS% >> %LOG%
echo.
echo Soak complete. See %LOG%
echo Total: %PASS% PASS, %FAIL% FAIL out of %ITERATIONS%
