# Preserve source precision and separate rendered precision

The M2 imaging work proceeds independently of M1.5. It changes no experimental USB or scanner behavior.

Decision: use tifffile for unsigned RGB/grayscale TIFF decoding and uncompressed16-bit processed TIFF output. Keep floating-point samples through density inversion, manual film-base adjustment, exposure/contrast and rotation, then quantize once at export. JPEG/previews remain8-bit. Preserve source bytes and hashes exactly.

Evidence: [tifffile upstream](https://github.com/cgohlke/tifffile) documents NumPy TIFF read/write and a BSD-3-Clause license. Version2026.10.15 was installed locally. Tests use exact known8/16-bit synthetic transmission arrays, little/big-endian storage and TIFF orientation tags;16-bit values separated by one code survive neutral export. These are numerical fixtures, not measured photographic negative references.

Every processed TIFF embeds the rendering version, edit settings, original hash, source sample width, output sample width and acquired effective precision when known. Simulator acquisition stays8-bit. A16-bit container from an imported TIFF does not establish the physical scanner's effective precision; that field remains unknown. The output profile is nominal sRGB, not measured scanner calibration.

Alternatives: Pillow's ordinary RGB path reduces TIFF samples to8-bit; converting those samples into a16-bit container afterward loses source information. OpenCV could handle TIFF arrays but introduces a larger distribution dependency and a second decoding API. Tifffile is limited here to its basic uncompressed functionality; extra compression codecs are not silently installed.

Unsupported high-precision input is rejected explicitly. Multi-page TIFF requires explicit page selection,16-bit RGB PNG requires a preserving decoder, and some compressed16-bit TIFFs require codecs not installed in this prototype. Original files and previous exports are never replaced when an export fails. Existing8-bit rendering files are retained under their earlier engine signatures.

Verification: precision/metadata/orientation tests, injected full-disk export failure, legacy-client edit compatibility, independent process restart/export reproduction, and the existing application workflow. Full photographic reference comparisons, calibrated color transforms, crop/curves, large-image memory benchmarks and portable restore remain M2 work.

The already running local service is not restarted by this change. New service processes use the revised engine; the browser exposes new film-base controls only when the service reports that engine, keeping the live M1 service compatible until its next normal restart.
