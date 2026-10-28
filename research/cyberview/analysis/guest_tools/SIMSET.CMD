@echo off
rem FRAME M1.5 simulator run only: write one [Simulator] setting, e.g. SIMSET.CMD FilmLoaded 0.
rem The simulated SCAN08.dll re-reads C:\FRAME\SIMAFL.INI on every call.
if "%~2"=="" goto usage
if not exist C:\FRAME mkdir C:\FRAME
rem Redirection first: "echo key=0>>file" would treat "0>>" as a handle redirect.
> C:\FRAME\SIMAFL.INI echo [Simulator]
>> C:\FRAME\SIMAFL.INI echo %~1=%~2
>> C:\FRAME\SIMSET.TXT type C:\FRAME\SIMAFL.INI
echo simset %~1=%~2 %DATE% %TIME% >> C:\FRAME\SIMSET.TXT
goto end
:usage
echo usage: SIMSET.CMD key value
:end
