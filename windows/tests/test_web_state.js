// Regression for edits made while a configuration request is in flight.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const webRoot = path.join(__dirname, '../keydous_bridge/web');
const source = fs.readFileSync(path.join(webRoot, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(webRoot, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(webRoot, 'style.css'), 'utf8');
const code = source.replace(/\ninit\(\);\s*$/, '');
const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length, 'HTML ids must be unique');
for (const id of [
  'state-label', 'state-source', 'device-select', 'connect-button', 'pet-select',
  'layout-select', 'background-color', 'background-text', 'source-selector',
  'hook-review-dialog', 'hook-consent', 'upload-button', 'rgb-toggle',
  'mapping-read-button', 'mapping-bank-selector', 'mapping-controls',
  'mapping-action-select', 'mapping-apply-button', 'mapping-restore-button'
]) assert.ok(ids.includes(id), `missing UI contract id: ${id}`);
for (const route of ['/api/mapping/read', '/api/mapping/apply', '/api/mapping/restore']) {
  assert.ok(source.includes(route), `missing mapping route: ${route}`);
}
assert.match(html, /max-width is set in CSS|class="popover-view"/);
assert.match(css, /\.popover-view\s*\{[^}]*max-width:\s*392px/s);
assert.match(css, /prefers-color-scheme:\s*dark/);
assert.match(css, /data-appearance="dark"/);
const nodes = new Map();
function makeNode() {
  return {hidden:true, checked:false, value:'', children:[], dataset:{},
    classList:{toggle(){},add(){},remove(){}},
    replaceChildren(){this.children=[];this.value='';}, appendChild(child){this.children.push(child);return child;},
    get options(){return this.children;}, addEventListener(){}, setAttribute(){}, closest(){return this;}, remove(){}};
}
const context = vm.createContext({
  assert, console, URLSearchParams,
  window:{setTimeout(){},clearTimeout(){}},
  document: {getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, makeNode());
    return nodes.get(id);
  }, createElement:makeNode, querySelectorAll(){return [];}, querySelector(){return null;}},
});
vm.runInContext(code, context);
vm.runInContext(`
(async () => {
  const mapping = {
    device_key: 'nj98:test', revision: 7, recovery: true, pending: false,
    normal: Array.from({length: 128}, () => [0, 0, 0, 0]),
    fn: Array.from({length: 128}, () => [0, 0, 0, 0]),
    normal_labels: Array(128).fill('No action'),
    fn_labels: Array(128).fill('No action'),
    controls: [{label: 'Knob clockwise', slot: 12}],
    actions: [{id: 'volume_up', label: 'Volume up'}]
  };
  assert.equal(validMappingSnapshot(mapping), true);
  assert.equal(validMappingSnapshot({mapping}), false); // The API contract is the direct snapshot.
  assert.equal(validMappingSnapshot({...mapping, normal: mapping.normal.slice(1)}), false);
  assert.equal(validMappingSnapshot({...mapping, controls: [{label: 'Bad', slot: 128}]}), false);

  // Exercise the real rendering path across an in-flight apply, not a render stub.
  ui.mappingSlot = 12;
  renderMapping(mapping);
  $('mapping-action-select').value = 'volume_up';
  api = async () => ({...mapping, revision:8, normal_labels:Array(128).fill('NEW')});
  await applyMapping();
  assert.equal($('mapping-action-select').disabled,false);
  assert.match($('mapping-current-action').textContent,/NEW/);

  ui.status = {knob:{supported:true,running:false,counts:{}},iot:{connected:true}};
  renderMapping(mapping);
  renderKnob();
  assert.equal($('knob-enable').disabled,false);
  api = async (route, request) => {
    assert.equal(route,'/api/mapping/knob-enable');
    assert.equal(request.body.revision,7);
    return {...mapping,knob_configured:true};
  };
  await configureKnob();
  assert.equal($('knob-restore').disabled,false);
  assert.equal(ui.mappingBusy,false);
  api = async () => {throw new Error('interrupted knob write');};
  await configureKnob(true);
  assert.equal($('knob-enable').disabled,true);
  assert.equal(ui.mapping,null);
  assert.match($('mapping-feedback').textContent,/interrupted knob write/);

  ui.status = {state:'working',source:'hooks',validity:'observed',summary:{execution:2},iot:{connected:true},device:{key:'test',online:true,capabilities:{rgb:true,upload:true}}};
  ui.config = {device_key:'test'};
  $('device-select').value = 'edited-device';
  ui.dirty.add('device_key');
  api = async () => {throw new Error('offline');};
  await pollStatus();
  assert.equal(ui.status.validity,'unknown');
  assert.equal($('hook-execution').textContent,'—');
  assert.equal($('mapping-apply-button').disabled,true);
  assert.equal($('upload-button').disabled,true);
  assert.equal($('device-select').value,'edited-device');
  ui.dirty.clear();

  let mappingRequest = null;
  let invalidated = '';
  api = async (route, options) => {
    mappingRequest = {route, options};
    return {...mapping, revision: 8};
  };
  renderMapping = snapshot => { ui.mapping = snapshot; };
  setMappingFeedback = () => {};
  invalidateMapping = message => { invalidated = message; ui.mapping = null; };
  toast = () => {};
  ui.mapping = mapping;
  ui.mappingSlot = 12;
  $('mapping-action-select').value = 'volume_up';
  await applyMapping();
  assert.equal(mappingRequest.route, '/api/mapping/apply');
  assert.equal(JSON.stringify(mappingRequest.options.body),
    JSON.stringify({revision: 7, bank: 'normal', slot: 12, action: 'volume_up'}));
  assert.equal(ui.mapping.revision, 8);
  ui.mapping = mapping;
  ui.mappingSlot = 12;
  $('mapping-action-select').value = 'volume_up';
  api = async () => { throw new Error('键盘配置已变化'); };
  await applyMapping();
  assert.match(invalidated, /重新读取/);
  assert.equal(ui.mapping, null);
  mappingRequest = null;
  ui.mapping = {...mapping, pending: true};
  ui.mappingSlot = 12;
  api = async () => { mappingRequest = true; };
  await applyMapping();
  assert.equal(mappingRequest, null, 'pending recovery must block mapping writes');

  const draft = {source:'manual', background:'#112233', rgb_enabled:false, device_key:'old', pet_id:'bridge-cat', layout:'pet', session_path:''};
  currentDraft = () => ({...draft});
  schedulePreview = () => {};
  let resolve;
  let calls = 0;
  postAction = () => { calls++; return new Promise(done => {resolve = done;}); };
  ui.config = {};
  markDirty('background');
  const saving = saveConfig();
  markDirty('rgb_enabled');
  markDirty('device_key');
  $('rgb-toggle').checked = true;
  await saveConfig(); // A second save cannot race the first transaction.
  assert.equal(calls, 1);
  resolve(draft);
  await saving;
  assert.equal(ui.dirty.has('background'), false);
  assert.equal(ui.dirty.has('rgb_enabled'), true);
  assert.equal(ui.dirty.has('device_key'), true);
  assert.equal($('rgb-toggle').checked, true);
  assert.equal($('dirty-badge').hidden, false);
  assert.equal(ui.config.device_key, 'old');
  assert.equal(ui.configBusy, false);
  console.log('UI in-flight configuration regression passed');
})()
`, context).catch(error => {console.error(error); process.exitCode = 1;});
