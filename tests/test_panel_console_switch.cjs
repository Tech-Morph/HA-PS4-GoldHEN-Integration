// Switching console in the panel switches the payload target too.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let Panel;
const select = {value: ''};
const sandbox = {
  HTMLElement: class {
    attachShadow() {
      this.shadowRoot = {innerHTML: '', querySelector: (s) => (s === '#entry-select' ? select : null), querySelectorAll: () => []};
    }
  },
  customElements: {define:(_name,cls)=>{Panel=cls;}},
  alert:()=>{}, requestAnimationFrame:()=>{}, setInterval:()=>0, clearInterval:()=>{}, console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../custom_components/ps4_goldhen/frontend/ps4-goldhen-panel.js'),'utf8'),sandbox);
async function main(){
  const sent=[];
  const p=new Panel();
  p.attachShadow();
  p._hass={
    callWS: async(msg)=>(msg.type === 'ps4_goldhen/list_entries'
      ? {entries:[{entry_id:'a',ps4_host:'192.0.2.1',binloader_port:9090},{entry_id:'b',ps4_host:'192.0.2.2',binloader_port:9021}]}
      : {path:'/', entries:[]}),
    callService: async(domain,service,data)=>{sent.push({domain,service,data});},
  };
  await p._loadEntries();
  p._render();  // attaches the console picker's onchange
  assert.equal(p._selectedEntryId,'a');
  await p._sendPayload('info.elf');
  assert.equal(sent[0].data.ps4_host,'192.0.2.1');
  select.value='b';
  await select.onchange();  // the user picks console B
  await p._sendPayload('info.elf');
  assert.equal(sent[1].data.ps4_host,'192.0.2.2');
  assert.equal(sent[1].data.binloader_port,undefined);  // HA uses the console's own port
  select.value='a';
  await select.onchange();
  await p._sendPayload('info.elf');
  assert.equal(sent[2].data.ps4_host,'192.0.2.1');
  for (const s of sent) assert.deepEqual([s.domain,s.service,s.data.payload_file],['ps4_goldhen','send_payload','info.elf']);
  console.log('PASS: the payload goes to the selected console after every switch, on its own port');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
