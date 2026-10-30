// Regression checks execute the actual range-change handler embedded in the page.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../web/index.html'),'utf8');
const start=html.indexOf('      chart.timeScale().subscribeVisibleTimeRangeChange(r => {');
const end=html.indexOf('\n      chart.subscribeCrosshairMove',start);
assert.ok(start>0&&end>start);
const handlerSource=html.slice(start,end);
const ctx=vm.createContext({});
vm.runInContext(`
let syncOn=false, groupSyncOn=false, blocked=false, currentRange={from:'2021-01-01',to:'2026-01-01'},handler;
const panel={id:'source'},box={dataset:{}},stored=new Map(),linkedIds=new Set();
const isoFrom=t=>t;
const isSyncing=()=>blocked;
const holdSync=()=>{blocked=true;};
const rememberRange=(p,r)=>stored.set(p.id,{...r});
const chart={timeScale:()=>({subscribeVisibleTimeRangeChange:fn=>handler=fn})};
const calls=[];
const charts=[{chart,panel},...['a','b'].map(id=>({panel:{id},chart:{timeScale:()=>({setVisibleRange:r=>calls.push({id,...r})})}}))];
${handlerSource}
`,ctx);
const read=code=>JSON.parse(vm.runInContext('JSON.stringify('+code+')',ctx));
vm.runInContext("handler({from:'2023-01-01',to:'2025-01-01'})",ctx);
assert.deepEqual(read('calls'),[],'Wheel must not broadcast in independent mode');
assert.equal(read("stored.get('source').from"),'2023-01-01');
assert.equal(read('currentRange.from'),'2021-01-01','Local wheel must not overwrite the global preset');
vm.runInContext("syncOn=true;handler({from:'2024-01-01',to:'2025-01-01'})",ctx);
assert.equal(read('calls.length'),2,'Explicitly linked charts must follow the source');
assert.equal(read('currentRange.from'),'2024-01-01');
vm.runInContext("calls.length=0;handler({from:'2020-01-01',to:'2025-01-01'})",ctx);
assert.deepEqual(read('calls'),[],'Programmatic range events must not cause a feedback loop');
vm.runInContext("syncOn=false;groupSyncOn=true;blocked=false;linkedIds.add('source');linkedIds.add('a');handler({from:'2024-01-01',to:'2025-01-01'})",ctx);
assert.equal(read('calls.length'),1,'Only marked peers may follow a selected group');
assert.equal(read('calls[0].id'),'a');
assert.match(html,/let syncOn = false/);
assert.doesNotMatch(html,/localStorage.getItem\("md_sync"\)/,'A saved old preference must not restore the reported bug');
console.log('OK: independent scroll, explicit linking, global preset isolation, feedback suppression');
