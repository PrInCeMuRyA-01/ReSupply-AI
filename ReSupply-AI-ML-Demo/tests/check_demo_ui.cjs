// Real workspace/demo/purchasing scripts, mock DOM/network. No live checkout.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const root=path.resolve(__dirname,'../backend'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const source=name=>fs.readFileSync(path.join(root,name),'utf8');
const tick=async()=>{for(let i=0;i<14;i++)await new Promise(resolve=>setImmediate(resolve))};
function element(){return {value:'',textContent:'',hidden:false,disabled:false,children:[],events:{},options:[],dataset:{},scrolled:false,
  append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},setAttribute(){},reportValidity(){return true},
  addEventListener(name,fn){(this.events[name]??=[]).push(fn)},dispatchEvent(event){for(const fn of this.events[event.type]||[])fn(event)},
  querySelectorAll(type){return this.children.flatMap(c=>[...(c.tag===type?[c]:[]),...c.querySelectorAll(type)])},
  scrollIntoView(){this.scrolled=true},async click(){for(const fn of this.events.click||[])await fn({preventDefault(){}})}};}
class Event{constructor(type){this.type=type}}
class CustomEvent extends Event{constructor(type,{detail}){super(type);this.detail=detail}}
function harness(mode='demo') {
  const el={};for(const id of html.matchAll(/\bid="([^"]+)"/g))el[id[1]]=element();
  for(const id of ['forecast-source','voice-source','history-source']){el[id].value='actual';el[id].options=[{value:'actual',disabled:false},{value:'demo',disabled:false}]}
  for(const [id,value] of Object.entries({'lead-time':'3','coverage-days':'7','buffer-days':'2','purchase-budget':'100.00','impact-demo-stock':'20'}))el[id].value=value;
  el['forecast-product'].value='1';el['forecast-product'].options=[1,2,3].map(id=>({value:String(id)}));
  const events={},calls=[],receipts=new Map(),trains=new Map();
  let prepared=false,loseSetup=false,loseTrain=false,failTrain=false,invalidTrain=false,holdSetup=false,releaseSetup=null;
  let focus=null,allowPlan=true;const reviews=new Map();
  const products=[{id:1,sku:'PEN-BLUE',name:'<b>Blue Pen</b>',stock:12},{id:2,sku:'NOTEBOOK-A5',name:'A5 Notebook',stock:10},{id:3,sku:'RICE-1KG',name:'Rice 1 kg',stock:24}];
  const window={addEventListener(name,fn){(events[name]??=[]).push(fn)},dispatchEvent(event){for(const fn of events[event.type]||[])fn(event)}};
  const emit=(name,detail)=>window.dispatchEvent(detail===undefined?new Event(name):new CustomEvent(name,{detail}));
  const data=()=>({workspace:'demo',synthetic:true,prepared,shop_date:'2026-10-14',focus_order:focus,
    products:prepared?products.map(p=>({...p,sample:true,ready:true,current:trains.has(p.id),run_id:p.id,
      active_run_id:reviews.get(p.id)||null,selected_method:p.id===3?'seven_day_mean':'random_forest',training_days:60})):[],
    counts:{products:prepared?3:0,suppliers:prepared?2:0,daily_sales_history:prepared?180:0},message:'Synthetic shop only.'});
  const view=()=>({product:products.find(p=>String(p.id)===el['forecast-product'].value),source:el['forecast-source'].value,
    run_id:Number(el['forecast-product'].value),report_current:trains.has(Number(el['forecast-product'].value)),
    planning:{can_use:true,review_revision:reviews.has(Number(el['forecast-product'].value))?1:0,
      reviewed_run_id:reviews.get(Number(el['forecast-product'].value))||null,message:'Demo synthetic planning.'}});
  const result=(value,status=200)=>({ok:status>=200&&status<300,status,json:async()=>structuredClone(value)});
  window.fetch=async(url,options={})=>{
    assert.equal(options.cache,'no-store');
    if(mode==='demo')assert.ok(url.startsWith('/demo/api/'),'Cross-shop URL: '+url);
    else assert.ok(url.startsWith('/api/'));
    const u=new URL(url,'http://test'),route=u.pathname.replace(/^\/demo/,''),body=options.body?JSON.parse(options.body):null;
    calls.push({url,route,method:options.method||'GET',body});
    if(route==='/api/products')return result(products);
    if(route==='/api/demo-shop')return result(data());
    if(route==='/api/demo-shop/setup') {
      prepared=true;
      if(holdSetup){holdSetup=false;await new Promise(resolve=>releaseSetup=resolve)}
      if(loseSetup){loseSetup=false;throw new TypeError('Setup response lost')}
      return result({added_history_rows:180});
    }
    if(route==='/api/forecast/train') {
      if(invalidTrain){invalidTrain=false;return result({detail:'Need confirmed history.'},422)}
      if(failTrain){failTrain=false;throw new TypeError('Connection lost before fit')}
      assert.equal(body.source,'demo');
      const report={report_current:true,run_id:body.product_id};trains.set(body.product_id,report);receipts.set(body.request_id,report);
      if(loseTrain){loseTrain=false;throw new TypeError('Train response lost')}
      return result(report);
    }
    if(route.startsWith('/api/forecast/requests/'))return receipts.has(route.split('/').at(-1))?result(receipts.get(route.split('/').at(-1))):result({detail:'Not saved'},404);
    if(route==='/api/purchase-plan')return result({budget:'100.00',lead_time_days:3,coverage_days:7,buffer_days:2,planned_units:30});
    if(route==='/api/incoming-stock')return result({shop_date:'2026-10-14',items:[],message:'Captured only.'});
    if(route==='/api/forecast-planning/preview')return result({product_id:Number(u.searchParams.get('product_id')),run_id:Number(u.searchParams.get('run_id')),
      demo:true,isolated_demo_shop:true,stock:12,unit_cost:'0.60',demand_units:'50',suggested_quantity:38,budget_quantity:38,budget_cost:'22.80',
      lead_time_days:2,coverage_days:7,buffer_days:2,incoming_units:0,delivery_risk:true,message:'Demo shop with selected quote.',daily:[]});
    if(route==='/api/forecast-planning/review') {
      assert.equal(body.action,'use');assert.equal(body.expected_run_id,body.product_id);
      reviews.set(body.product_id,body.expected_run_id);return result({message:'Demo forecast reviewed.'});
    }
    throw new Error('Unexpected API action '+route);
  };
  const document={body:{dataset:{workspace:mode,apiPrefix:mode==='demo'?'/demo':''}},getElementById:id=>el[id],
    createElement(tag){const item=element();item.tag=tag;return item}};
  const context=vm.createContext({document,window,Event,CustomEvent,URL,URLSearchParams,Date,crypto:{randomUUID},console});
  vm.runInContext(source('shop_workspace_ui.js'),context);
  vm.runInContext(source('demo_shop_ui.js'),context);
  window.addEventListener('resupply-demo-budget',event=>{event.detail.applied=allowPlan});
  el['forecast-product'].addEventListener('change',()=>emit('resupply-forecast-view-changed',view()));
  window.addEventListener('resupply-forecast-refresh',()=>emit('resupply-forecast-view-changed',view()));
  return {el,window,document,calls,trains,reviews,emit,view,
    loseSetup(){loseSetup=true},loseTrain(){loseTrain=true},failTrain(){failTrain=true},invalidTrain(){invalidTrain=true},
    holdSetup(){holdSetup=true},releaseSetup(){releaseSetup()},focus(order){focus=order},allowPlan(value){allowPlan=value},
    purchasing(){vm.runInContext(source('forecast_purchasing_ui.js'),context)}};
}
(async()=>{
  const h=harness();await tick();
  assert.equal(h.el['forecast-source'].value,'demo');assert.equal(h.el['history-source'].options[0].disabled,true);
  assert.equal(h.el['workspace-name'].textContent,'DEMO · synthetic shop');assert.equal(h.el['workspace-link'].href,'/');
  h.document.body.dataset.workspace='real';h.document.body.dataset.apiPrefix='';
  await h.window.resupplyFetch('/api/products');
  assert.equal(h.calls.at(-1).url,'/demo/api/products');
  assert.equal(h.window.resupplyUrl('/api/sales-history/export?product_id=1'),'/demo/api/sales-history/export?product_id=1');
  assert.throws(()=>h.window.resupplyUrl('/demo/api/orders'));assert.throws(()=>h.window.resupplyUrl('/api/../orders'));
  h.holdSetup();const pending=h.el['demo-prepare'].click();await tick();
  assert.equal(h.el['demo-prepare'].disabled,true);assert.equal(h.el['demo-plan'].disabled,true);
  await h.el['demo-prepare'].click();assert.equal(h.calls.filter(c=>c.route.endsWith('/setup')).length,1);
  h.releaseSetup();await pending;await tick();
  const trains=h.calls.filter(c=>c.route==='/api/forecast/train');
  assert.equal(trains.length,3);assert.equal(new Set(trains.map(c=>c.body.request_id)).size,3);
  assert.match(h.el['demo-summary'].textContent,/3\/3 current forecasts.*0\/3 reviewed/);
  assert.equal(h.el['demo-models'].children[0].children[0].textContent.startsWith('<b>Blue Pen</b>'),true);
  assert.match(h.el['demo-feedback'].textContent,/Review each forecast/);
  await h.el['demo-prepare'].click();assert.equal(h.calls.filter(c=>c.route==='/api/forecast/train').length,3);
  assert.ok(h.calls.filter(c=>c.method!=='GET').every(c=>['/api/demo-shop/setup','/api/forecast/train'].includes(c.route)));

  h.purchasing();await tick();
  assert.equal(h.el['impact-demo-stock-label'].hidden,true);assert.equal(h.el['impact-use'].hidden,false);
  await h.el['impact-preview'].click();assert.match(h.el['impact-summary'].textContent,/DEMO/);
  assert.equal(h.el['impact-use'].disabled,false);await h.el['impact-use'].click();await tick();
  assert.equal(h.reviews.get(1),1);assert.match(h.el['demo-summary'].textContent,/1\/3 reviewed/);
  h.el['demo-models'].children[1].children[1].dispatchEvent(new Event('click'));await tick();
  assert.equal(h.el['forecast-product'].value,'2');assert.equal(h.el['forecast-source'].value,'demo');
  assert.equal(h.el['forecast-title'].scrolled,true);
  await h.el['demo-plan'].click();assert.equal(h.calls.at(-1).route,'/api/purchase-plan');
  assert.match(h.el['demo-feedback'].textContent,/Fresh \$100/);
  h.allowPlan(false);await h.el['demo-plan'].click();assert.match(h.el['demo-error'].textContent,/pending order\/payment/);
  h.focus({number:'DEMO-run-000001',status:'approved',payment:{state:'authorized'}});h.emit('resupply-orders-changed');await tick();
  assert.match(h.el['demo-progress'].children[3].children[0].textContent,/○.*authorized/);
  h.focus({number:'DEMO-run-000001',status:'received',payment:{state:'captured'},receipt:{units:38}});
  h.emit('resupply-orders-changed');await tick();
  assert.match(h.el['demo-progress'].children[4].children[0].textContent,/✓.*38 units added once/);
  assert.ok(!h.calls.some(c=>/\/orders|\/paypal|\/receive/.test(c.route)));
  let routed=null;h.window.resupplyNavigate=page=>{routed=page;return true};
  h.emit('resupply-forecast-view-changed',h.view());
  h.el['purchase-budget'].checkValidity=()=>false;
  const previews=h.calls.filter(c=>c.route==='/api/forecast-planning/preview').length;
  await h.el['impact-preview'].click();assert.equal(routed,'purchasing');
  assert.equal(h.calls.filter(c=>c.route==='/api/forecast-planning/preview').length,previews);

  const lost=harness();await tick();lost.loseSetup();await lost.el['demo-prepare'].click();
  assert.equal(lost.trains.size,0);await lost.el['demo-prepare'].click();assert.equal(lost.trains.size,3);
  const recover=harness();await tick();recover.loseTrain();await recover.el['demo-prepare'].click();
  assert.equal(recover.trains.size,3);assert.ok(recover.calls.some(c=>c.route.startsWith('/api/forecast/requests/')));
  const retry=harness();await tick();retry.failTrain();await retry.el['demo-prepare'].click();
  assert.match(retry.el['demo-error'].textContent,/same request ID/);
  const key=retry.calls.find(c=>c.route==='/api/forecast/train').body.request_id;
  await retry.el['demo-prepare'].click();
  assert.equal(retry.calls.filter(c=>c.route==='/api/forecast/train')[1].body.request_id,key);
  const real=harness('real');await tick();assert.equal(real.calls.length,0);
  await real.window.resupplyFetch('/api/products');assert.equal(real.calls.at(-1).url,'/api/products');
  for(const file of ['index.html','sales_history_ui.js','demand_forecast_ui.js','forecast_purchasing_ui.js','voice_assistant_ui.js']) {
    assert.equal(/\bfetch\s*\(/.test(source(file)),false,'Unscoped fetch in '+file);
  }
  assert.ok(html.indexOf('/assets/shop-workspace.js')<html.indexOf('<script>'));
  console.log('PASS: immutable per-tab API scope, defaults/CSV URLs, retry-safe prepare, real ML request recovery, explicit demo review, budget handoff, truthful progress, payment boundaries and existing-shop fallback.');
})().catch(error=>{console.error(error);process.exit(1)});
