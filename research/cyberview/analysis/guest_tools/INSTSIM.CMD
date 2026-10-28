@echo off
rem FRAME M1.5: place the SIMULATED model-37 module where BeneScan looks for SCAN08.dll.
rem Research guest only. The file is FRAME's simulator, not Pacific Image software.
setlocal
set OUT=C:\FRAME
set DEST=%WINDIR%\twain_32\CyberViewX_SF
if not exist %OUT% mkdir %OUT%
if not exist "%DEST%\BeneScan.dll" goto missing
copy /y D:\SCAN08.DLL "%DEST%\SCAN08.dll"
type nul > %OUT%\SIMAFL.LOG
dir "%DEST%\SCAN08.dll" > %OUT%\SIMINST.TXT 2>&1
echo simulator-installed %DATE% %TIME% >> %OUT%\SIMINST.TXT
echo Simulated SCAN08.dll installed. Run BASELINE.CMD next.
goto end
:missing
echo CyberView is not installed under %DEST%; nothing copied.
:end
endlocal
