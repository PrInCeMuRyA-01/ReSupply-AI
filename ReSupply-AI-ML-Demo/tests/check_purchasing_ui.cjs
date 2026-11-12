const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const root=path.resolve(__dirname,'../backend');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8'),js=fs.readFileSync(path.join(root,'forecast_purchasing_ui.js'),'utf8');
function element(){return {value:'',textContent:'',children:[],handlers:{},disabled:false,hidden:false,
  append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},setAttribute(){},reportValidity(){return true},
  addEventListener(name,fn){this.handlers[name]=fn}};}
const el={};for(const m of html.matchAll(/\bid="([^"]+)"/g))el[m[1]]=element();
el['forecast-product'].value='1';el['forecast-source'].value='demo';
for(const [id,value] of Object.entries({'lead-time':'3','coverage-days':'7','buffer-days':'2','purchase-budget':'20.00','impact-demo-stock':'20'}))el[id].value=value;
class Event{constructor(type){this.type=type}}
const listeners={},emitted=[],window={addEventListener(name,fn){(listeners[name]??=[]).push(fn)},dispatchEvent(event){emitted.push(event.type);for(const fn of listeners[event.type]||[])fn(event)}};
const emit=(type,detail)=>window.dispatchEvent({type,detail});
const calls=[],receipts=new Map();let revision=0,reviewed=null,arrival=null,etaRevision=0;
let loseOnce=false,failBefore=false,stall=false,releaseWrite,staleWrite=false,holdPreview=false,releasePreview;
const json=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>JSON.parse(JSON.stringify(data))});
function forecast(source='demo'){return {product:{id:1,sku:'PEN'},source,run_id:10,report_current:true,
  planning:{review_revision:revision,reviewed_run_id:reviewed,active_run_id:reviewed,can_use:source==='actual',message:reviewed?'Purchasing uses reviewed actual forecast #10.':'Purchasing uses sales average.'}};}
function result(demo){return {product_id:1,run_id:10,demo,stock:demo?20:17,demand_units:'50',suggested_quantity:30,budget_quantity:20,
  budget_cost:'20.00',lead_time_days:3,coverage_days:7,buffer_days:2,incoming_units:0,delivery_risk:true,message:demo?'DEMO simulation: cannot create real purchase drafts.':'Single-product preview only.',
  daily:[{date:'2026-10-14',demand_units:'5',incoming_units:0,balance_before_arrival:'15'}]};}
const fetch=async(url,options={})=>{
  const u=new URL(url,'http://test'),body=options.body?JSON.parse(options.body):null;
  calls.push({url,body,method:options.method||'GET'});assert.equal(options.cache,'no-store');
  if(u.pathname==='/api/incoming-stock')return json({shop_date:'2026-10-14',message:'Captured only.',items:[{
    order_id:1,number:'RS-000001',order_version:2,arrival_date:arrival,revision:etaRevision,status:arrival?'expected':'no_date',items:[{name:'<b>Pen</b>',sku:'PEN',quantity:10}]}]});
  if(u.pathname==='/api/forecast-planning/preview'){
    const r=result(el['forecast-source'].value==='demo');
    assert.equal(u.searchParams.get('budget'),'20.00');
    if(holdPreview){holdPreview=false;return new Promise(resolve=>releasePreview=()=>resolve(json(r)))}
    return json(r);
  }
  if(u.pathname.startsWith('/api/forecast-planning/requests/')){
    const saved=receipts.get(u.pathname.split('/').at(-1));return saved?json(saved):json({detail:'Not saved yet'},404);
  }
  if(u.pathname==='/api/forecast-planning/review'||u.pathname==='/api/incoming-stock/1'){
    if(failBefore){failBefore=false;throw new Error('Connection lost')}
    if(stall){stall=false;await new Promise(resolve=>releaseWrite=resolve)}
    if(staleWrite){staleWrite=false;return json({detail:'Planning review changed. Refresh first.'},409)}
    if(receipts.has(body.request_id))return json(receipts.get(body.request_id));
    let saved;
    if(u.pathname.endsWith('/review')){
      assert.equal(body.expected_revision,revision);assert.equal(body.product_id,1);
      if(body.action==='use')assert.equal(el['forecast-source'].value,'actual');
      reviewed=body.action==='use'?10:null;revision++;
      saved={message:'Planning review saved.',revision,run_id:reviewed};
    }else{
      assert.equal(body.expected_revision,etaRevision);assert.equal(body.expected_order_version,2);
      arrival=body.arrival_date;etaRevision++;saved={message:'Expected delivery saved.',revision:etaRevision};
    }
    receipts.set(body.request_id,saved);
    if(loseOnce){loseOnce=false;throw new Error('Lost response')}
    return json(saved);
  }
  throw new Error('Unexpected request '+url);
};
listeners['resupply-forecast-refresh']=[()=>emit('resupply-forecast-view-changed',forecast(el['forecast-source'].value))];
window.resupplyFetch=fetch;
const ctx=vm.createContext({document:{getElementById:id=>el[id],createElement:element},window,fetch,Event,Date,URLSearchParams,crypto:{randomUUID},console});
vm.runInContext(js,ctx);
const tick=async()=>{for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve))};
const writes=()=>calls.filter(c=>c.method!=='GET');
async function choose(source){el['forecast-source'].value=source;el['forecast-source'].handlers.change();emit('resupply-forecast-view-changed',forecast(source));await tick()}
(async()=>{
  await tick();
  assert.equal(el['impact-demo-stock-label'].hidden,false);
  assert.equal(el['impact-use'].hidden,true);
  await el['impact-preview'].handlers.click();
  assert.match(el['impact-summary'].textContent,/DEMO.*Budget can cover: 20/);
  assert.equal(el['impact-use'].hidden,true);assert.equal(writes().length,0);
  assert.equal(el['impact-rows'].children.length,1);
  let row=el['incoming-rows'].children[0];
  assert.equal(row.children[1].textContent,'<b>Pen</b> (PEN): 10');
  assert.equal(row.children[2].children[0].min,'2026-10-14');
  // A late demo response cannot activate purchasing after selecting actual.
  holdPreview=true;const oldPreview=el['impact-preview'].handlers.click();await tick();
  await choose('actual');releasePreview();await oldPreview;
  assert.equal(el['impact-result'].hidden,true);
  await el['impact-preview'].handlers.click();loseOnce=true;
  await el['impact-use'].handlers.click();
  assert.equal(reviewed,10);assert.equal(el['purchasing-error'].hidden,true);
  assert.ok(emitted.includes('resupply-planning-changed'));
  assert.equal(window.resupplyPurchasingBusy,false);
  // Unknown preference outcome locks the values and keeps the same request ID.
  failBefore=true;await el['impact-average'].handlers.click();
  const pending=writes().at(-1);assert.equal(window.resupplyPurchasingBusy,true);
  assert.equal(el['purchasing-retry'].hidden,false);
  await el['purchasing-retry'].handlers.click();
  assert.deepEqual(writes().at(-1),pending);assert.equal(reviewed,null);
  // Saved incoming dates do not receive goods or send any payment request.
  row=el['incoming-rows'].children[0];row.children[2].children[0].value='2026-10-16';loseOnce=true;
  await row.children[3].children[0].handlers.click();assert.equal(arrival,'2026-10-16');
  assert.equal(el['purchasing-error'].hidden,true);
  row=el['incoming-rows'].children[0];stall=true;
  const saving=row.children[3].children[1].handlers.click();await tick();const count=writes().length;
  await row.children[3].children[1].handlers.click();assert.equal(writes().length,count);
  assert.equal(row.children[2].children[0].disabled,true);
  releaseWrite();await saving;assert.equal(arrival,null);
  await el['impact-preview'].handlers.click();staleWrite=true;
  await el['impact-use'].handlers.click();assert.match(el['purchasing-error'].textContent,/review changed/);
  assert.equal(window.resupplyPurchasingBusy,false);
  assert.ok(calls.every(c=>c.url.startsWith('/api/forecast-planning')||c.url.startsWith('/api/incoming-stock')));
  console.log('PASS: isolated demo preview, explicit actual review, stale response protection, receipt recovery, exact retry locks, date save/clear, double-click guard and no order/payment/receipt writes.');
})().catch(error=>{console.error(error);process.exitCode=1});
