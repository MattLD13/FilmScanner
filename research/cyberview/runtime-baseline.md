# CyberView no-device runtime baseline

Status on 2026-10-27/28 UTC: **not captured. External blocker.** Original CyberView
has never run in any environment for this project. There are no screenshots,
module-load records or error codes from a CyberView process. This file states the
blocker precisely and lists the exact steps that remain.

## Environment actually available

| Item | Checked this pass | Result |
| --- | --- | --- |
| Host | Windows 11 Pro 10.0.26200, x64 | `WindowsSandbox.exe` absent; `HypervisorPresent=False`. No feature was enabled. Hyper-V/Sandbox would need a host security/configuration change, which is outside this research's permissions. |
| Emulator | `qemu-system-i386` 11.1.0 (`v11.1.0-12130-ge470268ff4`), portable, TCG | Present. Includes `usb-redir` (socket chardev, `pcap=` capture) and UHCI/EHCI/xHCI controllers. See [virtual-device-feasibility](../usb/virtual-device-feasibility.md). |
| Guest base | Official Microsoft Server 2008 Enterprise x86 evaluation VHD | `guest_lab.py verify-base` → SHA-256 `bc57268875ab…d19d`, `unchanged: true`. |
| Guest overlay | `.artifacts/guest-lab/experiment.qcow2` | qcow2 over read-only `vpc` base, 132 MiB on disk. It still holds the state from the earlier stop at the product-key OOBE page. `guest_lab.py status` → connection refused: no QEMU running. |
| Free host disk | C: | About 40 GB free. The lab's ≥8 GiB reserve and ≤2 GiB overlay checks still apply. |
| Vendor media | Official installer, SHA-256 `EBCBE798…09CF` | Preserved. The read-only research CD contains only this installer and its hash. |

License facts are in [guest-environment.md](guest-environment.md): internal
evaluation only, 60 days from first installation, no activation, no production
use. The guest's own expiry state is unknown, because setup has never finished.

## Why no baseline exists

Every remaining step to a running CyberView needs interactive guest input:

1. **Server 2008 OOBE.** Leave the product key blank (as the README instructs).
   **Accept the Windows evaluation license terms.** **Set a password** for the
   built-in Administrator account.
2. Install CyberView from the research CD. This means the InstallShield dialogs,
   including **the vendor license agreement**, model selection and any driver prompts.
3. Launch CyberView with no device attached, and record what happens.

These steps hit three boundaries at once:

* The previous Computer Use session was **stopped by the user with the physical
  Escape key**. The directive and this project's rules require fresh user steering
  before guest UI control resumes. That includes driving the guest through QEMU's
  own keyboard injection instead of Computer Use.
* Accepting license terms requires explicit user approval.
* Setting the Administrator password is a human-action stop condition. Doing it
  through an injected `unattend.xml` would only move the same acceptance and
  credential step out of view, so that was **not** done.

No input was sent to the guest this pass. No key, password, EULA acceptance,
activation, clock change or evaluation extension was attempted.

## What the run should capture once authorized

Order matters. One snapshot of the overlay goes before each stage.

1. The user completes OOBE themselves in the QEMU window: blank key, accept the
   EULA, set their own password. Alternatively, the user explicitly authorizes
   bounded input for the non-credential screens. Then `guest_lab.py screenshot`.
2. Install CyberView from the CD. Record which components install, every dialog,
   every error, and whether any driver package (DPInst LC/U, USBSCAN, GENEUSB)
   asks to install. Install no driver unless the user approves it for this guest.
3. Launch with no device. Record separately (a) whether the application/TWAIN host
   process starts, (b) TWAIN source registration, and (c) scanner detection: the
   exact dialog or status text, and any model it names.
4. Module-load evidence for `SCAN08.dll`. Prefer a tool already inside the guest.
   A Sysinternals Process Monitor binary would have to be brought in on the
   research CD, which needs the user's approval to download. Expected result if
   the static reading is right: `…\Twain_32\CyberViewX_SF\SCAN08.dll` NAME NOT
   FOUND, then the bare-name search fails, with no user-visible error.
5. Shut the guest down through QMP and run `verify-base`.

Stop conditions still apply: a password or security prompt that needs a human,
an activation barrier, an expired evaluation, a driver-install prompt the user has
not approved, or the resource budget being exhausted.

## Windows 11 application-only alternative

This is still unattempted. The host has no Sandbox or hypervisor. Running vendor
x86 code directly on the main Windows installation is not "appropriately
isolated," so it was not done. A disposable Windows 11 evaluation VM under TCG
would run very slowly and would also need the user's Microsoft account to download
it. Even a successful window would establish only application startup. It would
not show TWAIN registration through the x86 drivers, or scanner operation.
