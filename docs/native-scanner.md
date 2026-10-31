# CyberScan X direct AFL capture

October 30, 2026. **A real current-frame RGB acquisition works through the installed
AFL module, without TWAIN or the CyberView application window.** This is native
integration with vendor libraries, not a complete independent USB driver.

## Use

Build with `npm run build:native` and `npm run build`, then open CyberScan X.
In **Settings → Native scanner integration**, acknowledge the startup behavior
and choose **Use native capture**. Selection is saved in the local library and
does not initialize or move the scanner. Startup can home the transport when a
scan is requested.

Native capture scans a loaded **35 mm negative strip** at the configurations
recorded in `services/scanner_host/native_validation.json`: 1800 dpi 16-bit,
600 dpi 16-bit, and a 300 dpi 8-bit prescan. It checks loaded-strip status
before scanning. After a scan in the same session it also offers next and
previous frame, forward eject, autofocus and film-base measurement, the controls
that file records as tested on the device (see [cyberview-parity.md](cyberview-parity.md)).
Batch scans use next frame between frames. Every other control in the module
stays disabled until it is tested; the full list is in
[scan08-feature-catalog.md](scan08-feature-catalog.md). **Use CyberView capture**
returns to the TWAIN workflow, which has automatic USB-reset recovery.

> Sections below "Actual physical result" describe the first current-frame
> experiments, before the transport and focus tests above were recorded.

The original is vendor-calibrated transmission with identity lookup tables.
CyberScan X initially enables its own nominal negative inversion for this source.
Manual red/green/blue film-base references and adjustments are saved as a recipe
and applied to display/export only. Color characterization remains unmeasured.
Original TIFF export stays byte-identical; adjusted TIFF is 16-bit, JPEG is 8-bit.
The corrected physical acquisition is saved in the user's library under
**Native integration test**; its research original remains preserved.

## Actual physical result

The user explicitly approved native initialization and a current-frame test with
expendable film loaded. No reverse, ejection, firmware or speculative diagnostic
command was issued. Both native experiments exited normally.

| Observation | First prototype | Corrected capture |
| --- | --- | --- |
| Image geometry | 2479 × 1703 | 2479 × 1703 |
| Delivered strips | 49, totaling 1703 rows | 49, totaling 1703 rows |
| Container | unsigned 16-bit RGB | unsigned 16-bit RGB |
| Maximum R/G/B | 31600 / 0 / 0 | 50160 / 36800 / 23792 |
| Interpretation | Failed color validation | All three channels populated |

The first prototype omitted a status query that latches the driver's film type.
Static analysis explained the exact failure: the mounted-negative branch uses
integer division that turns green and blue exposure into zero for normal inputs.
The corrected helper first queries masked status and requires the loaded-strip
bit. The successful repeat validates that correction; the failed capture is
retained as failed evidence.

All observed low four sample bits are zero, consistent with the recovered
12-bit lookup domain. This does not measure effective sensor precision, noise
performance or true sensor RAW. Effective precision stays unknown. Personal
images and full process traces remain in ignored local storage.

The helper pins SCAN08.dll 1.0.3.6 by SHA-256, checks model-37 geometry, constrains
DLL search and rejects arbitrary commands. Native and TWAIN helpers share scanner
ownership. USB reset checks that ownership before operating. Native timeouts
request cooperative cancellation and reserve a stuck session; they do not
force-kill or automatically reset motors.

## Discoveries

The [address-linked investigation](../research/cyberview/installed-native-investigation.md)
recovers 37 selector cases and 33 verified wrapper calls. Lesser-known features include:

- Four diagnostic processing dumps: `1_Raw.raw`, `2_AfterFT.raw`, `3_AfterAG.raw`,
  `4_AfterUC.raw`, plus `5_raw.log`. These are intermediate stages, not proof of sensor RAW.
- Native acquisition buckets at 300/360/450/600/900/1800 dpi despite the broken
  TWAIN resolution list. Only 1800 dpi has been tested in this backend.
- Two CCD paths, a detailed AFL calibration log, manual focus, minimum-density
  routines and extended line-acquisition diagnostics.
- Other accepted USB IDs and hidden QA/multisample settings. Their presence does
  not establish support on this scanner. No infrared channel is established.

These controls remain disabled pending bounded evidence. No installed vendor
setting or firmware was changed to expose them.

## Verification and limits

Synthetic DLL tests cover the actual C ABI, row copying, malformed transfers,
no-film rejection, cancellation, queue overflow and file preservation. API tests
cover selection persistence, startup cancellation, reset ownership and timeout
quarantine. The browser workflow uses a synthetic pipe helper and exercises
native selection, single-frame controls, inversion, film base and exports.
These tests are separate from the real physical helper experiments.

The real desktop inspection was stopped by the user's physical Escape key after
the idle old window was closed. No further app input was attempted. Reopen
CyberScan X to load the update; launching it does not start a scan.

Full independent USB protocol recovery, native transport, other modes,
photographic reference comparisons, scanner color calibration and repeated
real-roll validation remain incomplete. The original simulator is unchanged.
