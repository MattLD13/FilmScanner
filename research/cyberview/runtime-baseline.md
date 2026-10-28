# CyberView no-device runtime baseline

Status 2026-10-28 UTC: **captured. GUEST OBSERVED.** Original CyberView X SF v1.30
was installed and launched in the isolated evaluation guest with no scanner
attached. It requested `SCAN08.dll`, did not find it, probed every other model
module, then showed "Unable to communicate with the Film Scanner" and exited.
Tracked record: [runtime-baseline-2026-10-28.json](analysis/evidence/runtime-baseline-2026-10-28.json).
Screenshot: [cyberview-no-device-2026-10-28.png](analysis/evidence/cyberview-no-device-2026-10-28.png).
Tests: `tests/research/test_runtime_baseline.py`.

## Environment

| Item | Value |
| --- | --- |
| Guest | Microsoft Windows Server 2008 Enterprise x86 evaluation, 6.0.6001. Official VHD, base SHA-256 `bc57268875ab…d19d`, re-verified unchanged. No product key. Not activated. |
| Emulator | QEMU 11.1.0 TCG, `pc`, 2 vCPU, 1024 MiB. **No NIC**, no host shares, no host USB passthrough. Only USB device: QEMU's input tablet. |
| Disks | qcow2 overlay over a read-only base. Restore point `restore-01-pre-oobe.qcow2` (SHA-256 `e52727a1…c9e3`). The first OOBE attempt hung on a typed key; it is kept as `abandoned-oobe-keypage-…qcow2`. |
| Media | Vendor CD (installer `EBCBE798…09CF`, ISO `3ef1e3dc…7f00`). Tools CD (`20d63ce4…86f7`) holding the tracked `guest_tools/BASELINE.CMD` and `COLLECT.CMD`. A blank FAT12 evidence floppy. |
| Licenses | Microsoft evaluation EULA, accepted by the user during OOBE. CyberView EULA, read in full, then accepted by the user in chat for this guest. Its section 4 forbids reverse engineering, decompiling or disassembly. The user's stated position is that the software is unmaintained and right-to-repair reverse engineering is acceptable. That is the user's decision, recorded here; it is not a legal opinion. |

## Who did what

* **User:** OOBE in the QEMU window (blank key, evaluation EULA, their own
  Administrator password), and acceptance of the CyberView EULA.
* **Research tooling:** QMP-only input into the guest, logged one event per line in
  ignored `guest-lab/inputs.jsonl`. It never controls the host desktop and never
  types credentials. Actions: closed Initial Configuration Tasks; Run →
  `D:\CyberView-Official.exe`; paged through the EULA; clicked **Yes** after the
  user's approval; dismissed "connect the scanner"; swapped in the tools CD; Run →
  `BASELINE.CMD`; Run → `COLLECT.CMD`; dismissed the CyberView error.

## Installation result

* Pages shown: License Agreement, then "Please connect the scanner to the computer now
  and turn on the scanner. The rest of the installation will proceed
  automatically." There was no destination, model or language page, and no finish page.
* **No driver-install prompt** appeared. DPInst did not run. `USBSCAN.SYS` was copied to
  `system32\drivers`. No device is bound, because there is no scanner.
* Files: `C:\Windows\twain_32\CyberViewX_SF\` holds the payload's CyberViewX_SF tree
  plus DPInst and Vista helpers, `SQ_SCAN.DLL`, `IO_PORT.DLL`, `FVC.DLL` and
  `daspi32u.dll` in `system32`. Start menu "CyberViewX_SF" has three shortcuts.
  Uninstall key `{D8FF6E29-…}`, InstallLocation `C:\Program Files\Pacific Image ELectronics Co., Ltd.\CyberView X - SF v1.30 (build 20110526)`.
* **`SCAN08.dll` was not installed anywhere.** The installer neither generates nor
  renames it.

## Launch result (no device)

`PfsLoader.exe` was started under the NT Kernel Logger (process, image, fileio). The
trace ran 71 s with 34,730 events and **0 lost**. In time order:

1. PfsLoader loads `CyberViewX.ds`, which loads `BeneScan.dll`.
2. BeneScan walks its model table **from record 18 down to record 1**, exactly the
   static order of `0x1000c0f0`. For each record it opens `Twain_32\CyberViewX_SF\<module>`:
   * **Loaded** (and probed): PS7200, PF7250U, SS3600ICE, **LC** (which pulled in
     `system32\SQ_SCAN.DLL` → `IO_PORT.DLL` → `FVC.DLL`), PF2700 (writes
     `%TEMP%\PF2700.log`), PF1800U (writes `%TEMP%\PF1800U.log`).
   * **Absent, skipped with no message:** MF5000, DD6000, PF7250PRO3, PS3650, PF3650LAB,
     ProDICE, PowSlide, PF3610AFL, PF3600Pro, PF1800LAB, **SCAN08**, RFS3600.
3. `SCAN08.dll` and `PF1800LAB.dll` each go through the full search:
   `Twain_32\CyberViewX_SF`, `system32`, `system`, `Windows`, `System32\Wbem`.
   No image load follows, matching `LoadLibraryA` failure in `0x100106d0`. The
   Win32 error code itself is not in a kernel trace. `ERROR_MOD_NOT_FOUND` (126) is
   the expected value, not an observed one.
4. Record 0 (RAWSCAN) is never probed.
5. Dialog **"Unable to communicate with the Film Scanner. Try the following: Make
   sure the scanner power is on / Check all cables / Refer to the User's Manual on
   the CD as needed."** After OK, the process exits. No main window opened.
6. Persistent change: `CyberViewX.ini` `Pfs Loader Call=0 → 1`.

Not established by this run: whether the loaded modules opened `\\.\USBSCANn` or
`\\.\Geneusbn`. With no device, those opens fail in the object manager, and this
trace configuration did not record them. A registry or Process Monitor capture
would be needed for that.

## Meaning

* **SCAN08.dll is genuinely missing for this official package**, now verified at
  runtime. A real PF1800 AFL connected to this installation cannot be driven by
  the AFL module.
* Recognition with this package therefore depends on whether a loaded module
  (LC, PF1800U, PF2700, PF7250U, SS3600ICE, PS7200) claims the device's VID/PID. If
  one does, CyberView will treat the unit as **that** model. See the hardware-plan
  stop condition.

## Reproduce

```powershell
python research/cyberview/analysis/guest_lab.py start --budget-minutes 120
python research/cyberview/analysis/guest_lab.py insert --media evidence
# user completes OOBE; then CyberView install from the vendor CD (EULA needs the user's acceptance)
python research/cyberview/analysis/guest_lab.py insert --media tools   # then Run D:\BASELINE.CMD, observe, Run D:\COLLECT.CMD
python research/cyberview/analysis/guest_lab.py read-evidence
python research/cyberview/analysis/kernel_trace.py table-walk.json <collected>/MODELS.TXT <collected>/SCAN08.TXT <collected>/APP.TXT
python research/cyberview/analysis/guest_lab.py verify-base
```

Raw ETL/CSV stay inside the guest at `C:\FRAME`. The floppy's text extracts, with
hashes, are in ignored `guest-lab/collected-20261028T014601Z/`.
