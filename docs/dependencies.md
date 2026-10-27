# Dependency and runtime choices

FRAME uses Python for its local API, scanner simulator, and imaging, and React with TypeScript for the responsive client. Shared data contracts live in `packages/contracts`. SQLite is the local persistence choice; Python's standard-library `sqlite3` avoids an extra native database dependency.

## Current stack

| Area | Choice | Reason and evidence |
| --- | --- | --- |
| Local API | FastAPI served by Uvicorn | Uses the specification's flexible candidate-stack policy; the installed package metadata identifies FastAPI as MIT and Uvicorn as BSD-3-Clause. |
| Image processing | NumPy and Pillow | Python array and image building blocks aligned with the imaging requirement; installed metadata identifies NumPy's bundled notices as BSD-3-Clause, 0BSD, MIT, Zlib, and CC0-1.0, and Pillow as MIT-CMU. Review upstream notices when redistributing bundled binaries. |
| High-precision TIFF | tifffile | Version2026.10.15, BSD-3-Clause; preserves unsigned16-bit TIFF samples and writes processed16-bit RGB without an intermediate8-bit image. Optional imagecodecs dependencies are not installed. |
| Local persistence | SQLite through `sqlite3` | Built into Python; avoids adding a separate ORM or server before the workflow needs one. |
| Client | React, TypeScript, Vite | Fits the specified responsive React/TypeScript client and conventional local development/build workflow. npm registry metadata reports MIT for React, Apache-2.0 for TypeScript, and MIT for Vite; verify exact transitive licenses when dependencies are locked. |

The current environment reports Python 3.13.1, Node.js 24.19.0, and npm 11.17.0. FastAPI 0.141.1, Uvicorn 0.40.0, NumPy 2.4.0, and Pillow 12.0.0 are installed; their license identifiers above come from local Python package metadata. npm registry metadata was queried on 2026-10-27 for the current React, TypeScript, and Vite package releases; these are not yet pinned by a project lockfile. These observations establish availability in this environment, not the project's locked versions or a supported deployment matrix.

The client now has package-lock.json. Initial `npm install` installed 71 packages and its audit reported zero vulnerabilities. The checked-in sRGB.icc is a 588-byte profile generated using Pillow/LittleCMS, retained as an immutable asset so export ICC timestamps remain reproducible across restarts. It describes the export space, not measured scanner calibration.

## Alternatives and boundaries

The specification suggests ASP.NET for the API and Python for imaging, while explicitly allowing smaller candidate-stack choices. The prototype uses Python for the API, simulator, and imaging to avoid an additional runtime. No .NET SDK was returned by `dotnet --list-sdks` in this environment. TWAIN integration is deferred until scanner hardware, vendor documentation, and driver behavior can be verified; this stack choice makes no claim of TWAIN or PF1800 support. See the architecture decision for alternatives and tradeoffs.

Do not copy external project code into FRAME. Use package releases through their official distribution channels, preserve their licenses/notices when redistributing, and avoid committing environment-specific dependency state or credentials.

## Sources

- [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Uvicorn documentation](https://www.uvicorn.org/)
- [NumPy licensing](https://numpy.org/doc/stable/license.html)
- [Pillow documentation](https://pillow.readthedocs.io/)
- [React documentation](https://react.dev/)
- [TypeScript documentation](https://www.typescriptlang.org/docs/)
- [Vite documentation](https://vite.dev/guide/)
