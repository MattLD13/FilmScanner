# Windows 11 application compatibility versus scanner compatibility

Question raised during M1.5: can the original CyberView program run on Windows11
using compatibility mode instead of a legacy guest?

The application-only test is useful and remains unattempted. Microsoft documents
that WOW64 permits32-bit user applications on64-bit Windows, while32-bit kernel
drivers require porting; there is no equivalent driver translation layer.
[Microsoft driver guidance](https://learn.microsoft.com/en-us/windows/win32/winprog64/drivers).
Microsoft also provides application compatibility troubleshooting for older
programs on Windows11.
[Microsoft compatibility guidance](https://support.microsoft.com/en-us/windows/apps/make-older-apps-or-programs-compatible-with-the-latest-version-of-windows).

The extracted CyberView loader/TWAIN components are x86 PE files. The preserved
GENEUSB/USBSCAN driver payloads are also x86. The official manufacturer listing
supports XP/Vista/7, not Windows11. Those observations establish why application
startup and legacy scanner-driver loading need separate tests. They do not prove
that every possible modern scanner backend is impossible.

An eventual application-only Windows11 experiment should record normal startup,
startup under a specific compatibility setting, component-loading errors and
scanner-enumeration behavior separately. A successful window opening does not
establish a working scanner or replace the isolated vendor/USB experiment. It
should avoid installing the package's legacy kernel drivers or changing system
security settings. The existing specification's isolation requirement remains in
effect for experimental work.

At the current checkpoint, the host was confirmed64-bit. WindowsSandbox.exe was
not present at the standard System32 location; no feature was installed or enabled.
The official Server2008x86 evaluation guest was booted instead, with a read-only
base, disposable overlay, no guest NIC, no shared host directories and no physical
USB passthrough. It reached first-run regional setup before the UI attempt ended.
CyberView itself has not yet been launched in either environment.

This report records the comparison and actual evidence; it does not claim a
Windows11 compatibility-mode result.
