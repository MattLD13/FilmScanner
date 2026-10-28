@echo off
rem FRAME M1.5 CyberView no-device baseline, part 2 of 2. Stops the trace and copies
rem small text results to the evidence floppy A:\ in priority order.
setlocal
set OUT=C:\FRAME
echo collect %DATE% %TIME% >> %OUT%\RUN.TXT
tasklist /v > %OUT%\TASKS.TXT 2>&1
tasklist /m > %OUT%\MODULES.TXT 2>&1
wevtutil qe Application /q:"*[System[(EventID=1000 or EventID=1001)]]" /f:text /c:6 /rd:true > %OUT%\CRASH.TXT 2>&1
logman stop "NT Kernel Logger" -ets >> %OUT%\RUN.TXT 2>&1
tracerpt %OUT%\KERNEL.ETL -o %OUT%\KERNEL.CSV -of CSV -summary %OUT%\SUMMARY.TXT -y >> %OUT%\RUN.TXT 2>&1
findstr /i "scan08" %OUT%\KERNEL.CSV > %OUT%\SCAN08.TXT
findstr /i "lc.dll pf1800 pf2700 benescan beneraw rawscan pf7250u ps7200 ss3600ice sq_scan io_port fvc.dll usbscan geneusb daspi32u" %OUT%\KERNEL.CSV > %OUT%\MODELS.TXT
findstr /i "pfsloader cyberviewx dcvcom twain_32 twain.dll" %OUT%\KERNEL.CSV > %OUT%\APP.TXT
findstr /n "^" %OUT%\KERNEL.CSV | findstr /r /b "[1-9]: [1-9][0-9]: [1-9][0-9][0-9]:" > %OUT%\HEAD.TXT
for %%f in ("%OUT%\KERNEL.ETL" "%OUT%\KERNEL.CSV") do echo %%~nxf %%~zf bytes >> %OUT%\RUN.TXT
for /f "delims=" %%i in ('dir /s /b "%WINDIR%\twain_32\CyberViewX.ini" 2^>nul') do copy /y "%%i" %OUT%\CVX.INI > nul
for /f "delims=" %%i in ('dir /s /b "%WINDIR%\twain_32\*.log" 2^>nul') do echo %%i >> %OUT%\LOGS.TXT
dir "%USERPROFILE%\Pictures" > %OUT%\PICS.TXT 2>&1
echo collect-end %DATE% %TIME% >> %OUT%\RUN.TXT
if exist %OUT%\SIMAFL.LOG copy /y %OUT%\SIMAFL.LOG A:\ > nul
rem Scanned images are small at low DPI; copy them before the bulky trace extracts.
for %%i in ("%USERPROFILE%\Pictures\image*.tif") do copy /y "%%i" A:\ > nul
for %%f in (RUN PICS CRASH ENDCV SIMINST SIMSET FILMTERM SCAN08 MODELS SUMMARY TASKS MODULES TWAIN SYS32 STARTMNU UNINST LOGS) do if exist %OUT%\%%f.TXT copy /y %OUT%\%%f.TXT A:\ > nul || echo copy-failed %%f >> %OUT%\RUN.TXT
if exist %OUT%\CVX.INI copy /y %OUT%\CVX.INI A:\ > nul
copy /y %OUT%\RUN.TXT A:\ > nul
dir A:\
echo Done. Evidence copied to A:\
endlocal
