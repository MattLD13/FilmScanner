# SCAN08.dll dependency investigation

Research pass: 2026-10-27/28 UTC. Work package A of the M1.5 completion
directive. **Conclusion: still unresolved.** The file is not located. Nothing found
shows it is supplied dynamically. Runtime has not confirmed it is missing. The
static picture is now much sharper than in the earlier pass. No vendor code was
executed, and no DLL was renamed, substituted or fabricated.

Reproduce: `research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/scan08_survey.py <payload> research/cyberview/acquisition/payload-inventory.json <out.json>`.
The script checks six payload hashes against the inventory before it reads anything. The tracked
[scan08-evidence.json](analysis/scan08-evidence.json) is its actual output.
`tests/research/test_scan08_evidence.py` locks the conclusions below. Tools: Python
3.13, pefile 2024.8.26, capstone 5.0.9. The earlier Ghidra 12.1.4 decompiles stay in
ignored `.artifacts/`.

## What was examined

* All 290 inventoried payload paths: the per-file names, the PE version resources
  already in the inventory, the PE export-directory names, and all 22 INF files.
* BeneScan.dll's full model table. The loop bound in `0x1000c1c0` gives **19**
  records of 0x44 bytes at `0x100450d0`. The earlier report showed only part of it.
* CyberViewX.ds constructor code. Each `CPfs1800*` vtable store is paired with the
  string pushes next to it, found by instruction cross-reference, not by string
  proximity alone.
* Every `IOCTL_GET_DEVICE_DESCRIPTOR` (`0x80002018`) call site in the SCAN08-lineage
  modules, plus the vendor/product compare immediates that follow each one.
* WIA minidriver `PWiaScnr.dll` RTTI-adjacent strings, the 11 gamma-table headers,
  and the InstallShield file-group and component listings (`unshield g` / `c`).

## Evidence table

All addresses are preferred-image VAs in the named, hash-identified PE. Every row is STATIC.

| Binary (SHA-256 prefix) | Address / item | Observation |
| --- | --- | --- |
| CyberViewX.ds `50C9B359` | `0x100a8548` push `"SCAN08"`, `0x100a8555` store AFL vtable `0x10129264`, `0x100a859f` push `"37.GG"` | `CPfs1800AFL` driver name SCAN08, gamma 37. |
| CyberViewX.ds | `0x100a9d58` push `"LC"`, `0x100a9d65` store `CPfs1800P` vtable `0x1012960c`, push `"42.GG"` | **1800P binds LC, not SCAN08.** |
| CyberViewX.ds | `0x100a92a8` `"PF1800LAB"`/`38.GG`; `0x100aa008` `"PF1800U"`/`34.GG` | Lab and U bindings. |
| CyberViewX.ds | AFL `+0x2c = 0x28` (40) at `0x100a85ab`; P `+0x2c = 1` at `0x100a9dbb` | Model-dependent field. A frame-capacity meaning is INFERRED only. It is not the BeneScan model code (40 = PF2700). |
| BeneScan.dll `ACD215AA` | record 3 `0x1004519c`: code `0x25` (37) → `SCAN08.dll` | AFL module. **Absent** from the payload. |
| BeneScan.dll | record 8 `0x100452f0`: code `0x2a` (42) → `LC.dll` | Separate record. Present as `CyberViewX_SF/LC.dll`. |
| BeneScan.dll | 19 records | Present: RAWSCAN, PF1800U, PF2700, LC, SS3600ICE, PF7250U, PS7200. Absent: SCAN08 and 11 others (RFS3600, PF1800LAB, PF3600Pro, PF3610AFL, PowSlide, ProDICE, PF3650LAB, PS3650, PF7250PRO3, DD6000, MF5000). |
| GAMMA/*.GG | headers | Gamma number equals model code wherever both exist (34 U, 37 AFL, 38 Lab, 39 3600Pro, 40 PF2700, 42 "Low Cost", 46, 48, 54). `37.GG` says "Generic gamma file for PF3600AFL", and so does `40.GG`. Labels are copied between files, so they are not identity evidence. |
| LC.dll `5486ACE5` | version resource | `InternalName=SCAN08`, `OriginalFilename=SCAN08.DLL`, `FileDescription=SCAN08 DLL`, comment `SQ Scan08 ASIC`, version 1.0.9.4, link time 2008-06-17. Export-directory name `LC.dll`, single export `ScannerDeviceIO`. |
| LC.dll | strings | `Model Code = 42`, `SDK Version = 1,0,9,4`, `F/W Version = NO F/W`, `USB Standard = USB 1.1`, `Film Hole Position`, `Scan08.ini`, CCD 533/548, `PF3600u.txt`. |
| LC.dll | `0x10011677`, `0x100117f4`, `0x100118d3` | `\\.\USBSCAN%d` + IOCTL `0x80002018`; accepts only **`2770:011C`**. |
| LC.dll imports | SQ_Scan.dll | OpenScanner, GetStatus, SetLamp, MotorMoveNormal, SetAutoScan, QuickInitialAutoScan, GetAutoScanImage, WriteTable … |
| SQ_SCAN.DLL `55A865E7` → IO_PORT.DLL → FVC.DLL | version/strings | "SQ Tech" / "Service & Quality Technology CO.,LTD" ASIC library. FVC.DLL opens `\\.\USBSCAN%d`. No VID check of its own. |
| PF1800LC.Dll `54AB511F` (WXP_DLL = DPInst/LC copy) | version/export | `InternalName=Scan08Dll` 1.0.0.1, link time 2002-11-01, **export-directory name `Scan08.dll`**, export `ScannerDeviceIO`. |
| PF1800LC.Dll | `0x10005cfc`–`0x10005db2` | Walks `\\.\USBSCAN0..127`. IOCTL `0x80002018`. Accepts **`0461:034A`** or **`2770:011C`**. |
| PWiaScnr.dll `AC9B9ABD` | RTTI strings | `CPfs1800AFL` → `37.GG`, `SCAN08`. `CPfs1800P` → `42.GG`, `PF1800LC`. Log text "Load PF1800P okay". |
| DPInst/LC/Pf1800lc.inf | models | `USB\VID_2770&PID_011c`, description "LC". Copies PF1800LC.dll, PWiaScnr.dll, PWiaExt.dll. |
| INF_*/PF3600U.INF | models | Also `USB\VID_2770&PID_011c`. |
| All 22 INFs | hardware IDs | `05E3:0120` (PF1800U), `05E3:0129` (PF2700), `05E3:0145` (PF7250U/SS3600I), `2770:011C`. **None names `0461:034A`. None names an AFL.** |
| data1.hdr | file groups/components | 42 groups, 58 components. No group or path named SCAN08. |
| Disk1/setup.inx | compiled InstallScript | Still encoded. The ISx file-name key does not decode it. Rename or copy logic is **not recovered**. |
| CyberViewX_SF/XP-SF-LC.EXE | Microsoft WEXTRACT self-extractor; RCDATA `CABINET` (263,179 bytes, SHA-256 `5175EC5E…`) expanded with Windows `expand.exe` | 11 files: the same LC WIA package (`PF1800LC.Dll` and `PWiaScnr.dll` hashes identical to `DPInst/LC`; a 2,632-byte `Pf1800lc.inf` variant, still `2770:011C`/"LC"). **No SCAN08.dll.** |
| All 290 payload files + Disk1 | Signature sweep for nested CAB/ZIP/7z/RAR/ISc/gzip/PE past offset 0 | Only XP-SF-LC.EXE holds a real nested container. Every other hit is a coincidental byte pattern inside code: none decompresses, and the `PK` hits in zlib.dll are constants. |

## Interpretation

1. **SCAN08 is a driver lineage, not just a filename.** It is the "SQ Scan08 ASIC"
   family on SQ Technology's `SQ_Scan`/`IO_PORT`/`FVC` stack. The package contains
   two builds from that source tree. Each is shipped under another name, and the
   vendor's own tables bind each one to the **1800P / "Low Cost"** model (code 42),
   not to the AFL (code 37).
2. **The AFL module itself is absent.** BeneScan record code 37 asks for
   `SCAN08.dll`. No payload file has that name. No file group, component or INF
   supplies it. The earlier BeneScan decompile (`0x1000c0f0`) is relevant here:
   discovery walks records 18→0. For each record it calls
   `0x100106d0` (`LoadLibraryA` of module-dir + name, then bare name). It asks the
   module to detect (selector 3) **only if that load succeeds**. So a missing
   SCAN08.dll would most likely skip the AFL record silently, with no visible error.
   That is INFERRED from static control flow. It is not observed.
3. **Candidate USB identities are not AFL identities.** `2770:011C` is the identity
   that LC.dll, PF1800LC.Dll and two INFs accept, and they tie it to the LC/1800P
   and PF3600U families. `0461:034A` is accepted only by the 2002 Scan08Dll build,
   and no INF binds it. Either could belong to the AFL. Neither is attributed to it.
4. **Hazard noted for scanner arrival.** If the physical AFL reports `2770:011C`,
   BeneScan discovery could match LC.dll (model 42) and drive the unit with 1800P
   code. The hardware plan now makes "CyberView identifies a model other than
   PF1800AFL" a stop condition before any transport.

## Classification

| Outcome | Status | Why |
| --- | --- | --- |
| Located | No | No file carries the loader-required name. The SCAN08-named builds are bound to other models. |
| Dynamically supplied | Not established | No installer evidence of a rename, generation or download. `setup.inx` is still encoded. |
| Genuinely missing after runtime verification | Not reached | CyberView has not run. See [runtime-baseline.md](runtime-baseline.md). |
| **Still unresolved** | **Yes** | Static evidence strongly indicates a packaging gap for model 37. Only runtime or the original CD can settle it. |

## Rejected shortcuts

* Renaming LC.dll or PF1800LC.Dll to SCAN08.dll. Their own descriptor checks and
  model codes say they target another model. This would be a substitution,
  forbidden by the directive.
* Fetching "SCAN08.dll" from DLL download sites. Only vendor sources are allowed.
  The official ScanAce all-model page was already searched in the acquisition pass
  (see [inventory](acquisition/inventory.md)). No other official AFL package was found.

## Minimum inputs that would resolve it

1. The original PF1800AFL CD: hash it, inventory it, and search it for `SCAN08.dll`
   and for any InstallScript that renames LC.dll.
2. A runtime trace in a permitted guest (see runtime-baseline.md). It should show
   whether `LoadLibraryA("…\SCAN08.dll")` is attempted, the path tried and the
   resulting Win32 error (expected `ERROR_MOD_NOT_FOUND`, 126).
3. The physical unit's VID/PID, compared against `2770:011C`, `0461:034A` and
   `05E3:0120`.
4. Optional static follow-up: decode `setup.inx` with a reviewed InstallScript
   decompiler to look for model-specific copy/rename logic.
