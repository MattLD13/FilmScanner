# Build cvbridge.exe (x86) next to this script, in the ignored bin folder.
# -Tests also builds the CPU-only USB watch harness used by tests/scanner/test_usbwatch.py.
param([switch]$Tests)
$ErrorActionPreference = "Stop"
$source = $PSScriptRoot
$out = Join-Path $source "bin"
New-Item -ItemType Directory -Force $out | Out-Null
$vcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path $vcvars)) { throw "Visual Studio 2022 Build Tools (x86 C compiler) not found" }
$commands = "`"$vcvars`" x86 >nul && cd /d `"$out`" && " +
            "cl /nologo /W3 /O2 /MT /D_CRT_SECURE_NO_WARNINGS `"$source\cvbridge.c`" " +
            "/link /OUT:cvbridge.exe user32.lib kernel32.lib shell32.lib"
# vcvarsall prints a harmless vswhere notice on stderr; judge success by exit code only.
$ErrorActionPreference = "Continue"
cmd /c "$commands 2>&1"
if ($LASTEXITCODE -ne 0) { throw "build failed" }
# CyberView's own automatic colour, called outside a scan (docs/auto-color-re.md).
cmd /c "`"$vcvars`" x86 >nul && cd /d `"$out`" && cl /nologo /W3 /O2 /MT /D_CRT_SECURE_NO_WARNINGS `"$source\autocolor.c`" /link /OUT:autocolor.exe kernel32.lib shell32.lib 2>&1"
if ($LASTEXITCODE -ne 0) { throw "autocolor build failed" }
if ($Tests) {
    $harness = [IO.Path]::GetFullPath((Join-Path $source "..\..\tests\scanner\usbwatch_harness.c"))
    cmd /c "`"$vcvars`" x86 >nul && cd /d `"$out`" && cl /nologo /W3 /O2 /MT /D_CRT_SECURE_NO_WARNINGS `"$harness`" /link /OUT:usbwatch-harness.exe kernel32.lib 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "harness build failed" }
}
$ErrorActionPreference = "Stop"
Get-FileHash (Join-Path $out "cvbridge.exe") -Algorithm SHA256 | Format-List Hash, Path
