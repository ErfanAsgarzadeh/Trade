// Dependency-free UI/scene regression checks. Fixtures are not trading performance.
const fs=require('fs'), vm=require('vm'), assert=require('node:assert/strict'), path=require('path');
const root=path.resolve(__dirname,'..');
let clock=0, offline=false, raf, nextId=1, calls=0;
const timers=new Map(),windowEvents={},nodes=new Map();
class Element {
 constructor(id=''){this.id=id;this.value='';this.checked=true;this.hidden=false;this.disabled=false;this.textContent='';this.innerHTML='';this.children=[];this.attrs={};this.events={};this.tagName='BUTTON';}
 addEventListener(name,fn){this.events[name]=fn;}
 setAttribute(k,v){this.attrs[k]=v;}
 replaceChildren(){this.children=[];this.value='';}
 append(node){this.children.push(node);if(!this.value)this.value=node.value;}
 click(){if(this.onclick)this.onclick();}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id)};
for(const [id,v]of Object.entries({mode:'paper',scope:'open',bot:'all',format:'wide',rotation:'0',language:'en'}))get(id).value=v;
get('pin').value='TEST-PIN-NOT-FOR-PUBLICATION';get('setup').hidden=false;
const context={font:'16px sans-serif',save(){},restore(){},measureText(v){return {width:String(v).length*(parseFloat(this.font)||16)*.53}}};
for(const name of ['clearRect','fillRect','beginPath','moveTo','lineTo','rect','roundRect','arc','fill','stroke','setLineDash','translate','rotate','clip','fillText','drawImage'])context[name]=()=>{};
context.createRadialGradient=()=>({addColorStop(){}});
const canvas=get('stage');canvas.width=1920;canvas.height=1080;canvas.getContext=()=>context;
let trackStops=0;canvas.captureStream=()=>({getTracks:()=>[{stop(){trackStops++}}]});
let recordings=0;
class Recorder {
 static isTypeSupported(){return true}
 constructor(){this.state='inactive';recordings++;}
 start(){this.state='recording';}
 stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable?.({data:new Blob(['test-only'])});this.onstop?.()});}
}
const base=Date.now();class DateClock extends Date {static now(){return base+clock;}}
const document={getElementById:get,createElement:()=>new Element(),activeElement:{tagName:'BODY'},fonts:{ready:Promise.resolve()},documentElement:{requestFullscreen:async()=>{}}};
function makeData(url){
 const q=new URL(url,'http://fixture').searchParams,real=q.get('mode')==='real';let rows=[
  {id:'main:open:BTC',mode:'paper',bot:'main',strategy:'Shahin',symbol:'BTC/USDT:USDT',side:'long',status:'open',entry:100,current_price:110+calls,stop:95,price_move_pct:10,pnl_usd:20,timeframe:'4h',opened_at:base/1000-144000,closed_at:null},
  {id:'c3:open:ETH',mode:'paper',bot:'c3',strategy:'Wave Rider',symbol:'ETH/USDT:USDT',side:'short',status:'open',entry:100,current_price:105,stop:110,price_move_pct:-5,pnl_usd:-10,timeframe:'4h',opened_at:null,closed_at:null}
 ];
 if(real)rows=[{...rows[0],id:'real:open:BTC',mode:'real',bot:'exchange',symbol:'BTCUSDT',strategy:'TheTrueTrade',pnl_usd:null,price_move_pct:null,current_price:null}];
 if(q.get('bot')!=='all')rows=rows.filter(r=>r.bot===q.get('bot'));
 const trade=rows.find(r=>r.id===q.get('trade_id'))||rows[0]||null;
 return {records:rows,trade,candles:real?[]:Array.from({length:30},(_,i)=>[(base/1000-(30-i)*14400)*1000,100+i*.1,102+i*.1,99+i*.1,101+i*.1,10]),
  account:{equity_usd:10020,pnl_usd:real?null:20,return_pct:real?null:.2,basis:'Whole account now'},
  data_mode:'TEST FIXTURE',source_ok:true,publishable:false,generated_at:DateClock.now()/1000,source_started_at:DateClock.now()/1000,
  candle_note:'Completed candles · STALE',notice:'TEST DATA ONLY',warnings:[]};
}
const window={addEventListener:(name,fn)=>windowEvents[name]=fn,MediaRecorder:Recorder};
const sandbox={window,document,console,Date:DateClock,performance:{now:()=>clock},URL,URLSearchParams,Blob,AbortController,MediaRecorder:Recorder,
 Image:class {constructor(){this.complete=true;this.naturalWidth=132;this.width=132;this.height=80;}},
 requestAnimationFrame:fn=>(raf=fn,nextId++),cancelAnimationFrame(){raf=null},
 setTimeout:(fn,ms)=>{const id=nextId++;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id),setInterval:()=>nextId++,
 fetch:async(url,options)=>{calls++;assert(options.headers['X-Bot-Pin']);if(offline)throw Error('fixture offline');return {ok:true,json:async()=>makeData(url)}}};
URL.createObjectURL=()=> 'blob:test';URL.revokeObjectURL=()=>{};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync(root+'/trade_broadcast_svg.js','utf8'),sandbox);
const source=fs.readFileSync(root+'/trade_broadcast.html','utf8').split('<script>')[1].split('</script>')[0];vm.runInContext(source,sandbox);
function tick(ms=50){clock+=ms;const fn=raf;assert(fn);fn(clock);}
const connect=()=>get('connect-form').onsubmit({preventDefault(){}});
(async()=>{
 await connect();tick();let svg=get('screen').innerHTML;
 assert(svg.includes('BTC/USDT:USDT'));assert(svg.includes('TEST DATA'));assert(svg.includes('CANDLES STALE'));
 assert(!svg.includes('TEST-PIN'));assert.equal(get('pin').value,'');assert(get('setup').hidden);
 assert(svg.includes('animateTransform'));assert.equal(get('screen').attrs.viewBox,'0 0 1920 1080');
 get('format').value='portrait';get('connect-form').events.change();tick();assert.equal(get('screen').attrs.viewBox,'0 0 1080 1920');
 get('amounts').checked=false;get('connect-form').events.change();tick();assert(!get('screen').innerHTML.includes('10,020'));
 tick(25000);assert(get('screen').innerHTML.includes('DATA OFFLINE'));assert(!get('screen').innerHTML.includes('BTC/USDT:USDT'));
 await connect();tick();assert(get('screen').innerHTML.includes('BTC/USDT:USDT'));
 offline=true;await connect();tick();assert(!get('screen').innerHTML.includes('BTC/USDT:USDT'));offline=false;
 get('mode').value='real';get('bot').value='c3';await get('mode').onchange();tick();
 assert.equal(get('bot').value,'all');assert(get('bot').disabled);assert(get('screen').innerHTML.includes('BTCUSDT'));assert(!get('screen').innerHTML.includes('BTC/USDT:USDT'));
 get('record').onclick();assert.equal(recordings,1);tick();get('record').onclick();get('record').onclick();assert.equal(recordings,1);await Promise.resolve();await Promise.resolve();assert(trackStops>0);
 get('disconnect').onclick();tick();assert(get('screen').innerHTML.includes('NOT CONNECTED'));assert(!get('screen').innerHTML.includes('BTCUSDT'));
 windowEvents.pagehide();windowEvents.pageshow({persisted:true});tick();assert(get('setup').hidden===false);
 // Exercise escaping separately from the scene fixtures.
 const c=new window.AvinaSVGContext(context);c.fillText('<script>&"',0,0);assert(c.markup().includes('&lt;script&gt;&amp;&quot;'));
 console.log('UI checks passed: SVG layouts, auth privacy, source freshness, recovery, Real separation, recording lifecycle, BFCache, escaping. Codec/browser capture not exercised.');
})().catch(e=>{console.error(e);process.exitCode=1});
