// Mock DOM/network checks for the real forecast script. No payments or browser session.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const path=require('node:path'), {randomUUID}=require('node:crypto');
const root=path.resolve(__dirname,'../backend');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const js=fs.readFileSync(path.join(root,'demand_forecast_ui.js'),'utf8');
new vm.Script(js);
function element(){return {children:[],handlers:{},attributes:{},value:'',textContent:'',disabled:false,hidden:false,
  append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},
  setAttribute(key,value){this.attributes[key]=value},addEventListener(name,fn){this.handlers[name]=fn}};}
const el={};for(const m of html.matchAll(/\bid="([^"]+)"/g))el[m[1]]=element();
el['forecast-source'].value='actual';
const products=[{id:1,sku:'PEN',name:'<b>Blue Pen</b>',stock:17},{id:2,sku:'BOOK',name:'Notebook',stock:30}];
const records=new Map(), receipts=new Map(), calls=[], events={};
let actualReady=false, loseResponse=false, failBefore=false, stall=false, releaseTrain;
let holdRead=false, releaseRead, missingPackage=false;
const response=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>JSON.parse(JSON.stringify(data))});
function status(id,source){
  const saved=records.get(id+':'+source);
  return {product:products.find(p=>p.id===id),source,shop_date:'2026-10-14',ready:source==='demo'||actualReady,
    reason:source==='demo'?'Ready: 60 consecutive demo days.':'Need 56 consecutive actual days.',
    coverage:{consecutive_days:source==='demo'?60:actualReady?60:0,stockout_days:0,last_day:'2026-10-12'},
    report:saved?.report??null,report_current:saved?.report_current??false,
    message:saved?.report_current===false?'Saved forecast is outdated. Train again.':source==='demo'?'Demo forecast: synthetic data only.':'Forecast is advisory.',
    advice:source==='actual'&&saved?.report_current?{stock_now:17,seven_day_gap:5,message:'Review delivery and buffer.'}:null};
}
function trained(id,source){
  const items=Array.from({length:7},(_,i)=>({date:`2026-10-${15+i}`,model_units:4+i,baseline_units:5,selected_units:5}));
  const report={demo:source==='demo',source,selected_method:'seven_day_mean',selection_reason:'ML did not improve tested error by at least 5%.',
    selected_total_units:35,items,training_days:60,data_start:'2026-08-14',data_end:'2026-10-12',bridge_days:2,
    evaluation:{model_mae:2.3,baseline_mae:2.1,test_days:14,folds:[{},{}],items:[{date:'2026-10-12',observed_units:4,model_units:5,baseline_units:5}]},
    limitations:'Demo results only describe synthetic data.'};
  records.set(id+':'+source,{report,report_current:true});
  return status(id,source);
}
const fetch=async(url,options={})=>{
  const u=new URL(url,'http://test'),body=options.body?JSON.parse(options.body):null;
  calls.push({url,method:options.method||'GET',body});
  assert.equal(options.cache,'no-store');
  if(u.pathname==='/api/products')return response(products);
  if(u.pathname==='/api/forecast'){
    const data=status(Number(u.searchParams.get('product_id')),u.searchParams.get('source'));
    if(holdRead){holdRead=false;return new Promise(resolve=>{releaseRead=()=>resolve(response(data))})}
    return response(data);
  }
  if(u.pathname==='/api/forecast/train'){
    assert.deepEqual(Object.keys(body).sort(),['product_id','request_id','source']);
    if(missingPackage){missingPackage=false;return response({detail:'ML package is missing. Run pip install -r requirements.txt.'},503)}
    if(failBefore){failBefore=false;throw new Error('Connection lost')}
    if(stall){stall=false;await new Promise(resolve=>{releaseTrain=resolve})}
    const data=receipts.get(body.request_id)||trained(body.product_id,body.source);
    receipts.set(body.request_id,data);
    if(loseResponse){loseResponse=false;throw new Error('Response lost')}
    return response(data);
  }
  if(u.pathname.startsWith('/api/forecast/requests/')){
    const saved=receipts.get(u.pathname.split('/').at(-1));
    return saved?response(saved):response({detail:'Not saved yet'},404);
  }
  throw new Error('Unexpected request '+url);
};
const window={addEventListener(name,fn){(events[name]??=[]).push(fn)}};
window.resupplyFetch=fetch;
const context=vm.createContext({document:{getElementById:id=>el[id],createElement:element,createElementNS:element},
  window,fetch,crypto:{randomUUID},URL,Date,console});
vm.runInContext(js,context);
const tick=async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve))};
const submit=()=>el['forecast-form'].handlers.submit({preventDefault(){}});
const posts=()=>calls.filter(c=>c.method==='POST');
async function source(value){el['forecast-source'].value=value;await el['forecast-source'].handlers.change()}
(async()=>{
  await tick();
  assert.equal(el['forecast-product'].value,'1');
  assert.equal(el['forecast-product'].children[0].textContent,'<b>Blue Pen</b> · PEN');
  assert.equal(el['forecast-train'].disabled,true);
  await source('demo');assert.equal(el['forecast-train'].disabled,false);
  loseResponse=true;await submit();
  assert.equal(el['forecast-results'].hidden,false);
  assert.match(el['forecast-choice'].textContent,/DEMO.*Average forecast selected/);
  assert.match(el['forecast-stock-gap'].textContent,/Demo simulation/);
  assert.equal(el['forecast-rows'].children.length,7);
  assert.equal(el['forecast-test-rows'].children.length,1);
  assert.equal(el['forecast-error'].hidden,true);
  const polys=el['forecast-chart'].children.filter(e=>e.attributes.points);
  assert.equal(polys.length,3);assert.ok(polys.every(e=>!e.attributes.points.includes('NaN')));
  // Unknown write outcome preserves the exact UUID and source for retry.
  failBefore=true;await submit();
  const uncertain=posts().at(-1).body;
  assert.equal(el['forecast-product'].disabled,true);assert.equal(el['forecast-source'].disabled,true);
  assert.equal(el['forecast-train'].textContent,'Retry same training');
  await el['forecast-refresh'].handlers.click();
  assert.match(el['forecast-error'].textContent,/No saved result yet/);
  await submit();assert.deepEqual(posts().at(-1).body,uncertain);
  assert.equal(el['forecast-source'].disabled,false);
  // Double clicks and history events cannot change inputs while training.
  stall=true;const pending=submit();await tick();const count=posts().length;
  assert.equal(el['forecast-train'].disabled,true);await submit();assert.equal(posts().length,count);
  await events['resupply-history-changed'][0]();
  releaseTrain();await pending;assert.equal(el['forecast-source'].disabled,false);
  // Older status requests must not replace a newly selected product/source.
  holdRead=true;const old=source('demo');await tick();
  actualReady=true;await source('actual');releaseRead();await old;
  assert.match(el['forecast-coverage'].textContent,/actual/);
  await submit();assert.match(el['forecast-stock-gap'].textContent,/Stock now: 17.*gap: 5/);
  records.get('1:actual').report_current=false;
  await el['forecast-refresh'].handlers.click();
  assert.equal(el['forecast-results'].hidden,true);assert.match(el['forecast-notice'].textContent,/outdated/);
  missingPackage=true;await submit();
  assert.equal(el['forecast-source'].disabled,false);assert.match(el['forecast-error'].textContent,/pip install/);
  // Receipt status can complete an unknown request without a second POST.
  failBefore=true;await submit();const receiptKey=posts().at(-1).body.request_id;
  receipts.set(receiptKey,trained(1,'actual'));const previous=posts().length;
  await el['forecast-refresh'].handlers.click();
  assert.equal(posts().length,previous);assert.equal(el['forecast-results'].hidden,false);
  window.resupplyPurchasingBusy=true;events['resupply-purchasing-lock'][0]();
  assert.equal(el['forecast-source'].disabled,true);assert.equal(el['forecast-train'].disabled,true);
  await submit();assert.equal(posts().length,previous);
  window.resupplyPurchasingBusy=false;events['resupply-purchasing-lock'][0]();
  assert.equal(el['forecast-source'].disabled,false);
  assert.ok(calls.every(c=>c.url.startsWith('/api/forecast')||c.url==='/api/products'));
  console.log('PASS: forecast UI source labels, chart/table, baseline fallback, lost receipts, same-ID retry, busy locks, stale reads, outdated report and dependency error. No stock/order/payment writes.');
})().catch(error=>{console.error(error);process.exitCode=1});
