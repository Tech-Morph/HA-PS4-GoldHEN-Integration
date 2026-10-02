const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let Panel;
const sandbox = {
  HTMLElement: class { attachShadow() { this.shadowRoot = {querySelector:()=>null}; } },
  customElements: {define:(_name,cls)=>{Panel=cls;}},
  alert:()=>{}, requestAnimationFrame:()=>{}, console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../custom_components/ps4_goldhen/frontend/ps4-goldhen-panel.js'),'utf8'),sandbox);
function setup(subscribe) {
  const p=new Panel();
  p.isConnected=true;p._tab='klog';p._selectedEntryId='one';
  p._hass={connection:{subscribeMessage:subscribe}};
  p._render=()=>{
    if (!p._klogUnsub && !p._klogConnecting && !p._klogManuallyDisconnected) p._klogConnect();
  };
  return p;
}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
async function main(){
  let count=0,unsub=0,callback;
  let d=deferred();let p=setup((cb,msg)=>{count++;callback=cb;assert.equal(msg.entry_id,'one');assert.equal(msg.port,undefined);return d.promise;});
  const pending=p._klogConnect();await p._klogConnect();assert.equal(count,1);
  d.resolve(()=>unsub++);await pending;assert.ok(p._klogUnsub);assert.equal(p._klogConnecting,false);
  callback({line:'test'});assert.equal(p._klogLines[0],'test');
  p._klogDisconnect(true);assert.equal(unsub,1);
  callback({line:'stale'});assert.equal(p._klogLines.length,1);

  d=deferred();unsub=0;p=setup(()=>d.promise);
  const abandoned=p._klogConnect();p._klogDisconnect(true);d.resolve(()=>unsub++);await abandoned;
  assert.equal(unsub,1);assert.equal(p._klogUnsub,null);

  count=0;p=setup(async()=>{count++;throw new Error('failed');});await p._klogConnect();
  assert.equal(count,1);assert.equal(p._klogManuallyDisconnected,true);

  d=deferred();unsub=0;p=setup(()=>d.promise);const switched=p._klogConnect();p._selectedEntryId='two';p._klogDisconnect(true);d.resolve(()=>unsub++);await switched;
  assert.equal(unsub,1);assert.equal(p._klogUnsub,null);

  count=0;p=setup(async()=>{count++;return ()=>{};});p.isConnected=false;await p._klogConnect();assert.equal(count,0);
  p.isConnected=true;p._tab='ftp';await p._klogConnect();assert.equal(count,0);
  console.log('PASS: overlap guard, payload shape, event handling, stale callbacks, pending disconnect, failure retry guard, console switch, detached/wrong-tab guards');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
