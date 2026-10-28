# CyberView acquisition and tooling notes

Research snapshot: 2026-10-27 UTC. Scope is acquisition/tool availability only; the installer was never executed and no host driver or hypervisor was installed.

## Official package

Pacific Image's [All Models Driver Download page](https://www.scanace.com/product/all-models-driver-download-user-guide) lists **PrimeFilm 1800AFL** under discontinued models and links its Windows download to Google Drive file ID `1ZO2fiBFpS6v6B5OnsnYTpDq5Qqr7T-yM`. The same manufacturer table says **Windows XP/Vista/7 only (nothing newer)**, and marks the model EOL. The link's source filename is `PrimeFilm 1800AFL_Windows_SF_ENG_1.3.exe`.

The package was fetched through the manufacturer page's link and Google Drive's executable warning/confirmation flow. Retrieval records (status, redirect chain, selected HTTP headers, byte counts, and UTC time) are in the ignored `research/cyberview/.artifacts/official-pf1800afl-v1.3/acquisition.json`. Cookie headers are deliberately excluded. Original downloaded bytes are at `research/cyberview/.artifacts/official-pf1800afl-v1.3/PrimeFilm_1800AFL_Windows_SF_ENG_1.3.exe` (local filename normalized to underscores).

* Size: 9,898,119 bytes.
* SHA-256: `EBCBE798FE577B9461DF22DB3BDE6240185E0553E65EB9B93D139D367F9109CF`.
* Google Drive response: 200, `application/octet-stream`, `Content-Length: 9898119`, `Last-Modified: Fri, 22 Jul 2022 08:45:55 GMT`; redirect chain is in acquisition metadata.
* Windows version resource: FileDescription `Setup.exe`, FileVersion `14.0.162`, ProductName `InstallShield`, ProductVersion `14.0`, CompanyName `Macrovision Corporation`, OriginalFilename `Setup.exe`, copyright 2007.
* Authenticode status: unsigned (`NotSigned`). This is a provenance observation, not a verdict on the package.
* No alternate-model package was substituted.

### Identity/version discrepancy

The manufacturer-linked filename advertises `...ENG_1.3.exe`, while readable embedded strings identify `CyberView X - SF v1.30 (build 20110526)`. The outer executable identifies itself as InstallShield 14.0.162 / 14.0, not CyberView. These appear to be three different version namespaces. No extracted INF or driver version has yet been established, so do not call the kernel driver version 1.3. The manufacturer's Windows XP/Vista/7 support restriction is also narrower than the generic `Windows` in the package filename.

## Safe archive inspection and extraction

7-Zip 22.01 could not parse the complete setup EXE. Static PE parsing with pefile 2024.8.26 found a 32-bit PE overlay beginning at 0x5B000 (9,525,383 bytes); it begins with `data1.cab`, `Disk1\\data1.cab`, version text `0.0.0.0`, length `498554`, and InstallShield CAB magic `ISc(`. This is not Microsoft CAB (`MSCF`) or `ISSetupStream`.

Two source-code parsers were reviewed:

* [ISx](https://github.com/lifenjoiner/ISx), commit `3c4177ddd0519244490ff8e78d380110c8dacdc8`, is MIT-licensed. Its source README claims DevStudio 9 through InstallShield 2021, and its version table identifies InstallShield 2008 as v14. A temporary source copy was patched to reject absolute paths, drive prefixes, `.` and `..` components, then built with Visual Studio 2022 `cl.exe /DNO_INFLATE` and used to peel the EXE wrapper. No installer code was run.
* [Unshield](https://github.com/twogood/unshield), commit `feaa32f6227fb306a87f4249a6618aa2ddd49966`, is MIT-licensed and supports InstallShield CAB v5 onward. It handles the embedded CAB, not the outer setup.exe wrapper. It was built from source using MSVC/CMake against source-built zlib (zlib license); no prebuilt extractor was used.

ISx returned exit 0 and peeled the outer overlay into files under ignored `research/cyberview/.artifacts/extracted-pf1800afl-v1.3/Disk1/`, including `data1.cab` (498,554 bytes), `data1.hdr` (55,483), `data2.cab` (7,427,648), `ISSetup.dll`, `setup.exe`, `setup.inx`, `setup.isn`, and related support files. It prints `Unrecognized version installer!` after these files; record that warning rather than calling the wrapper parse clean. `unshield l` listed 290 paths with no absolute, drive-prefixed, or `..` entries. `unshield x` returned exit 0 and extracted 290 files (24,474,629 bytes) under ignored `payload/`. No vendor executable, DLL, driver, or script was executed.

The complete tracked per-file size/SHA-256/PE/import inventory is [acquisition/payload-inventory.json](acquisition/payload-inventory.json); a generated copy also remains in ignored `.artifacts`. Reproduction steps and the path-guard patch are in [acquisition/extraction-replay.md](acquisition/extraction-replay.md); provenance and support details are in [acquisition/inventory.md](acquisition/inventory.md). `acquire.py` only downloads/fingerprints; it does not execute or extract.

## USB/VM tool evidence

Primary references reviewed:

* [QEMU USB emulation manual](https://www.qemu.org/docs/master/system/devices/usb.html): QEMU supports virtual USB controllers/devices and real-device host passthrough. `usb-host` is passthrough for an attached physical device; it is not a custom PF1800 emulator. QEMU supports USB traffic capture (`pcap=`). A custom QEMU USB device would require implementing/building a QEMU device model; this is C/QEMU-development work, not a command-line descriptor-only feature.
* [QEMU device emulation guide](https://www.qemu.org/docs/master/system/device-emulation.html) and [qdev API](https://www.qemu.org/docs/master/devel/qdev-api): describes device models/front ends and back ends. QEMU project license is GPL-2.0-or-later; keep any modified QEMU distribution compliant.
* [Linux kernel USB/IP protocol documentation](https://docs.kernel.org/7.2/usb/usbip_protocol.html): USB/IP is a TCP client/server protocol for exporting real USB devices, with an import/export handshake and URB submit/unlink traffic. This protocol is not itself a complete virtual USB device implementation.
* [PyUSB project documentation](https://github.com/pyusb/pyusb): PyUSB controls host-attached USB devices through native backends (libusb is recommended); it is useful for client-side device probing but does not by itself emulate a device.
* [Python `usbip` package on PyPI](https://pypi.org/project/usbip/): current listing advertises a pure-Python USB/IP virtual-device API, MIT license, Python 3.8+, beta status, and POSIX/Linux classifier. It is a promising isolated prototype candidate, not yet independently audited or installed here; confirm source, license, compatibility, and protocol behavior before adopting it. It is distinct from PyUSB.

Read-only PATH checks found no `qemu-system-x86_64`, `qemu-img`, or `usbipd` executable; this is not a full-machine software inventory. The reverse-engineering agent reports a portable QEMU 11.1 build under `research/.tools/qemu-portable/`; its `qemu-img info` command read the extracted Server 2008 VHD metadata, without booting a VM. The reverse-engineering agent also reports Ghidra 12.1.4 in a local tool path. Hyper-V PowerShell commands exist, but `Get-VM` did not return inventory and Windows optional-feature queries returned **requires elevation**; host edition/feature status is unknown. WSL's quiet listing returned no distro names. The CyberView installer is proprietary and remains private research evidence.

### Legitimate Windows guest media reviewed

* Microsoft's current [Windows 11 Enterprise Evaluation Center](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise) lists version 26H2 x64 and Arm64 ISOs and a 90-day evaluation. Registration is required; installation requires a Microsoft account and no product key. The page does not publish ISO byte size before the registration/download flow, so no multi-gigabyte ISO was fetched. Once expired/unactivated, the evaluation shuts down hourly.
* Microsoft's [Windows Server 2008 Enterprise x86 VHD evaluation](https://www.microsoft.com/en-us/download/details.aspx?id=14527) is a preconfigured 32-bit VHD for a 60-day evaluation, explicitly nonproduction. The three official parts were downloaded and SHA-256 recorded; the VHD was extracted after checking free space. The included EULA allows demonstration/internal evaluation in any VHD-capable hypervisor, bars transfer/live use, and expressly forbids activation; README gives Hyper-V setup instructions. Read-only `qemu-img info` reports a dynamic 127 GiB VHD backed by a 7.65 GB file. No guest was booted. See [acquisition/inventory.md](acquisition/inventory.md) for source URLs, hashes, EULA findings and storage constraints.
* Microsoft's [Windows developer VM page](https://developer.microsoft.com/en-us/windows/downloads/virtual-machines/) still reports its VM downloads temporarily unavailable since October 23, 2024.
* The old [Windows 10 Enterprise Evaluation page](https://www.microsoft.com/en-us/evalcenter/evaluate-windows-10-enterprise) redirects to a Windows 10 end-of-support blog. The current [Windows 10 ISO page](https://www.microsoft.com/en-us/software-download/windows10ISO) offers Home/Pro, not Enterprise; Enterprise downloads require the Microsoft 365 admin/VLSC route. No current public Win10 Enterprise evaluation ISO was confirmed.
* Microsoft says [Visual Studio Subscription downloads vary by level](https://learn.microsoft.com/en-us/visualstudio/subscriptions/product-availability) and may include legacy titles after end of support, but some titles are omitted or restricted. Portal access and any required keys depend on the eligible subscription. Exact XP/7 availability cannot be established without that account.
* Microsoft lifecycle information states Windows XP support ended April 9, 2014, and Windows 7 support ended January 14, 2020. No public Microsoft XP/Vista/7 evaluation ISO or current legacy VM image was found. Lawful options are user-owned media/license that permits VM use, an OEM recovery source subject to its license, or a subscription portal that explicitly lists the needed Windows edition and license terms. A used key alone does not establish a transferable VM license.

The extracted CyberView user-mode TWAIN/application files are PE machine `0x14c` (x86), so current x64 Windows can be useful for application-level inspection through WOW64. The official Server 2008 x86 evaluation VHD is a closer app/driver experiment candidate, but the manufacturer's table limits PF1800AFL support to XP/Vista/7; no server installation or scanner-driver validation is claimed. Windows 11 evaluation is not evidence that the old driver or real scanner path will work. Linux/Wine cannot load the Windows `.sys` kernel driver, and no equivalent native TWAIN path was established, so that is not a useful original-CyberView hardware-detection fallback.

### Suggested bounded path

1. Keep the original installer and extracted tree under ignored `.artifacts`; hash each file and preserve acquisition metadata.
2. Continue static analysis of extracted files; never invoke `setup.exe` or extracted installers.
3. For USB protocol work, prefer a Python USB/IP responder only after a pinned-source/license review; record that a guest-side Windows USB/IP client/driver may be a separate dependency. If the goal becomes original CyberView detection, a legally licensed Windows guest and driver binding are prerequisites. QEMU's `usb-host` physical passthrough does not provide a fake scanner.
4. No VM or guest experiment was run in this snapshot.
