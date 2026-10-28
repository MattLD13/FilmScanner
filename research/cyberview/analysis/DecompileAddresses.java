// Export explicitly selected functions, calls, callers and machine instructions.
// @category FRAME
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.util.*;
import java.nio.file.*;
import com.google.gson.GsonBuilder;

public class DecompileAddresses extends GhidraScript {
    Map<String,Object> record(Function f) {
        Map<String,Object> row = new LinkedHashMap<>();
        row.put("name", f.getName(true)); row.put("entry", f.getEntryPoint().toString());
        row.put("size", f.getBody().getNumAddresses()); return row;
    }
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) throw new IllegalArgumentException("output and one or more VA required");
        DecompInterface dec = new DecompInterface(); dec.openProgram(currentProgram);
        List<Object> rows = new ArrayList<>();
        for (int i = 1; i < args.length; i++) {
            Address address = toAddr(args[i]); Function f = getFunctionAt(address);
            if (f == null) { disassemble(address); f = createFunction(address, null); }
            if (f == null) { println("NO FUNCTION: " + args[i]); continue; }
            Map<String,Object> row = record(f);
            List<Object> calls = new ArrayList<>(), callers = new ArrayList<>(), instructions = new ArrayList<>();
            for (Function target : f.getCalledFunctions(monitor)) calls.add(record(target));
            for (Reference ref : getReferencesTo(f.getEntryPoint())) {
                Map<String,Object> rr = new LinkedHashMap<>();
                rr.put("from", ref.getFromAddress().toString()); rr.put("type", ref.getReferenceType().toString());
                Function caller = getFunctionContaining(ref.getFromAddress());
                if (caller != null) rr.put("function", record(caller)); callers.add(rr);
            }
            InstructionIterator ii = currentProgram.getListing().getInstructions(f.getBody(), true);
            while(ii.hasNext()) {
                Instruction instruction = ii.next();
                instructions.add(instruction.getAddress().toString() + " " + instruction.toString());
            }
            row.put("calls", calls); row.put("references", callers); row.put("instructions", instructions);
            DecompileResults dr = dec.decompileFunction(f, 60, monitor);
            row.put("completed", dr.decompileCompleted());
            if (dr.decompileCompleted()) row.put("pseudocode", dr.getDecompiledFunction().getC());
            else row.put("error", dr.getErrorMessage()); rows.add(row);
        }
        dec.dispose();
        Map<String,Object> report = new LinkedHashMap<>(); report.put("program", currentProgram.getName());
        report.put("image_base", currentProgram.getImageBase().toString());
        report.put("functions", rows);
        Files.writeString(Path.of(args[0]), new GsonBuilder().setPrettyPrinting().create().toJson(report));
        println("FRAME_TARGETED: " + rows.size());
    }
}
