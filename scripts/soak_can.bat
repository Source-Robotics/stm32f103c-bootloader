@echo off
REM End-to-end CAN soak test: 20 consecutive flash cycles.
REM Each cycle: app-reset (auto via flash cmd) -> erase -> flash 89 pages -> verify -> let app boot.

set ITERATIONS=20
set FW=..\..\..\<your-app-repo>\.pio\build\genericSTM32F103CB\firmware.bin
set LOG=soak_can.log

echo Starting CAN soak test: %ITERATIONS% iterations > %LOG%
echo Start: %date% %time% >> %LOG%

set PASS=0
set FAIL=0

for /L %%i in (1,1,%ITERATIONS%) do (
    echo.
    echo === Iteration %%i / %ITERATIONS% ===
    echo === Iteration %%i / %ITERATIONS% === >> %LOG%
    py bl_flash.py --transport can --can-interface gs_usb --channel 0 flash "%FW%" --board 0 --app-node 3 --erase-first >> %LOG% 2>&1
    if errorlevel 1 (
        echo Iteration %%i: FAIL
        echo Iteration %%i: FAIL >> %LOG%
        set /a FAIL=FAIL+1
    ) else (
        echo Iteration %%i: PASS
        echo Iteration %%i: PASS >> %LOG%
        set /a PASS=PASS+1
    )
    REM Give the host application time to actually boot before the next iteration.
    timeout /t 5 /nobreak > nul
)

echo.
echo End:   %date% %time% >> %LOG%
echo. >> %LOG%
echo Total: %PASS% PASS, %FAIL% FAIL out of %ITERATIONS% >> %LOG%
echo.
echo Soak complete. See %LOG%
echo Total: %PASS% PASS, %FAIL% FAIL out of %ITERATIONS%
