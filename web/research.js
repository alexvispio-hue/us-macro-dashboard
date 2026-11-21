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
      compareCadence:['auto','exact','week','month','quarter'].includes(input.compareCadence)?input.compareCadence:'auto',
      compareRange:validRange(input.compareRange)?{from:input.compareRange.from,to:input.compareRange.to}:null,
      linked:unique(input.linked).filter(id=>ids.has(id)).slice(0,100),
      todayPanel:ids.has(input.todayPanel)?input.todayPanel:null,profiles:{}};
    for(const id of ids){if([256,420].includes(input.sizes?.[id]))state.sizes[id]=input.sizes[id];
      const r=input.ranges?.[id];if(r&&/^\d{4}-\d{2}-\d{2}$/.test(r.from)&&/^\d{4}-\d{2}-\d{2}$/.test(r.to)&&r.from<r.to)state.ranges[id]={from:r.from,to:r.to};}
    for(const id of ids){
      const r=input.profiles?.[id];
      if(r&&/^\d{4}-\d{2}-\d{2}$/.test(r.from)&&/^\d{4}-\d{2}-\d{2}$/.test(r.to)&&r.from<=r.to)state.profiles[id]={from:r.from,to:r.to};
    }
    for(const [key,value] of Object.entries(input.groups||{}))if(typeof value==='boolean')state.groups[key]=value;
    return state;
  }
  function save(storage,state){try{storage.setItem(KEY,JSON.stringify(state));return true;}catch(e){return false;}}
  function validRange(range){
    const isDate=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)
      && Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
    return !!range&&isDate(range.from)&&isDate(range.to)&&range.from<=range.to;
  }
  const FREQUENCIES=['exact','week','month','quarter'];
  function cadenceOf(spec){
    if(FREQUENCIES.includes(spec.cadence))return spec.cadence;
    const dates=spec.data.slice(-32).map(p=>Date.parse(p.time));
    const gaps=dates.slice(1).map((date,i)=>(date-dates[i])/86400000).sort((a,b)=>a-b);
    const typical=gaps[Math.floor(gaps.length/2)]||0;
    return typical>=60?'quarter':typical>=20?'month':typical>=5?'week':'exact';
  }
  function periodEnd(time,frequency){
    if(frequency==='exact')return time;
    const date=new Date(time+'T00:00:00Z');
    if(frequency==='week')date.setUTCDate(date.getUTCDate()+(7-date.getUTCDay())%7);
    else{
      const month=date.getUTCMonth();
      const endMonth=frequency==='quarter'?Math.floor(month/3)*3+3:month+1;
      date.setUTCMonth(endMonth,0);
    }
    return date.toISOString().slice(0,10);
  }
  function comparison(specs,mode,from,to,frequency='exact'){
    const natural=FREQUENCIES[Math.max(0,...specs.map(s=>FREQUENCIES.indexOf(cadenceOf(s))))];
    const period=frequency==='auto'?natural:frequency;
    if(!validRange({from,to}))return {series:[],dates:0,error:'Укажите корректный период сравнения.'};
    if(period!=='exact'&&FREQUENCIES.indexOf(period)<FREQUENCIES.indexOf(natural)){
      return {series:[],dates:0,error:'Выберите автоматическую или более редкую частоту. Один из рядов публикуется реже.'};
    }
    const clean=specs.map(spec=>{
      const periods=new Map();
      for(const point of spec.data){
        const value=point.value??point.close;
        if(point.time<from||point.time>to||!Number.isFinite(value))continue;
        const time=periodEnd(point.time,period);
        if(time<=to)periods.set(time,{time,value,observation:point.time});
      }
      return {...spec,data:[...periods.values()]};
    });
    if(!clean.length)return {series:[],dates:0,error:'Выберите от двух до четырёх рядов.'};
    const sets=clean.map(s=>new Set(s.data.map(p=>p.time)));
    const dates=clean[0].data.map(p=>p.time).filter(t=>sets.every(set=>set.has(t)));
    if(dates.length<2)return {series:[],dates:dates.length,error:'Недостаточно общих дат. Увеличьте период или выберите ряды с совместимой частотой.'};
    const series=[];
    for(const s of clean){const map=new Map(s.data.map(p=>[p.time,p]));const values=dates.map(t=>map.get(t).value);const mean=values.reduce((a,b)=>a+b,0)/values.length;
      const sd=Math.sqrt(values.reduce((a,v)=>a+(v-mean)**2,0)/(values.length-1));
      if((mode==='100'||mode==='pct')&&values[0]===0)return {series:[],dates:dates.length,error:'База одного из рядов равна нулю. Выберите исходные значения или z-score.'};
      if(mode==='z'&&sd===0)return {series:[],dates:dates.length,error:'У одного из рядов нет изменений за выбранный период; z-score не определён.'};
      const convert=v=>mode==='100'?100*v/values[0]:mode==='pct'?100*(v/values[0]-1):mode==='z'?(v-mean)/sd:v;
      series.push({name:s.name,color:s.color,unit:s.unit||'',key:s.key,
        data:dates.map((time,i)=>({time,value:convert(values[i]),observation:map.get(time).observation}))});
    }
    return {series,dates:dates.length,from:dates[0],to:dates.at(-1),period};
  }
  function csv(panel,range,includeObservation=false){
    const quote=v=>'"'+String(v??'').replace(/"/g,'""')+'"';
    const rows=[['date','series','value','open','high','low','close','volume']];
    if(includeObservation)rows[0].push('observation_date','unit');
    for(const s of panel.series)for(const p of s.data||[]){
      if(range&&(p.time<range.from||p.time>range.to))continue;
      const values=[p.time,s.name,p.value,p.open,p.high,p.low,p.close,p.volume];
      if(includeObservation)values.push(p.observation,s.suffix);
      rows.push(values);
    }
    return '\ufeff'+rows.map(r=>r.map(quote).join(',')).join('\r\n');
  }
  function move(list,id,delta){const out=[...list],i=out.indexOf(id),j=i+delta;if(i>=0&&j>=0&&j<out.length)[out[i],out[j]]=[out[j],out[i]];return out;}
  function volumeProfile(data,from,to){
    const bars=data.filter(d=>d.time>=from&&d.time<=to&&d.volume>0);
    if(!bars.length)return null;
    const low=Math.min(...bars.map(d=>d.low)),high=Math.max(...bars.map(d=>d.high));
    const n=high===low?1:64,step=(high-low)/n;
    const bins=Array.from({length:n},()=>({up:0,down:0}));
    const binFor=price=>step?Math.max(0,Math.min(n-1,Math.floor((price-low)/step))):0;
    for(const bar of bars){
      for(let i=binFor(bar.low);i<=binFor(bar.high);i++){
        const overlap=Math.min(bar.high,low+(i+1)*step)-Math.max(bar.low,low+i*step);
        const fraction=bar.high===bar.low?1:Math.max(0,overlap)/(bar.high-bar.low);
        bins[i][bar.close>=bar.open?'up':'down']+=bar.volume*fraction;
      }
    }
    const totals=bins.map(b=>b.up+b.down),max=Math.max(...totals),poc=totals.indexOf(max);
    const target=totals.reduce((a,b)=>a+b,0)*.7;
    let total=totals[poc],left=poc,right=poc;
    while(total<target&&(left>0||right<n-1)){
      if(right<n-1&&(left===0||totals[right+1]>=totals[left-1]))total+=totals[++right];
      else total+=totals[--left];
    }
    return {from:bars[0].time,to:bars.at(-1).time,low,step,bins,totals,max,poc,left,right,binFor,
      pocPrice:low+(poc+.5)*step,valueLow:low+left*step,valueHigh:low+(right+1)*step};
  }
  function eventReaction(data,event){
    const first=data.findIndex(p=>event.afterClose?p.time>event.date:p.time>=event.date);
    if(first<1)return null;
    const value=p=>p.value??p.close;
    const prior=data[first-1],earlier=data[first-6],reaction=data[first],fifth=data[first+4];
    if(reaction.time>new Date(Date.parse(event.date)+7*86400000).toISOString().slice(0,10))return null;
    const base=value(prior);
    if(!Number.isFinite(base)||base<=0)return null;
    const before=earlier&&value(earlier)>0?(base/value(earlier)-1)*100:null;
    return {first:reaction.time,before,prior:prior.time,day:(value(reaction)/base-1)*100,
      week:fifth?(value(fifth)/base-1)*100:null};
  }
  root.MacroResearch={KEY,load,save,validRange,comparison,csv,move,volumeProfile,eventReaction};
})(typeof window!=='undefined'?window:globalThis);
