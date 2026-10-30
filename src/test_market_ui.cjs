// Node-only checks of the exact aggregation code embedded in the offline page.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../web/index.html'),'utf8');
const start=html.indexOf('  const weeklyCache ='),end=html.indexOf('  // Метка',start);
const context=vm.createContext({});
vm.runInContext("let timeframe='W';"+html.slice(start,end),context);
const run=code=>JSON.parse(vm.runInContext('JSON.stringify('+code+')',context));
const result=run(`dataFor({type:'candles',data:[
 {time:'2026-09-21',open:10,high:14,low:9,close:12,volume:100},
 {time:'2026-09-25',open:12,high:16,low:8,close:15,volume:300},
 {time:'2026-09-28',open:15,high:18,low:14,close:16,volume:200}]})`);
assert.deepEqual(result,[{time:'2026-09-21',open:10,high:16,low:8,close:15,volume:400},{time:'2026-09-28',open:15,high:18,low:14,close:16,volume:200}]);
assert.deepEqual(run(`dataFor({type:'volume',data:[{time:'2026-09-21',value:100},{time:'2026-09-25',value:300}]})`),[{time:'2026-09-21',value:400}]);
assert.deepEqual(run(`dataFor({type:'line',data:[{time:'2026-09-21',value:4.2},{time:'2026-09-25',value:4.3}]})`),[{time:'2026-09-21',value:4.3}]);
assert.deepEqual(run('dataFor({data:[]})'),[]);
console.log('OK: weekly OHLC, volume conservation, final observation, empty data');
