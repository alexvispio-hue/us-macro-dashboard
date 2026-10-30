/* Pure research helpers shared by the offline page and regression tests. */
(function(root){
  'use strict';
  const KEY='macroview.research.v1';
  function load(storage,known){
    let input={};try{input=JSON.parse(storage.getItem(KEY)||'{}')||{};}catch(e){}
    const ids=new Set(known), unique=arr=>[...new Set(Array.isArray(arr)?arr:[])];
    const state={favorites:unique(input.favorites).filter(id=>ids.has(id)).slice(0,100),
      sizes:{},ranges:{},groups:{},page:typeof input.page==='string'?input.page:'overview',
      timeframe:input.timeframe==='W'?'W':'D',rangeDays:[0,1,7,31,365,1095,1825].includes(input.rangeDays)?input.rangeDays:1825,
      compare:unique(input.compare).filter(v=>typeof v==='string').slice(0,4),compareMode:['level','100','pct','z'].includes(input.compareMode)?input.compareMode:'100',
      linked:unique(input.linked).filter(id=>ids.has(id)).slice(0,100)};
    for(const id of ids){if([256,420].includes(input.sizes?.[id]))state.sizes[id]=input.sizes[id];
      const r=input.ranges?.[id];if(r&&/^\d{4}-\d{2}-\d{2}$/.test(r.from)&&/^\d{4}-\d{2}-\d{2}$/.test(r.to)&&r.from<r.to)state.ranges[id]={from:r.from,to:r.to};}
    for(const [key,value] of Object.entries(input.groups||{}))if(typeof value==='boolean')state.groups[key]=value;
    return state;
  }
  function save(storage,state){try{storage.setItem(KEY,JSON.stringify(state));return true;}catch(e){return false;}}
  function comparison(specs,mode,from,to){
    const clean=specs.map(s=>({name:s.name,color:s.color,data:s.data.filter(p=>p.time>=from&&p.time<=to&&Number.isFinite(p.value??p.close)).map(p=>({time:p.time,value:p.value??p.close}))}));
    if(!clean.length)return {series:[],dates:0,error:'Выберите от двух до четырёх рядов.'};
    const sets=clean.map(s=>new Set(s.data.map(p=>p.time)));
    const dates=clean[0].data.map(p=>p.time).filter(t=>sets.every(set=>set.has(t)));
    if(dates.length<2)return {series:[],dates:dates.length,error:'Недостаточно общих дат. Увеличьте период или выберите ряды с совместимой частотой.'};
    const series=[];
    for(const s of clean){const map=new Map(s.data.map(p=>[p.time,p.value]));const values=dates.map(t=>map.get(t));const mean=values.reduce((a,b)=>a+b,0)/values.length;
      const sd=Math.sqrt(values.reduce((a,v)=>a+(v-mean)**2,0)/(values.length-1));
      if((mode==='100'||mode==='pct')&&values[0]===0)return {series:[],dates:dates.length,error:'База одного из рядов равна нулю. Выберите исходные значения или z-score.'};
      if(mode==='z'&&sd===0)return {series:[],dates:dates.length,error:'У одного из рядов нет изменений за выбранный период; z-score не определён.'};
      const convert=v=>mode==='100'?100*v/values[0]:mode==='pct'?100*(v/values[0]-1):mode==='z'?(v-mean)/sd:v;
      series.push({name:s.name,color:s.color,data:dates.map((time,i)=>({time,value:convert(values[i])}))});
    }
    return {series,dates:dates.length,from:dates[0],to:dates.at(-1)};
  }
  function csv(panel,range){
    const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
    const rows=[['date','series','value','open','high','low','close','volume']];
    for(const s of panel.series)for(const p of s.data||[]){if(range&&(p.time<range.from||p.time>range.to))continue;rows.push([p.time,s.name,p.value,p.open,p.high,p.low,p.close,p.volume]);}
    return '\ufeff'+rows.map(r=>r.map(quote).join(',')).join('\r\n');
  }
  function move(list,id,delta){const out=[...list],i=out.indexOf(id),j=i+delta;if(i>=0&&j>=0&&j<out.length)[out[i],out[j]]=[out[j],out[i]];return out;}
  root.MacroResearch={KEY,load,save,comparison,csv,move};
})(typeof window!=='undefined'?window:globalThis);
