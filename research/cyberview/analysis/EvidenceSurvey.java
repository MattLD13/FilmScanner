// Static analysis only: exports strings, callers, function locations and pseudocode.
// @category FRAME
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import java.util.*;
import java.util.regex.*;
import java.nio.file.*;
import com.google.gson.GsonBuilder;

public class EvidenceSurvey extends GhidraScript {
    String addr(Address a) { return a == null ? null : a.toString(); }
    Map<String,Object> functionRecord(Function f) {
        Map<String,Object> row = new LinkedHashMap<>();
        row.put("name", f.getName()); row.put("entry", addr(f.getEntryPoint()));
        row.put("size", f.getBody().getNumAddresses());
        return row;
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Output JSON path required");
        Pattern interest = Pattern.compile("usb|scsi|focus|calib|expos|gain|firmware|motor|eject|prescan|position|1800|gene|inquir|download|acquir|readfile|writefile|deviceiocontrol|createfile", Pattern.CASE_INSENSITIVE);
        Map<String,Object> report = new LinkedHashMap<>();
        report.put("program", currentProgram.getName());
        report.put("image_base", addr(currentProgram.getImageBase()));
        report.put("language", currentProgram.getLanguageID().toString());
        report.put("evidence", "Ghidra-static-not-executed");
        List<Object> strings = new ArrayList<>(), imports = new ArrayList<>(), functions = new ArrayList<>();
        Set<Function> selected = new LinkedHashSet<>();
        DataIterator di = currentProgram.getListing().getDefinedData(true);
        while (di.hasNext() && !monitor.isCancelled()) {
            Data d = di.next();
            if (!d.hasStringValue()) continue;
            String text = String.valueOf(d.getValue());
            if (!interest.matcher(text).find()) continue;
            Map<String,Object> row = new LinkedHashMap<>();
            row.put("va", addr(d.getAddress())); row.put("value", text);
            List<Object> refs = new ArrayList<>();
            for (Reference r : getReferencesTo(d.getAddress())) {
                Function f = getFunctionContaining(r.getFromAddress());
                Map<String,Object> rr = new LinkedHashMap<>();
                rr.put("from", addr(r.getFromAddress())); rr.put("type", r.getReferenceType().toString());
                if (f != null) { rr.put("function", functionRecord(f)); selected.add(f); }
                refs.add(rr);
            }
            row.put("references", refs); strings.add(row);
        }
        SymbolIterator syms = currentProgram.getSymbolTable().getExternalSymbols();
        while (syms.hasNext()) {
            Symbol s = syms.next();
            if (!interest.matcher(s.getName()).find()) continue;
            Map<String,Object> row = new LinkedHashMap<>();
            row.put("name", s.getName()); row.put("address", addr(s.getAddress()));
            List<Object> refs = new ArrayList<>();
            for (Reference r : s.getReferences()) {
                Function f = getFunctionContaining(r.getFromAddress());
                Map<String,Object> rr = new LinkedHashMap<>(); rr.put("from", addr(r.getFromAddress()));
                if (f != null) { rr.put("function", functionRecord(f)); selected.add(f); }
                refs.add(rr);
            }
            row.put("references", refs); imports.add(row);
        }
        FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
        while (fi.hasNext()) {
            Function f = fi.next(); functions.add(functionRecord(f));
            if (interest.matcher(f.getName()).find()) selected.add(f);
        }
        // Follow callers one step to include transport wrappers around imported APIs.
        List<Function> seed = new ArrayList<>(selected);
        for (Function f : seed) for (Function caller : f.getCallingFunctions(monitor)) selected.add(caller);
        DecompInterface dec = new DecompInterface(); dec.openProgram(currentProgram);
        List<Object> decompiled = new ArrayList<>();
        for (Function f : selected) {
            if (monitor.isCancelled()) break;
            Map<String,Object> row = functionRecord(f);
            List<Object> calls = new ArrayList<>();
            for (Function target : f.getCalledFunctions(monitor)) calls.add(functionRecord(target));
            row.put("calls", calls);
            DecompileResults dr = dec.decompileFunction(f, 45, monitor);
            row.put("completed", dr.decompileCompleted());
            if (dr.decompileCompleted()) row.put("pseudocode", dr.getDecompiledFunction().getC());
            else row.put("error", dr.getErrorMessage());
            decompiled.add(row);
        }
        dec.dispose();
        report.put("interesting_strings", strings); report.put("interesting_imports", imports);
        report.put("functions", functions); report.put("selected_functions", decompiled);
        Files.writeString(Path.of(args[0]), new GsonBuilder().setPrettyPrinting().create().toJson(report));
        println("FRAME_SURVEY: " + currentProgram.getName() + " functions=" + functions.size() + " selected=" + decompiled.size());
    }
}
