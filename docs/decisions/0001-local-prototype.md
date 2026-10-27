# Local simulated vertical slice

Decision: one FastAPI/Python service owns SQLite metadata, archival files, developing sessions, image processing and simulator orchestration. A React/TypeScript client is served from that same origin. The actual workspace remains C:/Users/mld20/Documents/FilmScanner, preserving the supplied specification there rather than moving user files to its suggested C:/FilmScanner location.

Evidence: Python 3.13, FastAPI, NumPy, Pillow and Node 24 are installed; `dotnet --list-sdks` returns no SDK. FRAME_SPEC section10 calls its stack candidates, not requirements. No original vendor drivers, photos, reference screenshots or hardware are present.

Alternatives: ASP.NET/SignalR would fit a future Windows scanner host but requires an SDK now and duplicates the Python image runtime. Electron adds packaging work without helping M1. A browser-only archive cannot reliably own immutable originals or coordinate a future scanner.

Tradeoffs: Python acquisition runs sequentially with small synthetic fixtures. Production TIFF sizes require streaming/bounded worker processing and benchmarks. Simulator output is an 8-bit 192x128 synthetic transmission chart, not 1800 DPI image data. Metadata states the actual precision. Image exports are currently 8-bit sRGB, with no 16-bit claim. Manual film-base selection, measured calibration and advanced color work remain M2.

Reversibility: ScannerBackend is independent of HTTP and storage. A later C#/32-bit TWAIN bridge can implement the same operations with explicit unsupported capability errors. No real device command is enabled by this prototype.

Verification: API tests exercise develop to 36-frame scanning, frame17 recovery, cancellation, originals hashes, separate edits, JPEG/TIFF export, archive integrity, backup creation, and process restart. Browser tests validate the same production client on desktop and a phone-size viewport.

Network boundary: production startup binds 127.0.0.1. Same-origin local bootstrap creates an HttpOnly session cookie; archive/API/WebSocket access requires that cookie. LAN pairing, scoped companion tokens and HTTPS are deferred. Phone-size browser validation is not a claim of actual iPhone LAN access or reliable background alarms.
