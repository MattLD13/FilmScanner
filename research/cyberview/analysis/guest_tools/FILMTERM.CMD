@echo off
rem FRAME M1.5 simulator run only: model 37 reads film terms from GAMMA\*.ft, which the
rem official package leaves empty. Copy the package's own unused GAMMA\Original set there.
rem This is a test configuration change, not evidence of what the AFL installer provides.
setlocal
set OUT=C:\FRAME
set G=%WINDIR%\twain_32\CyberViewX_SF\GAMMA
if not exist %OUT% mkdir %OUT%
if not exist "%G%\Original\Generic Negative.ft" goto missing
copy /y "%G%\Original\*.ft" "%G%\" > %OUT%\FILMTERM.TXT 2>&1
dir /b "%G%\*.ft" >> %OUT%\FILMTERM.TXT 2>&1
echo filmterm-copied %DATE% %TIME% >> %OUT%\FILMTERM.TXT
echo Film terms copied to %G%
goto end
:missing
echo No GAMMA\Original film terms found; nothing copied.
:end
endlocal
