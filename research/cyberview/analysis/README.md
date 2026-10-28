# Reproduce static analysis

These tools read PE bytes and write research outputs; they never load target DLLs,
call target exports, execute the installer or open physical scanner devices.
Optional dependencies are pinned in `requirements.txt`; the application/test suite
does not require them. Vendor binaries remain ignored, with identities recorded
in `../acquisition/payload-inventory.json`.

```powershell
python -m venv research/.tools/analysis-venv
research/.tools/analysis-venv/Scripts/python.exe -m pip install -r research/cyberview/analysis/requirements.txt
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/pe_survey.py research/cyberview/.artifacts/extracted-pf1800afl-v1.3/payload research/cyberview/.artifacts/payload-survey.json
research/.tools/analysis-venv/Scripts/python.exe research/cyberview/analysis/rtti_map.py research/cyberview/.artifacts/extracted-pf1800afl-v1.3/payload/Resource_ENG/CyberViewX.ds research/cyberview/.artifacts/rtti-rerun.json
```

`pe_survey.py` inventories hashes, PE headers/imports/exports, versions and selected
strings. `rtti_map.py` finds MSVC32 type-descriptor/complete-object-locator/vtable
relationships for the 1800 classes; these are candidates whose operation semantics
still require code analysis. The tracked `rtti-evidence.json` is the actual result
for the inventoried CyberViewX.ds hash.

Obtain the official Ghidra12.1.4 archive and a full64-bit JDK21 before the headless
steps below. Set process-local JAVA_HOME to the chosen JDK; never change global
Java merely for research. The project's directory cannot contain a component
starting with `.`, hence the ignored `workspace.ghidra` directory. The following
is the actual analysis pattern (run from repository root):

```powershell
New-Item -ItemType Directory -Force research/cyberview/analysis/workspace.ghidra | Out-Null
& research/.tools/ghidra_12.1.4_PUBLIC/support/analyzeHeadless.bat research/cyberview/analysis/workspace.ghidra PF1800U -import research/cyberview/.artifacts/extracted-pf1800afl-v1.3/payload/CyberViewX_SF/PF1800U.dll -max-cpu 2 -analysisTimeoutPerFile 180 -scriptPath research/cyberview/analysis -postScript EvidenceSurvey.java research/cyberview/.artifacts/pf1800u-ghidra.json
```

Repeat imports with distinct project names for `BeneScan.dll`, `system/daspi32u.dll`
and `Resource_ENG/CyberViewX.ds` (300-second analysis timeout for the latter).
`EvidenceSurvey.java` emits relevant string references, imported calls, function
locations/callers and selected pseudocode. `DecompileAddresses.java` follows
explicit preferred VAs and additionally emits machine instructions. Its follow-up
pattern uses `-process <imported-name> -noanalysis -postScript
DecompileAddresses.java <new-output.json> <VA>...`.

Actual focused targets included CyberViewX `100a8520 100a9fe0 100bb2a0`, BeneScan
`10011840 10010a30 1000bf50 1000c0f0 100106d0 10010040`, and all unique AFL
vtable methods from the RTTI map. Output is analyst evidence, not runnable vendor
source. Check the PE hash, address ranges and disassembly before interpreting
decompiler types or assigning operation names.

Guest setup/boot is a separate authorized procedure documented in
`../guest-environment.md`. The user stopped Computer Use in the recorded pass;
none of the static-analysis commands resume UI automation or execute CyberView.
