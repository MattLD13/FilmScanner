/* Observe vendor calls only. Never changes arguments, return values or image data. */
'use strict';
const seen = new Set();
const moduleHooks = new Map();
let sequence = 0;
function bytes(address, size) {
  try { return Array.from(new Uint8Array(address.readByteArray(size))).map(x => x.toString(16).padStart(2, '0')).join(''); }
  catch (_) { return null; }
}
function emit(record) { send({time_ms: Date.now(), ...record}); }
function callback(address) {
  const key = 'callback:' + address;
  if (address.isNull() || seen.has(key)) return;
  seen.add(key);
  Interceptor.attach(address, {
    onEnter(args) { emit({event: 'strip', pointer: String(args[0]), block: bytes(args[0], 0x2c)}); }
  });
}
Process.attachModuleObserver({
  onAdded(module) {
    if (!/^(scan08|benescan|beneraw|rawscan|sq_scan|io_port|fvc)\.dll$/i.test(module.name)) return;
    emit({event: 'module', name: module.name, base: String(module.base), size: module.size,
      exports: module.enumerateExports().filter(x => x.type === 'function').map(x => ({name: x.name, rva: String(x.address.sub(module.base))}))});
    if (!/^scan08\.dll$/i.test(module.name)) return;
    const target = module.findExportByName('ScannerDeviceIO');
    if (!target || seen.has(String(target))) return;
    seen.add(String(target));
    const listener = Interceptor.attach(target, {
      onEnter(args) {
        this.selector = args[0].toUInt32(); this.parameter = args[1]; this.id = ++sequence;
        this.size = ({3:36,5:36,9:4,12:4,16:4,20:12,21:8,22:0x85,32:0x4c,17:6,27:6,33:6,35:60})[this.selector] || 0;
        emit({event:'enter', id:this.id, selector:this.selector, parameter:String(this.parameter), block:this.size ? bytes(this.parameter,this.size) : null});
        if (this.selector === 3) {
          try { emit({event:'identity_context', id:this.id, text:this.parameter.add(0x1c).readPointer().readUtf8String()}); }
          catch (_) { /* Optional caller string is not readable. */ }
        }
        if (this.selector === 32) {
          try { callback(this.parameter.add(4 + 0x40).readPointer()); }
          catch (e) { emit({event:'callback_error', message:String(e)}); }
          for (let channel = 0; channel < 3; channel++) {
            try { emit({event:'lut', id:this.id, channel, table:bytes(this.parameter.add(4 + 0x24 + 4 * channel).readPointer(),8192)}); }
            catch (_) { /* Optional table is not readable. */ }
          }
        }
      },
      onLeave(result) {
        emit({event:'leave', id:this.id, selector:this.selector, result:result.toInt32(), block:this.size ? bytes(this.parameter,this.size) : null});
      }
    });
    moduleHooks.set(module.path, {listener, target:String(target)});
    emit({event:'attached', module:module.name, export:'ScannerDeviceIO'});
  },
  onRemoved(module) {
    const hook = moduleHooks.get(module.path);
    if (!hook) return;
    try { hook.listener.detach(); } catch (_) { /* Module is already unmapped. */ }
    seen.delete(hook.target);
    moduleHooks.delete(module.path);
    emit({event:'module_removed', module:module.name});
  }
});
