# Build the simulated SCAN08.dll (x86) into ignored research artifacts.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot | Split-Path -Parent | Split-Path -Parent
$source = $PSScriptRoot
$out = Join-Path $root "research\cyberview\.artifacts\afl-sim"
New-Item -ItemType Directory -Force $out | Out-Null
$vcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
$commands = "`"$vcvars`" x86 >nul && cd /d `"$out`" && rc /nologo /fo scan08_sim.res `"$source\scan08_sim.rc`" && " +
            "cl /nologo /W3 /O2 /MT /LD /D_CRT_SECURE_NO_WARNINGS `"$source\scan08_sim.c`" scan08_sim.res " +
            "/link /DEF:`"$source\scan08_sim.def`" /OUT:SCAN08.dll user32.lib kernel32.lib"
# vcvarsall prints a harmless vswhere notice on stderr; judge success by exit code only.
$ErrorActionPreference = "Continue"
cmd /c "$commands 2>&1"
if ($LASTEXITCODE -ne 0) { throw "build failed" }
$ErrorActionPreference = "Stop"
Get-FileHash (Join-Path $out "SCAN08.dll") -Algorithm SHA256 | Format-List Hash, Path
