@echo off
rem FRAME M1.5 CyberView no-device baseline, part 1 of 2. Built-in Windows tools only.
rem Records the installed layout, starts a bounded kernel image/file trace, launches PfsLoader.
setlocal
set OUT=C:\FRAME
if not exist %OUT% mkdir %OUT%
echo baseline-start %DATE% %TIME% > %OUT%\RUN.TXT
ver >> %OUT%\RUN.TXT
whoami >> %OUT%\RUN.TXT 2>&1
dir /s /b "%WINDIR%\twain_32" > %OUT%\TWAIN.TXT 2>&1
dir /s /b "%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu" > %OUT%\STARTMNU.TXT 2>&1
dir "%WINDIR%\system32\SCAN08.dll" "%WINDIR%\system32\SQ_SCAN.DLL" "%WINDIR%\system32\IO_PORT.DLL" "%WINDIR%\system32\FVC.DLL" "%WINDIR%\system32\daspi32u.dll" "%WINDIR%\system32\drivers\usbscan.sys" > %OUT%\SYS32.TXT 2>&1
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "CyberView" > %OUT%\UNINST.TXT 2>&1
set APP=
for /f "delims=" %%i in ('dir /s /b "%WINDIR%\twain_32\PfsLoader.exe" 2^>nul') do set APP=%%i
echo app=%APP% >> %OUT%\RUN.TXT
if "%APP%"=="" goto missing
for %%d in ("%APP%") do set APPDIR=%%~dpd
logman stop "NT Kernel Logger" -ets > nul 2>&1
logman start "NT Kernel Logger" -p "Windows Kernel Trace" (process,img,fileio) -o %OUT%\KERNEL.ETL -max 64 -ets >> %OUT%\RUN.TXT 2>&1
echo launch %DATE% %TIME% >> %OUT%\RUN.TXT
start "" /D "%APPDIR%" "%APP%"
echo Launched %APP%. Observe it, then run COLLECT.CMD from this CD.
goto end
:missing
echo PfsLoader.exe not found under %WINDIR%\twain_32 >> %OUT%\RUN.TXT
echo PfsLoader.exe not found; nothing launched.
:end
endlocal
