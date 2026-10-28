# PF1800AFL CyberView acquisition inventory

Snapshot date: 2026-10-27 UTC. This report records source/provenance and parser outcomes; vendor binaries remain under ignored `.artifacts` and are not redistributed by Git.

## Original installer provenance

* Official manufacturer page: [All Models Driver Download](https://www.scanace.com/product/all-models-driver-download-user-guide), discontinued-model row **PrimeFilm 1800AFL**.
* Manufacturer link target: Google Drive file ID `1ZO2fiBFpS6v6B5OnsnYTpDq5Qqr7T-yM`, displayed source name `PrimeFilm 1800AFL_Windows_SF_ENG_1.3.exe`.
* Manufacturer page states EOL and **Windows XP/Vista/7 only (nothing newer)**.
* Downloaded 2026-10-27 23:29:07 UTC through the manufacturer link and Drive executable-warning confirmation flow. Redirect: `drive.google.com/uc?export=download&id=...` → `drive.usercontent.google.com/download?...` (303), then confirmed download (200). Drive response `application/octet-stream`, 9,898,119 bytes, `Last-Modified: Fri, 22 Jul 2022 08:45:55 GMT`.
* Original file path (ignored): `research/cyberview/.artifacts/official-pf1800afl-v1.3/PrimeFilm_1800AFL_Windows_SF_ENG_1.3.exe`.
* Size: 9,898,119 bytes. SHA-256: `EBCBE798FE577B9461DF22DB3BDE6240185E0553E65EB9B93D139D367F9109CF`.
* Outer PE resource: `Setup.exe`, InstallShield / Macrovision, FileVersion `14.0.162`, ProductVersion `14.0`, copyright 2007. Authenticode: unsigned (`NotSigned`).
* Embedded printable string: `CyberView X - SF v1.30 (build 20110526)`.

**Identity/version caveat:** the manufacturer-linked filename suffix `1.3`, embedded CyberView string `v1.30`, outer InstallShield version `14.0.162`, TWAIN component `DCVCom.dll` version `2.62`, and `CyberViewX.ds` version `1.4.0.0` are separate version records. There is no basis to call every embedded driver or component “version 1.3.” The package is officially linked from the PF1800AFL row, but contains drivers/resources for several scanner models.

## Parser source and extraction method

Static pefile 2024.8.26 inspection found the PE overlay at offset `0x5B000`, length 9,525,383 bytes. Its first bytes identify `data1.cab`, `Disk1\\data1.cab`, version text `0.0.0.0`, the decimal length `498554`, then InstallShield `ISc(` magic. The wrapper does not begin with Microsoft CAB `MSCF` or `ISSetupStream`. 7-Zip 22.01 reports “Cannot open the file as archive” on the whole EXE; this is an unsupported wrapper/container, not evidence of absent contents.

The wrapper parser was [ISx](https://github.com/lifenjoiner/ISx), source commit `3c4177ddd0519244490ff8e78d380110c8dacdc8` (MIT). Its source README claims DevStudio 9 (2003) through InstallShield 2021; its source version table maps InstallShield 2008 to version 14.

The source was inspected and built in a temporary directory with the installed Visual Studio 2022 compiler. Source file hashes: `ISx.c` `BD9FCC51BC9C4A1C1462A29D1553E276DAE39C0356D554077B2AB08442B8617F`; `inflate_tinfl.c` `2BD26446D6F033E863585330C86EA78DE4F23A56E3AB5EFFD111A49CE543F0BF`. A temporary source copy added path rejection for absolute paths, drive prefixes, `.` and `..` components; build used `cl.exe /nologo /DNO_INFLATE /O2 /FeISx-reviewed.exe ISx-reviewed.c`. The source parser wrote only into a unique temporary directory. It peeled ten wrapper files into `Disk1/` with exit code 0, then printed `Unrecognized version installer!`; the listed embedded CAB and support files were present. The warning is retained as a parser diagnostic.

The ten-file wrapper output includes `data1.cab` (498,554 bytes), `data1.hdr` (55,483), `data2.cab` (7,427,648), `ISSetup.dll`, `setup.exe`, `setup.inx`, `setup.isn`, and support files. Extracted `data1.cab` SHA-256: `4B7897BCF5BB45DE933F16C7BEEFE9A5FE97914BC422EEC5D1AD9218A4A6300D`; `data1.hdr` SHA-256: `8735A68BD3ED4572EBDD2125EB1B2677222385752986640D1F85C277B447E100`.

For the inner CAB, [Unshield](https://github.com/twogood/unshield) source commit `feaa32f6227fb306a87f4249a6618aa2ddd49966` was used. Its README describes support for InstallShield cabinets version 5 and later; license is MIT. The source build used Visual Studio 2022/MSVC and CMake against [zlib](https://github.com/madler/zlib) source commit `71747d1d39168833e0cae8ed84b8ce77cb049699` (zlib license), static build, and no OpenSSL. The project was built in a temporary folder; no vendor code was executed.

Commands/results:

```text
ISx-reviewed.exe <official-installer.exe> <unique-temp-output>
  exit 0; extracted wrapper support files; diagnostic: "Unrecognized version installer!"
unshield.exe -V
  Unshield version 1.6.2. MIT License.
unshield.exe l <Disk1/data1.cab>
  exit 0; 290 listed paths; no absolute/drive-prefixed/.. paths found
unshield.exe -d <ignored-artifact-payload-dir> x <Disk1/data1.cab>
  exit 0; 290 files, 24,474,629 bytes
```

Extracted data is preserved under ignored `research/cyberview/.artifacts/extracted-pf1800afl-v1.3/`. The complete tracked per-file inventory, with paths relative to `payload/`, byte counts, SHA-256, PE version resources, architectures, imported DLLs and imported symbols where parseable, is [payload-inventory.json](payload-inventory.json). A generated copy remains beside `Disk1/` and `payload/` in ignored artifacts. No payload file was run or installed.

## Extracted version and driver evidence

| Component | Size | Version evidence | SHA-256 |
|---|---:|---|---|
| `CyberViewX_SF/DCVCom.dll` | 925,696 | TWAIN 32 data source; `FileVersion=2.62`; PE x86 | `17EB0E7539F9B63326C5DC3726E7E714D7D854399F189E1B3018F6F2DDBBFE79` |
| `Resource_ENG/CyberViewX.ds` | 2,019,328 | CyberViewX; `FileVersion=1,4,0,0`; PE x86 | `50C9B359417CA61E555A743B8E7351DF43A22585822AA79C334140DD0EB6D64E` |
| `CyberViewX_SF/PfsLoader.exe` | 245,760 | PfsLoader; `FileVersion=1,0,1,2`; PE x86 | `14AE1CD755718626AC69FC912EA2B703343F2076A43F93F377103FA0706A0299` |
| `CyberViewX_SF/PF1800U.dll` | 143,360 | `FileVersion=1,0,2,6`; PE x86 | `6A694BF6344C90E11F961B29239F99BE82567D0DC3FCF790F213602D44414F03` |
| `GENEUSB_W2K_SYS/GENEUSB.SYS` | 10,624 | PE x86; no version resource | `38480891911EBBD55F8AD08C084DF893D2C43714D5B7E5C40943A44124D296AD` |
| `USBSCAN_W2K/USBSCAN.SYS` | 12,400 | Microsoft USB Scanner Driver `5.00.2151.1`; PE x86 | `801FE8DD420BE927C3ED795C6B8B432B880D9A52A58EA7A190A6D364E6B492B5` |
| `USBSCAN_W9X/usbscan.sys` | 8,944 | Microsoft `Logitech USB Scanner driver` `4.10.1998`; PE x86 | `1593856C798D3714BDBB7F6E05107896ED008778D47C56F9BE63A9B179FE23F3` |
| `INF_WNT/PF1800U.INF` (same hash in W9X/Vista) | 2,678 | Text names PF1800U, generic “Single Frame Film Scanner,” VID `05E3`, PID `0120` | `091B7B7308F53B26813624655A100B8091D0B3E4C849C7900EC1A8BDA2DFDA7B` |

The INF says it is for Windows Vista x86/x64 but references `usbscan.sys`; its contents name **PF1800U**, not PF1800AFL, and genericize the device description. The package came from the official PF1800AFL download row, but the exact relationship between the INF family, hardware ID and physical AFL model still requires model-specific evidence. This package contains several scanner families (including PF2700, PF3600U, PF7250U); do not attribute every component to the AFL without checking setup metadata and source code.

### AFL-specific dependency check

The complete Unshield listing contains 290 entries and no standalone payload path named `SCAN08.dll`. The package does contain a `PF1800U.dll` (version `1.0.2.6`), but its distinct name/model evidence is not grounds to treat it as a substitute. A raw bytescan found `SCAN08`/`SCAN08.dll` strings embedded in `CyberViewX_SF/BeneRaw.dll`, `BeneScan.dll`, `LC.dll`, `Resource_ENG/CyberViewX.ds`, `WXP_DLL/PF1800LC.Dll`, `WXP_DLL/PWiaScnr.dll`, and DPInst copies. The reverse-engineering agent reports that the CyberViewX model table's `CPfs1800AFL` constructor requests `SCAN08.dll`; whether an embedded component supplies it still requires code analysis. This is static package evidence, not a physical device test.

The [manufacturer all-model download page](https://www.scanace.com/product/all-models-driver-download-user-guide) exposes a Windows download for **PrimeFilm 1800AFL** and a separate row for **PrimeFilm 1800u/i & 1800 Silver**. The [manufacturer troubleshooting page](https://www.scanace.com/product/troubleshooting) directs owners of old PrimeFilm 1800-series software to the all-model page and says legacy driver development ended around Windows 7. Searches on the official ScanAce domain for `SCAN08`, `PrimeFilm 1800AFL SCAN08`, and `PF1800AFL_Windows` did not locate another AFL package or CD image. There is no standalone `SCAN08.dll` path in this official archive. The embedded string references may resolve to code in one of the listed binaries, so a separate missing runtime dependency is not established. The user's original CD or a direct vendor response remain possible sources if further analysis confirms a separate file is required. No unrelated-model DLL or third-party DLL download was substituted.

## Authorized Windows guest media status

* The current [Windows 11 Enterprise Evaluation Center](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise) offers version 26H2 x64 and Arm64 ISOs for a 90-day evaluation after registration. A Microsoft account is required; no product key is required. The page does not state ISO size before registration/download, so no multi-gigabyte file was fetched. After expiry/unactivated use, the evaluation shuts down hourly.
* A closer x86 candidate is the official Microsoft Download Center's [Windows Server 2008 Enterprise Edition x86 (Full Install) VHD](https://www.microsoft.com/en-us/download/details.aspx?id=14527). Its page calls it a preconfigured VHD and a 60-day evaluation for evaluation only, not production; page date July 15, 2024. HEAD on the three official parts returned 200 (`application/octet-stream`): [part01.exe](https://download.microsoft.com/download/9/3/6/9368f957-cff4-4f0a-b228-f43af06145b1/Windows2008Fullx86Ent.part01.exe), 734,003,200 bytes; [part02.rar](https://download.microsoft.com/download/9/3/6/9368f957-cff4-4f0a-b228-f43af06145b1/Windows2008Fullx86Ent.part02.rar), 734,003,200 bytes; [part03.rar](https://download.microsoft.com/download/9/3/6/9368f957-cff4-4f0a-b228-f43af06145b1/Windows2008Fullx86Ent.part03.rar), 484,091,051 bytes. Total: 1,952,097,451 bytes. The three parts were downloaded from those URLs and their hashes are listed below. Microsoft's [current Hyper-V guest matrix](https://learn.microsoft.com/windows-server/virtualization/hyper-v/supported-windows-guest-operating-systems-for-hyper-v-on-windows) includes Windows Server 2008 SP2 32-bit/64-bit guests. Microsoft's [Hyper-V-on-Windows requirements](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/reference/hyper-v-requirements) permit Hyper-V on Windows 11 Pro/Enterprise. The older README gives Hyper-V setup steps, while the EULA permits use on any VHD-capable virtualization software; the exact VHD has not been imported on a current host. The vendor supports PF1800AFL on XP/Vista/7 only, so Server 2008 driver testing remains experimental.

#### Downloaded evaluation archive and extracted metadata

* Retrieved from the official Microsoft Download Center links on 2026-10-27 23:43 UTC. All direct responses were HTTP 200 `application/octet-stream`; `Last-Modified` was February 17, 2025. The ignored `download-metadata.json` preserves final URLs and response headers. The archive files are in ignored `research/cyberview/.artifacts/guest-media/server2008-x86/`.
* `Windows2008Fullx86Ent.part01.exe`: 734,003,200 bytes, SHA-256 `B13F21B88389DF2EED78193FA2379B1CA6ACEC616A10008486B35466A0537700`.
* `Windows2008Fullx86Ent.part02.rar`: 734,003,200 bytes, SHA-256 `1D7F25BB2348ECBFC5C02B77CA0A1CBD12A9BDC9B5FA915C7395E30B06C73F8E`.
* `Windows2008Fullx86Ent.part03.rar`: 484,091,051 bytes, SHA-256 `7688BCA0D8B200FD2CEE5BED7403304A3A5F80B4DE65625CEB31143197AEF0B0`.
* 7-Zip listed the three volumes as one RAR archive: total physical compressed stream 1,951,993,003 bytes; listed files total 7,654,065,174 bytes. Main VHD entry: `Windows2008Fullx86Ent.vhd`, physical size 7,653,676,032 bytes, compressed size 1,951,666,168 bytes. The other seven files are README/EULA/configuration metadata totaling 389,142 bytes.
* Extracted only the seven small docs first (7-Zip exit 0), including `README.htm` and `VHD Test Drive Program WS08 EULA .xps`; they are retained under ignored `metadata/`. README SHA-256 `C0EAF5B0A9813F9C6CD8C198726D0310BF773027568886A0034CAE118CF80BB8`; XPS EULA SHA-256 `CB1F744B6ED7E3162BF23FE07CCD921FFB97D5C51B3049E06BB8117427F808D1`.
* README says the image's evaluation ends in 60 days, the image should then be discarded, **do not activate**, do not redistribute, and do not use in production. The included EULA grants use only to demonstrate and internally evaluate the software, disallows live production use and transfer, sets a 60-day term from first installation, and explicitly says activation is not licensed for any purpose. Its general scope clause also prohibits reverse engineering/decompiling/disassembling the licensed Windows software except where applicable law permits; the scanner research does not disassemble the guest OS. The EULA says it can be installed on a device running any virtualization software that supports VHD; the old README gives Hyper-V-specific setup instructions. This is an evaluation-only image and was not booted or activated.
* After checking the archive listing and free space, extracted only the VHD (7-Zip exit 0) to ignored `vhd/`. VHD SHA-256 `BC57268875AB4589F2F11B766FA214BBE11B5349B427EC518E2A6316E2DED19D`. Read-only QEMU `qemu-img info` reports format `vpc`, dynamic VHD, virtual size 136,365,211,648 bytes (~127 GiB), current file 7,653,676,032 bytes, 524,288-byte cluster size, clean/not dirty. Free C: space after extraction was 25,531,351,040 bytes; the VHD's virtual capacity exceeds that free space. No guest was started. Do not boot until a storage-safe VM plan is approved and the primary reverse engineer coordinates it.
* Microsoft's [prebuilt Windows developer VM page](https://developer.microsoft.com/en-us/windows/downloads/virtual-machines/) still says downloads are temporarily unavailable since 2024-10-23.
* The prior [Windows 10 Enterprise Evaluation Center URL](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-10-enterprise) redirects to the Windows end-of-support blog. The current Windows 10 ISO page exposes Home/Pro, not Enterprise; Enterprise is offered through Microsoft 365 admin/VLSC routes.
* [Visual Studio Subscriptions](https://learn.microsoft.com/en-us/visualstudio/subscriptions/product-availability) can include legacy downloads, depending on account/subscription/region, but exact XP/7 media availability requires checking an eligible signed-in portal. No such account was available to inspect here.
* No public Microsoft XP/Vista/7 evaluation or legacy VM image was found. Any user-owned or OEM recovery media still has to be used under its specific Windows license; a secondhand key alone does not establish VM rights.

The CyberView UI/TWAIN PE files found here are x86 and may be suitable for application-only inspection under WOW64 on x64 Windows. The package's driver files are x86 and the manufacturer says XP/Vista/7 only, so Windows 11 evaluation is not evidence of driver or scanner compatibility. Linux/Wine cannot load these Windows `.sys` drivers; no useful TWAIN/USB hardware path has been established there. No guest experiment has been run.
