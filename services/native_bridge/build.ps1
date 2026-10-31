param([switch]$Fixtures)
$ErrorActionPreference = "Stop"
$source = $PSScriptRoot
$out = Join-Path $source "bin"
New-Item -ItemType Directory -Force $out | Out-Null
$vcvars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if (-not (Test-Path -LiteralPath $vcvars)) { throw "Visual Studio 2022 Build Tools (x86 C compiler) not found" }
function Build-Native([string]$Arguments) {
    $commands = "`"$vcvars`" x86 >nul && cd /d `"$out`" && cl /nologo /W4 /O2 /MT /D_CRT_SECURE_NO_WARNINGS $Arguments"
    $ErrorActionPreference = "Continue"
    cmd /c "$commands 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "native bridge build failed" }
}
Build-Native "`"$source\aflbridge.c`" /link /OUT:aflbridge.exe bcrypt.lib kernel32.lib"
if ($Fixtures) {
    Build-Native "/DFRAME_NATIVE_TEST `"$source\aflbridge.c`" /link /OUT:aflbridge-fixture.exe bcrypt.lib kernel32.lib"
    $fixture = [IO.Path]::GetFullPath((Join-Path $source "..\..\tests\native\fake_model.c"))
    $definition = [IO.Path]::ChangeExtension($fixture, ".def")
    $fvc = [IO.Path]::GetFullPath((Join-Path $source "..\..\tests\native\fake_fvc.c"))
    $fvcDefinition = [IO.Path]::ChangeExtension($fvc, ".def")
    Build-Native "/LD `"$fvc`" /link /OUT:fake-fvc.dll /IMPLIB:fake-fvc.lib /DEF:`"$fvcDefinition`" kernel32.lib"
    Build-Native "/LD `"$fixture`" /link /OUT:fake-model.dll /DEF:`"$definition`" kernel32.lib fake-fvc.lib"
}
Get-FileHash (Join-Path $out "aflbridge.exe") -Algorithm SHA256 | Format-List Hash, Path
