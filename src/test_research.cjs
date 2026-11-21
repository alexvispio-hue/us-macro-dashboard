const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx=vm.createContext({});vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/research.js'),'utf8'),ctx);const R=ctx.MacroResearch;
const plain=x=>JSON.parse(JSON.stringify(x));
let saved='';const storage={getItem:()=>saved,setItem:(_,v)=>saved=v};
saved='{bad';assert.deepEqual(plain(R.load(storage,['a']).favorites),[]);
saved=JSON.stringify({favorites:['a','a','gone'],sizes:{a:999999},ranges:{a:{from:'2025-12-31',to:'2020-01-01'}},timeframe:'H'});
let state=R.load(storage,['a']);assert.deepEqual(plain(state.favorites),['a']);assert.deepEqual(plain(state.sizes),{});assert.deepEqual(plain(state.ranges),{});assert.equal(state.timeframe,'D');assert.equal(R.save(storage,state),true);assert.equal(R.save({setItem:()=>{throw Error('full')}},state),false);
assert.deepEqual(plain(R.move(['a','b','c'],'b',-1)),['b','a','c']);assert.deepEqual(plain(R.move(['a','b'],'a',-1)),['a','b']);
const specs=[{name:'A',data:[{time:'2025-01-01',value:10},{time:'2025-01-02',value:15},{time:'2025-01-03',value:20}]},{name:'B',data:[{time:'2025-01-01',value:100},{time:'2025-01-03',value:90}]}];
const original=JSON.stringify(specs),all=['2025-01-01','2025-01-03'];
let result=R.comparison(specs,'100',...all);assert.equal(result.dates,2);assert.deepEqual(plain(result.series.map(s=>s.data.map(p=>p.value))),[[100,200],[100,90]]);assert.equal(JSON.stringify(specs),original);
result=R.comparison(specs,'pct',...all);assert.deepEqual(plain(result.series.map(s=>s.data.map(p=>Math.round(p.value)))),[[0,100],[0,-10]]);
result=R.comparison(specs,'z',...all);for(const s of result.series)assert.ok(Math.abs(s.data.reduce((a,p)=>a+p.value,0))<1e-10);
assert.ok(R.comparison([{name:'zero',data:specs[0].data.map(p=>({...p,value:0}))}],'100',...all).error);
assert.ok(R.comparison([{name:'flat',data:specs[0].data.map(p=>({...p,value:2}))}],'z',...all).error);
assert.ok(R.comparison(specs,'100','2025-01-02','2025-01-02').error);
const csv=R.csv({series:[{name:'a,"quoted"',data:specs[0].data}]},{from:'2025-01-02',to:'2025-01-03'});assert.equal(csv.split('\r\n').length,3);assert.ok(csv.includes('"a,""quoted"""'));assert.ok(!csv.includes('2025-01-01'));
console.log('OK: preferences, validation, order, common-date comparison, base100, percent, z-score, zero bases, CSV escaping');

const trades=[
  {time:'2026-11-17',low:100,high:164,open:110,close:140,volume:6400},
  {time:'2026-11-18',low:120,high:120,open:120,close:120,volume:900},
  {time:'2026-11-19',low:120,high:120,open:120,close:120,volume:10000},
];
const profile=R.volumeProfile(trades,'2026-11-17','2026-11-18');
assert.equal(profile.pocPrice,120.5);
assert.equal(profile.totals.reduce((sum,value)=>sum+value,0),7300);
assert.ok(profile.totals.slice(profile.left,profile.right+1).reduce((sum,value)=>sum+value,0)>=7300*.7);
const flat=R.volumeProfile(trades,'2026-11-19','2026-11-19');
assert.equal(flat.pocPrice,120);
assert.equal(flat.valueHigh,120);
assert.equal(R.volumeProfile(trades,'2026-11-20','2026-11-20'),null);
const closes=[{time:'2026-11-16',close:100},{time:'2026-11-17',close:90},{time:'2026-11-18',close:99}];
const after=R.eventReaction(closes,{date:'2026-11-17',afterClose:true});
assert.equal(after.first,'2026-11-18');
assert.equal(after.prior,'2026-11-17');
assert.ok(Math.abs(after.day-10)<1e-9);
assert.equal(R.eventReaction(closes,{date:'2026-11-19',afterClose:false}),null);
console.log('OK: anchored profile volume, POC and value area, after-close event reaction');
