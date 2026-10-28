@echo off
rem FRAME M1.5: end only the CyberView loader process so the simulator DLL can be replaced.
taskkill /im PfsLoader.exe /f > C:\FRAME\ENDCV.TXT 2>&1
echo endcv %DATE% %TIME% >> C:\FRAME\ENDCV.TXT
