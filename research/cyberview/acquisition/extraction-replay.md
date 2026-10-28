# Reproduce the InstallShield 14 static extraction

This recipe uses pinned MIT/zlib-licensed source parsers and never executes the vendor installer or extracted payloads. Keep output in a fresh directory under `research/cyberview/.artifacts/`, which is Git-ignored. Preserve the source repositories' `LICENSE` files and notices when using or redistributing their source/builds. No vendor binary belongs in Git.

## 1. Fetch source at the reviewed commits

From PowerShell in the repository root. Resolve the workspace root first so patch and artifact paths do not accidentally resolve inside the temporary parser checkout:

```powershell
$repo = (Resolve-Path '.').Path
$artifactRoot = Join-Path $repo 'research/cyberview/.artifacts'
$work = Join-Path $env:TEMP 'frame-isx-source'
git clone https://github.com/lifenjoiner/ISx.git $work
git -C $work checkout --detach 3c4177ddd0519244490ff8e78d380110c8dacdc8
$patch = Join-Path $repo 'research/cyberview/acquisition/isx-safe-path-guard.patch'
git -C $work apply --check $patch
if ($LASTEXITCODE -ne 0) { throw 'ISx safety patch does not apply cleanly' }
git -C $work apply $patch
if ($LASTEXITCODE -ne 0) { throw 'ISx safety patch failed to apply' }
```

ISx upstream source commit `3c4177ddd0519244490ff8e78d380110c8dacdc8` has an MIT license. The guard patch rejects absolute paths, drive prefixes, and `.`/`..` components before ISx concatenates the archive entry name to its destination. It changes only the temporary source checkout. The source file hashes before patching were recorded in [inventory.md](inventory.md).

## 2. Build and run ISx against the wrapper

Use the installed Visual Studio 2022 Build Tools compiler; this command assumes the standard Build Tools path:

```powershell
$vsdev = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat'
cmd.exe /d /c "`"$vsdev`" -arch=x64 && cd /d `"$work`" && cl.exe /nologo /DNO_INFLATE /O2 /FeISx-reviewed.exe ISx.c"
```

`/DNO_INFLATE` omits ISx's optional inflate helper; the wrapper CAB streams and required support files were recovered without it. Run ISx only on the acquired installer and direct its writes to a new, empty `.artifacts` destination:

```powershell
$dest = Join-Path $artifactRoot 'extracted-pf1800afl-v1.3'
if (Test-Path -LiteralPath $dest) { throw 'Use a fresh artifact output path' }
New-Item -ItemType Directory -Path $dest
& (Join-Path $work 'ISx-reviewed.exe') `
  (Join-Path $artifactRoot 'official-pf1800afl-v1.3/PrimeFilm_1800AFL_Windows_SF_ENG_1.3.exe') `
  $dest
```

Expected wrapper output includes `Disk1/data1.cab`, `data1.hdr`, `data2.cab`, and InstallShield support binaries. ISx may emit `Unrecognized version installer!` after extracting these files; treat it as a diagnostic and confirm the expected streams exist and have the recorded hashes before continuing. Never launch the emitted `setup.exe` or `_sfx.exe`.

## 3. Build Unshield from pinned source and extract the inner CAB

Unshield source commit `feaa32f6227fb306a87f4249a6618aa2ddd49966` is MIT-licensed. It reads the InstallShield CAB/header that ISx peeled from the wrapper; it does not parse the setup EXE itself. Its CMake build uses zlib. The extraction was made with zlib source commit `71747d1d39168833e0cae8ed84b8ce77cb049699` and the zlib license.

```powershell
$cmake = 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$zsrc = Join-Path $env:TEMP 'frame-zlib-source'
$zbld = Join-Path $env:TEMP 'frame-zlib-build'
$usrc = Join-Path $env:TEMP 'frame-unshield-source'
$ubld = Join-Path $env:TEMP 'frame-unshield-build'
git clone https://github.com/madler/zlib.git $zsrc
git -C $zsrc checkout --detach 71747d1d39168833e0cae8ed84b8ce77cb049699
git clone https://github.com/twogood/unshield.git $usrc
git -C $usrc checkout --detach feaa32f6227fb306a87f4249a6618aa2ddd49966
& $cmake -S $zsrc -B $zbld -A x64 -DZLIB_BUILD_TESTING=OFF
& $cmake --build $zbld --config Release --target zlibstatic --parallel 4
$zlib = Join-Path $zbld 'Release/libzs.lib'
& $cmake -S $usrc -B $ubld -A x64 -DBUILD_STATIC=ON -DUSE_OUR_OWN_MD5=ON `
  "-DZLIB_INCLUDE_DIR=$zsrc" "-DZLIB_LIBRARY=$zlib" -DBUILD_TESTING=OFF
& $cmake --build $ubld --config Release --target unshield --parallel 4
```

Before extraction, list the cabinet and inspect every returned path for absolute paths, drive prefixes, or `..` components. For this package, the list had 290 safe relative paths. Then extract into a new empty payload directory under the artifact root:

```powershell
$payload = Join-Path $dest 'payload'
New-Item -ItemType Directory -Path $payload
$unshield = Join-Path $ubld 'src/Release/unshield.exe'
& $unshield l (Join-Path $dest 'Disk1/data1.cab')
& $unshield -d $payload x (Join-Path $dest 'Disk1/data1.cab')
```

Expected result for this installer: Unshield 1.6.2; 290 files, 24,474,629 bytes, exit code 0. Generate SHA-256 and static PE version/import inventories for the resulting tree. Do not execute, register, install, or load any extracted executable, DLL, SYS, INF, or script.

## Current source and output records

* Pinned parser commits, package source and extracted output hashes are in [inventory.md](inventory.md).
* The complete relative-path inventory is [payload-inventory.json](payload-inventory.json).
* Original installer, extracted CABs, and extracted payload remain in ignored `.artifacts/`.
