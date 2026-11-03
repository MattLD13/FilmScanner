# Vendor automatic tone: recovered worker and observed caller sequence

November2 continuation: the Generic Negative vendor UI sequence and RGB16 table
reuse are now physically observed and replayed exactly. See
[processing validation](cyberview-processing-validation-2026-11-02.md) for the
successful vendor prescan/scan, copied buffers, exact table/TIFF comparisons,
new automatic defaults, per-preview reuse and remaining acquisition limits.
The earlier uncertainty described below is retained as historical context.

This implementation is deliberately distinct from complete CyberView appearance parity.
It operates on saved images without scanner I/O. Vendor binaries/tables remain local.

## Exact supported paths

- The pinned `CyberViewX.ds` SHA-256 is `bfe1bac8744320a41d23ee7b51b21b4e0e31004eea4a7a49a68b32b522fd28bb`.
- `vendorcolour autotables` constructs CFilmCIP and invokes worker `0x10103810` on caller-owned RGB8/RGB16 buffers, returning three 256-entry WORD tables.
- Flag 1 selects the separate negative-histogram branch: resize/convert image to an 8-bit working plane, `0x10008bd0`, then copy generated tables through `0x100068b0`.
- Flag 0 uses histogram controls through `0x10101220` and the six-point gamma builder `0x101045b0`.
- These are not the separate UI control-curve builder `0x10115290` / Lagrange worker `0x10104360`. Duplicate implicit endpoints in the latter can produce unusable zero/binary curves; the earlier investigation should not be read as proof that all vendor automatic tone is broken.
- Python application matches CFilmCIP mode 7: RGB8 uses direct lookup; RGB16 table knots have input and output spacing 257, with integer interpolation. CPU-oracle tests cover all 196608 RGB16 channel samples and the RGB8 domain.

`services/imaging/vendor_autogamma.py` provides `generate_tables()` and `apply()`.
Generation runs a bounded pinned CPU-only subprocess. The worker refuses a running
CyberView application, protects its settings with a mutex, restores both existing
INI contents and prior absence, and refuses output overwrite. Application is in
Python and verifies shape/range/monotonicity. Generation additionally refuses a
channel with fewer than eight distinct output levels. Table checks do not imply
that every accepted photographic result is desirable.

## FRAME integration

At the earlier checkpoint, **Try vendor auto tone** was an explicit experimental edit. It generated tables from
the current converted-positive plane with optional model/film conversion, before
display controls and optional cleanup filters. Tables and branch/input-plane
diagnostics are saved in the viewing recipe. Preview/export apply them once.
Enabling it cleared the earlier automatic-color edit and neutralized extra display
levels/gamma/gains/curve to avoid accidental stacking. Disabling removes the tables.
Source TIFFs remained unchanged. That earlier option was not enabled by default;
the newer supported Generic Negative default and per-preview reuse are described
in the November2 report linked above.

At that checkpoint, `caller_stage_order_verified: false` was intentional. Static wrapper `0x10113ce0`
receives a prepared BCImage in the larger scan worker; the complete UI's prior
plane construction, settings, and subsequent processing state have not yet been
reconstructed sufficiently to claim pixel-identical CyberView output. Exact worker
and interpolation tests are necessary evidence, not proof of that full sequence.

The older Auto color control retains its independently verified parameter
calculation and its existing approximate curve interpolation. It should not be
presented as an exact port of the entire UI curve-builder pipeline.

## Verification

Run `python -m pytest -q tests/imaging/test_vendor_autogamma.py tests/api/test_vendor_auto_tone_api.py`.
Tests include real pinned CPU-worker execution when available, exhaustive integer
application comparisons, invalid/degenerate tables, saved recipes, guarded errors,
processing-preview behavior, and immutable original acquisitions. No scanner command
is used by the vendor automatic-tone tests.
