/* DOM logic smoke check. Run: node tests/test_ui.cjs. No browser required. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,'..','dashboard_server.py'),'utf8');
const html = source.match(/HTML = r'''([\s\S]*?)'''/)[1];
const javascript = html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
 constructor(){this.value='';this.checked=false;this.disabled=false;this.style={};this.children=[];this.events={};this.textContent='';}
 addEventListener(name,fn){this.events[name]=fn;}
 append(item){this.children.push(item);}
 replaceChildren(){this.children=[];}
}
const ids = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
const config = JSON.parse(fs.readFileSync(path.join(__dirname,'..','config.json'),'utf8'));
let serverConfig = structuredClone(config), version='"v1"', calls=[];
const status = {strategy_mode:'MTF',dry_run_mode:true,data_mode:'demo',auto_trade_enabled:true,
 total_unrealized_pnl:5,daily_realized_pnl:-3,daily_trades_count:2,open_positions_count:1,
 max_open_positions:3,price_errors:[],runtime:{watchdog_at:Date.now()/1000},
 engaged_margin_usd:1200,allowed_margin_usd:6000,engaged_margin_pct:12,
 allowed_margin_pct:60,margin_budget_utilization_pct:20,reserved_pending_margin_usd:100,
 positions:[{symbol:'BTC/USDT:USDT',side:'long',entry_price:100,trigger_price:100,live_price:105,
 active_sl:90,tp1_price:115,state:'STATE_INITIAL',current_r:.5,unrealized_pnl_usd:5}]};
async function fakeFetch(url,options){
 calls.push([url,options]);assert.equal(options.headers['X-Bot-Pin'],'ui-test-pin');
 let data;
 if(url==='/api/config'&&options.method==='PUT'){
  assert.equal(options.headers['If-Match'],version);serverConfig=JSON.parse(options.body);version='"v2"';data=serverConfig;
 }else if(url==='/api/config'){data=serverConfig;}
 else if(url==='/api/status'){data=status;}
 else if(url==='/api/positions/close-all'){data={results:[],errors:[],remaining_positions:0};serverConfig.bot_control.auto_trade_enabled=false;}
 else if(url==='/api/positions/close'){data={result:'closed'};}
 else throw Error('Unexpected endpoint '+url);
 return {ok:true,json:async()=>structuredClone(data),headers:{get:()=>version}};
}
const context = vm.createContext({document:{getElementById:id=>ids.get(id),createElement:()=>new Element()},
 fetch:fakeFetch,confirm:()=>true,setInterval:()=>0,Date,Number,JSON,Error});
vm.runInContext(javascript,context,{timeout:2000});
(async()=>{
 ids.get('pin').value='ui-test-pin';await ids.get('connect').onclick();
 assert.equal(ids.get('save').disabled,false);
 assert.match(ids.get('mode').textContent,/DRY-RUN.*demo/);
 assert.equal(ids.get('positions').children.length,1);
 assert.equal(ids.get('engaged').value,60);
 assert.match(ids.get('margin').textContent,/1,200.*6,000/);
 assert.equal(vm.runInContext("target({exit_scheme:'PURE_KIJUN',tp1_price:120,hard_tp_price:0})",context),null);
 assert.equal(vm.runInContext("target({exit_scheme:'HARD_TARGET',tp1_price:120,hard_tp_price:140})",context),140);
 assert.equal(vm.runInContext("target({exit_scheme:'PURE_RUNNER',tp1_price:120,hard_tp_price:0})",context),120);
 ids.get('risk').value='1.2';ids.get('risk').events.change();
 assert.equal(JSON.parse(ids.get('editor').value).risk_and_exit.risk_per_trade_pct,.012);
 await ids.get('save').onclick();assert.equal(serverConfig.risk_and_exit.risk_per_trade_pct,.012);
 ids.get('engaged').value='50';ids.get('engaged').events.change();
 ids.get('leverage').value='FIXED_LEVERAGE';ids.get('leverage').events.change();
 ids.get('pyramid').checked=false;ids.get('pyramid').events.change();
 ids.get('exit_tp').value='HYBRID_TRAIL_AND_HARD_TP';ids.get('exit_tp').events.change();
 ids.get('hard_tp').value='4';ids.get('hard_tp').events.change();
 ids.get('breakeven').value='2';ids.get('breakeven').events.change();
 await ids.get('save').onclick();
 assert.equal(serverConfig.risk_and_exit.engaged_capital_pct,.5);
 assert.equal(serverConfig.risk_and_exit.leverage_mode,'FIXED_LEVERAGE');
 assert.equal(serverConfig.strategy_settings.exit_tp_mode,'HYBRID_TRAIL_AND_HARD_TP');
 assert.equal(serverConfig.strategy_settings.hard_tp_rr,4);
 assert.equal(serverConfig.strategy_settings.breakeven_trigger_rr,2);
 assert.equal(serverConfig.strategy_settings.pyramid_enabled,false);
 await ids.get('panic').onclick();assert.equal(ids.get('auto').checked,false);
 assert(calls.some(([url])=>url==='/api/positions/close-all'));
 status.total_unrealized_pnl=null;status.positions=[];await vm.runInContext('refresh()',context);
 assert.equal(ids.get('unrealized').textContent,'—');
 assert.equal(ids.get('positions').children[0].children[0].colSpan,10);
 console.log('PASS: UI connect, render, config sync, ETag save, panic, missing PnL');
})().catch(error=>{console.error(error);process.exitCode=1;});
