# Guest-visible virtual PF1800 AFL: feasibility and negative result

Pass: 2026-10-27/28 UTC, work package D. **Result: unable to build an evidence-backed
AFL profile. No guest-visible scanner was presented.** The existing passive parsers,
the exact replay engine and the loopback USB/IP management harness are still the
only implemented emulator parts. None of them has enumerated a device to Windows.

## Existing parts audited

| Module | What it really does | Reuse |
| --- | --- | --- |
| `protocol.py` | Passive setup-packet and descriptor decoder. Rejects malformed input. Default command registry is empty, so every vendor payload is rejected. | Validate any captured descriptors before use. |
| `replay.py` | Exact, ordered request→response replay with provenance. Unknown transfers are rejected. | Response source for a future device backend. |
| `usbip.py` | USB/IP **management plane** on 127.0.0.1: DEVLIST→empty, IMPORT→refused, passive CMD_SUBMIT decoder. | Nothing for QEMU. USB/IP is not usbredir. |
| `qemu_probe.py` | Stopped/diskless QMP smoke test. | Infrastructure check only. |

## Chosen architecture (not built)

Checked this pass: portable QEMU 11.1.0 provides `-device usb-redir` with options
`chardev`, `filter`, `pcap`, `serial` and others, plus `socket` chardevs and UHCI/EHCI/xHCI host controllers.
The direct, isolated path to a guest is:

```text
Windows guest USBSCAN  ⇄  QEMU UHCI  ⇄  usb-redir (pcap=…)  ⇄  loopback TCP chardev  ⇄  Python usbredir "host-side" device server  ⇄  replay.py profile
```

* The Python server speaks the [usbredir protocol](https://www.spice-space.org/usbredir.html):
  hello/capabilities, `device_connect`, `interface_info`, `ep_info`, then control,
  bulk and interrupt packets. It would replace no part of `usbip.py`. A USB/IP socket
  must never be passed to `usb-redir`. The two wire protocols are unrelated
  ([QEMU USB](https://www.qemu.org/docs/master/system/devices/usb.html),
  [Linux USB/IP](https://docs.kernel.org/usb/usbip_protocol.html)).
* QEMU's own `pcap=` output records guest↔device traffic independently of the
  emulator's log. That keeps captured "original CyberView traffic" separate from
  simulator test traffic.
* There is no host-USB passthrough, no host driver and no network. It is
  loopback only and fits the existing `guest_lab.py` isolation.
* The rejected alternative is a USB/IP→usbredir relay, for example through a Linux VM
  running `usbip` plus `usbredirserver`. It needs a second guest and a kernel
  importer, and its behavior is harder to bound.

Prerequisites before any code: (1) descriptor and initialization evidence from the
model, (2) a running CyberView in the guest (see
[runtime-baseline](../cyberview/runtime-baseline.md)), (3) a usbredir test peer that
is not the vendor software.

## Why no AFL profile can be attached: precise proof

1. **The AFL code path needs a module the package lacks.** CyberViewX
   `CPfs1800AFL` binds driver `SCAN08` (`0x100a8548`). BeneScan model 37 maps
   that to `SCAN08.dll` (`0x1004519c`). Discovery (`0x1000c0f0`) calls the model's
   detect selector only after `LoadLibraryA` succeeds. No file of that name exists
   ([scan08-investigation](../cyberview/scan08-investigation.md)). So with this
   package, no USB device, however accurate, can be recognized **as a PF1800 AFL**
   by the AFL class. **GUEST OBSERVED 2026-10-28:** at launch, BeneScan searched
   five paths for `SCAN08.dll`, never loaded it, skipped the AFL record and
   reported no scanner ([runtime-baseline](../cyberview/runtime-baseline.md)).
2. **The only USB identities in the SCAN08 lineage belong to other models.**
   `2770:011C` is accepted by LC.dll (model 42, 1800P "Low Cost") and by
   PF1800LC.Dll, and is bound by the LC and PF3600U INFs. `0461:034A` is accepted
   only by the 2002 Scan08Dll build, and no INF names it. Presenting `2770:011C` would at most test
   CyberView's **1800P** path through LC.dll. Labeling that as an AFL would be false.
3. **The descriptor is unknown beyond VID/PID.** No device class, bcdDevice,
   endpoint addresses or types, max-packet sizes, strings or speed have been
   recovered. LC.dll's string `USB Standard = USB 1.1` is a log label, not a descriptor.
4. **Only a host-side framing is known.** See the
   [protocol notebook](../cyberview/protocol-notebook.md#sq-stack-host-framing-static).
   For the SQ stack used by LC.dll, FVC.DLL writes `[reg−0x78, value]` and reads
   with `[0xF0, reg−0x78]` + 1 byte over the USBSCAN bulk handle. No response values,
   status bits, image framing or safe register set are known. An emulator answering
   those requests would be inventing scanner behavior.

## What a repeatable experiment would look like (blocked)

Once runtime and identity evidence exists, the first experiment is enumeration
only. The Python server presents exactly the captured descriptors. It answers
standard requests from the capture and STALLs and logs every vendor request. A
`pcap` file and an emulator JSONL log are kept per run. Success means Windows
binds USBSCAN and CyberView reports a model. Extending to status, calibration or
prescan needs one original-software trace per operation (see the
[hardware plan](../cyberview/hardware-plan.md)). Without that evidence, the honest
experiment is this negative one, and nothing was run against the guest.

## Host-API simulation actually run (2026-10-28)

Because of point 1, the user asked for a simulated AFL. FRAME built a labeled
simulator one layer up: a research `SCAN08.dll` that implements BeneScan's
model-module contract, recovered from LC.dll. Original CyberView detected it,
opened it, prescanned and scanned to a TIFF through it
([afl-simulator.md](../cyberview/afl-simulator.md)). That run is GUEST OBSERVED
against a SIMULATOR. **It is not a guest-visible USB device and not an AFL USB
profile.** The usb-redir path above is still unbuilt for the same evidence reasons.

## Explicitly not claimed

No QEMU boot, USB/IP loopback, synthetic descriptor fixture or Ghidra decompile is
reported as CyberView detection. No PF1800 descriptor, VID/PID or response bytes
are shipped in code or tests.
