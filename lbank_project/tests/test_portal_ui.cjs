/* Portal interaction test with a small DOM stub; no browser or live exchange. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'../portal.html'),'utf8');
const source=fs.readFileSync(path.join(__dirname,'../portal.js'),'utf8');
class Element{constructor(){this.value='';this.children=[];this.events={};this.hidden=false;this.disabled=false;this.textContent='';}addEventListener(k,fn){this.events[k]=fn;}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
const ids=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
let loggedIn=false,configured=false,verified=false,queued=false,calls=[],late=null;
let timerId=0;const timers=new Map();
async function fetch(url,options){
 calls.push([url,options]);assert.equal(options.credentials,'same-origin');assert.equal(options.headers['X-Portal-Request'],'1');
 let data={},status=200;
 if(url==='/api/login'){loggedIn=true;data={csrf:'csrf-alice'};}
 else if(!loggedIn){status=401;}
 else if(url==='/api/me'){data={username:'alice',csrf:'csrf-alice'};}
 else if(url==='/api/exchanges'){data={exchanges:[{id:'lbank',name:'LBank',markets:['spot'],required_fields:{spot:['apiKey','secret']}},{id:'okx',name:'OKX',markets:['spot','futures'],required_fields:{spot:['apiKey','secret','password'],futures:['apiKey','secret','password']}}]};}
 else if(url==='/api/logout'){assert.equal(options.headers['X-CSRF-Token'],'csrf-alice');loggedIn=false;}
 else if(url==='/api/me/robots'){data={robots:[{name:'شاهین',state:'running',positions:[{symbol:'BTC/USDT',side:'long',entry_price:100,active_sl:90}],trades:[]},{name:'ققنوس',state:'not_provisioned',positions:[],trades:[]}]};}
 else if(url==='/api/me/connection/refresh'){assert.equal(options.headers['X-CSRF-Token'],'csrf-alice');queued=true;data={status:'queued'};}
 else if(url==='/api/me/connection'){
  if(options.method==='PUT'){assert.equal(options.headers['X-CSRF-Token'],'csrf-alice');configured=true;data={status:'saved_unverified'};}
  else if(options.method==='DELETE'){configured=false;verified=false;}
  else{data={configured,market:'spot',account:verified?{status:'verified_read_only',checked_at:100,snapshot:{balances:[{asset:'USDT',free:42,locked:3,total:45}]}}:queued?{status:'queued',snapshot:null}:null};if(late){const wait=late;late=null;await wait;}}
 }else throw Error('Unexpected URL '+url);
 return {ok:status===200,status,json:async()=>data};
}
const context=vm.createContext({document:{getElementById:id=>{assert.ok(ids.has(id),id);return ids.get(id);},createElement:()=>new Element()},fetch,Date,Promise,confirm:()=>true,setTimeout:(fn,delay)=>{assert.ok(delay>=15000);timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)});
vm.runInContext(source,context);
(async()=>{
 await new Promise(setImmediate);
 assert.equal(ids.get('account-panel').hidden,true);
 ids.get('username').value='alice';ids.get('password').value='strong-password-123';
 await ids.get('login-form').events.submit({preventDefault(){},submitter:new Element()});
 assert.equal(ids.get('account-panel').hidden,false);assert.equal(ids.get('password').value,'');
 assert.equal(ids.get('robots').children.length,2);
 ids.get('exchange-id').value='okx';ids.get('api-key').value='old-key';ids.get('api-secret').value='old-secret';ids.get('exchange-id').events.change();
 assert.equal(ids.get('api-key').value,'');assert.equal(ids.get('passphrase-field').hidden,false);assert.equal(ids.get('passphrase').required,true);
 ids.get('exchange-id').value='lbank';ids.get('passphrase').value='old-passphrase';ids.get('exchange-id').events.change();
 assert.equal(ids.get('passphrase').value,'');assert.equal(ids.get('passphrase-field').hidden,true);
 ids.get('market').value='spot';ids.get('api-key').value='alice-api-key';ids.get('api-secret').value='alice-secret-value';
 await ids.get('connection-form').events.submit({preventDefault(){},submitter:new Element()});
 assert.equal(ids.get('api-key').value,'');assert.equal(ids.get('api-secret').value,'');
 await ids.get('refresh-account').events.click();
 assert.equal(ids.get('balances').children.length,0);assert.equal(timers.size,1);
 queued=false;verified=true;const [timer,callback]=timers.entries().next().value;timers.delete(timer);await callback();
 assert.equal(ids.get('balances').children.length,1);
 let release;late=new Promise(resolve=>release=resolve);
 const pending=vm.runInContext('connection()',context);
 await ids.get('logout').events.click();release();
 await assert.rejects(pending);
 assert.equal(ids.get('account-panel').hidden,true);assert.equal(ids.get('balances').children.length,0);
 assert.ok(!source.includes('localStorage'));assert.ok(!source.includes('innerHTML'));
 console.log('Portal UI: login, credential clearing, own-account rendering, logout and stale-response protection passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
