# Isolated CyberView research

M1.5 research is independent of FRAME's production scanner backend. Nothing in
this directory grants physical scanner compatibility. Do not run vendor programs
on the host, flash firmware, or issue experimental motor commands.

Start with the [acquisition inventory](cyberview/acquisition/inventory.md) and
[full per-file manifest](cyberview/acquisition/payload-inventory.json). Original
vendor software, Windows media, analysis workspaces and guest disks live under
ignored `.artifacts`, `.tools` or `.venv` directories. They are not redistributed
in this repository. See [extraction instructions](cyberview/acquisition/extraction-replay.md)
for the pinned source parsers used to extract the installer as data.

The passive tools and tests run without downloading any vendor binary:

```powershell
python -m pytest tests/research -q
python -m research.usb.usbip --exercise-log research/usb/evidence/new-harness-run.jsonl
python -m research.usb.inspect_trace --help
```

The USB/IP lab binds only to loopback, advertises zero devices and rejects imports
until a complete evidenced scanner profile exists. Its logs are harness traffic,
not original CyberView interactions. The offline replay engine matches ordered
preserved transfers exactly and rejects uncaptured requests. Synthetic descriptor
test fixtures are never advertised as PF1800 descriptors.

[Guest setup](cyberview/guest-environment.md) distinguishes an infrastructure
smoke test, a guest boot, original CyberView execution and a scanner recognition
attempt. Those are separate pieces of evidence. The official Microsoft evaluation
image is kept unmodified as a read-only base with a disposable overlay; no
activation, altered clock, production use, physical USB or guest network is used.
Read its included license before use.

Analysis-only dependencies live in [analysis/requirements.txt](cyberview/analysis/requirements.txt)
and are not required by the production app or portable research tests. Ghidra
scripts export static function/address evidence. An INF identity, class name or
reconstructed host IOCTL is not a captured USB transaction.

[Hardware plan](cyberview/hardware-plan.md) lists the evidence and bounded
experiments needed when the scanner arrives. Current milestone status is in
[docs/progress.md](../docs/progress.md).
