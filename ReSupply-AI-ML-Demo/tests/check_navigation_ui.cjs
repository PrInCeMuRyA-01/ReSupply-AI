// Real page controller; mock DOM/history/events. It must never make API writes.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../backend'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const source=fs.readFileSync(path.join(root,'app_ui.js'),'utf8');
const tick=async()=>{for(let i=0;i<3;i++)await new Promise(resolve=>setImmediate(resolve))};
class Event {constructor(type){this.type=type}}
class CustomEvent extends Event {constructor(type,{detail}){super(type);this.detail=detail}}
function harness(mode='demo',view='overview',small=false) {
  let document;
  function element(tag='div'){return {tag,dataset:{},attributes:{},children:[],hidden:false,open:false,textContent:'',href:'',events:{},inert:false,
    append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},
    addEventListener(name,fn){(this.events[name]??=[]).push(fn)},focus(){document.activeElement=this},closest(){return this},
    dispatchEvent(event){for(const fn of this.events[event.type]||[])fn(event)}}}
  const el={};for(const id of html.matchAll(/\bid="([^"]+)"/g))el[id[1]]=element();
  const views=['overview','inventory','sales','history','forecast','suppliers','purchasing','orders','assistant','demo-guide'];
  const screens=views.map(key=>{const item=el['screen-'+key];item.dataset.screen=key;return item});
  const links=[];
  for(const match of html.matchAll(/<a\b[^>]*data-view="([^"]+)"[^>]*>/g)) {
    const id=match[0].match(/id="([^"]+)"/)?.[1],item=id?el[id]:element('a');item.dataset.view=match[1];links.push(item);
  }
  const nav=links.slice(0,11),dialogs=['stock-dialog','sale-dialog','order-dialog'].map(id=>el[id]);
  el['app-sidebar'].querySelectorAll=()=>nav;
  el['app-sidebar'].querySelector=selector=>selector==='a'?nav[0]:nav.find(item=>item.attributes['aria-current']==='page');
  const events={},docEvents={},classNames=new Set(),paths=[],emitted=[];
  const prefix=mode==='demo'?'/demo':'';
  const start=prefix+(view==='overview'?'/':view==='history'?'/sales-history':'/'+view);
  const window={resupplyWorkspace:Object.freeze({mode,prefix}),location:{pathname:start},
    addEventListener(name,fn){(events[name]??=[]).push(fn)},dispatchEvent(event){emitted.push(event);for(const fn of events[event.type]||[])fn(event)},
    scrollTo(){},matchMedia(){return media},fetch(){throw new Error('Navigation/dashboard must not send a request')},
    history:{pushState(state,_,url){paths.push(['push',url]);window.location.pathname=url},replaceState(state,_,url){paths.push(['replace',url]);window.location.pathname=url}}};
  const media={matches:small,addEventListener(name,fn){this.onchange=fn}};
  document={body:{dataset:{startView:view},classList:{add(c){classNames.add(c)},remove(c){classNames.delete(c)}}},activeElement:null,title:'',
    getElementById:id=>el[id],createElement:element,addEventListener(name,fn){(docEvents[name]??=[]).push(fn)},
    querySelectorAll(selector){return selector==='[data-screen]'?screens:selector==='[data-view]'?links:selector==='dialog'?dialogs:[]}};
  const context=vm.createContext({document,window,Event,CustomEvent,Intl,Date,console});
  vm.runInContext(source,context);
  const emit=(type,detail)=>window.dispatchEvent(detail===undefined?new Event(type):new CustomEvent(type,{detail}));
  const data=(section,data,status='ready')=>emit('resupply-dashboard-data',{section,data,status});
  return {el,window,document,paths,media,emitted,nav,links,screens,data,emit,classNames,
    click(view,modified=false){const link=links.find(item=>item.dataset.view===view);const event={target:link,button:0,ctrlKey:modified,preventDefault(){this.prevented=true}};
      for(const fn of docEvents.click||[])fn(event);return event},
    key(key,shiftKey=false){const event={key,shiftKey,preventDefault(){this.prevented=true}};for(const fn of docEvents.keydown||[])fn(event);return event},
    visible(){return screens.filter(item=>!item.hidden).map(item=>item.dataset.screen)}};
}
(async()=>{
  const h=harness();assert.deepEqual(h.visible(),['overview']);assert.match(h.document.title,/DEMO.*Dashboard/);
  for(const view of ['inventory','sales','history','forecast','suppliers','purchasing','orders','assistant','demo-guide','overview']) {
    assert.equal(h.click(view).prevented,true);assert.deepEqual(h.visible(),[view]);
    assert.ok(h.window.location.pathname.startsWith('/demo/'));
    assert.equal(h.nav.filter(item=>item.attributes['aria-current']==='page').length,view==='overview'?2:1);
  }
  const before=h.paths.length;h.click('inventory',true);assert.equal(h.paths.length,before);
  h.window.resupplyNavigate('inventory');h.el['name']??={};h.el['name'].value='Keep unsaved text';
  h.window.resupplyNavigate('forecast');h.window.resupplyNavigate('inventory');assert.equal(h.el['name'].value,'Keep unsaved text');
  h.window.location.pathname='/demo/orders';h.emit('popstate');assert.deepEqual(h.visible(),['orders']);
  h.el['order-dialog'].open=true;
  assert.equal(h.window.resupplyNavigate('inventory'),false);assert.deepEqual(h.visible(),['orders']);
  h.window.location.pathname='/demo/assistant';h.emit('popstate');assert.equal(h.window.location.pathname,'/demo/orders');
  assert.match(h.el['navigation-note'].textContent,/Close the current dialog/);h.el['order-dialog'].open=false;
  const e={section:'products',data:[{name:'<img src=x>',stock:12},{name:'Rice',stock:24}],status:'ready'};
  h.emit('resupply-dashboard-data',e);assert.equal(h.el['dash-products'].textContent,'2');assert.match(h.el['dash-products-note'].textContent,/36 units/);
  h.data('restock',{suggested_products:1,shop_date:'2026-10-14',method:'reviewed_forecast_mixed',items:[
    {name:'<b>Blue Pen</b>',sku:'PEN',stock:12,suggested_quantity:40,status:'delivery_risk'},{name:'Unknown',suggested_quantity:null}]});
  assert.equal(h.el['dash-restock'].textContent,'1');assert.match(h.el['dash-restock-note'].textContent,/1 product.*need demand/);
  assert.equal(h.el['dash-attention'].children[0].children[0].children[0].textContent,'<b>Blue Pen</b>');
  assert.equal(h.el['nav-restock-count'].hidden,false);
  h.data('purchase',{planned_cost:'49.50',budget:'100.00'});assert.equal(h.el['dash-plan'].textContent,'$49.50');
  h.data('orders',[
    {number:'DEMO-1',units:20,grand_total:'30.00',status:'approved',payment:{state:'authorized'}},
    {number:'DEMO-2',units:30,grand_total:'49.50',status:'approved',payment:{state:'captured'}},
    {number:'DEMO-3',units:12,grand_total:'20.00',status:'received',payment:{state:'captured'}}]);
  assert.equal(h.el['dash-incoming'].textContent,'1');
  assert.equal(h.el['dash-orders'].children[0].children[1].textContent,'Hold · not captured');
  assert.equal(h.el['dash-orders'].children[2].children[1].textContent,'Stock received');
  h.emit('resupply-demo-state',{prepared:true,products:[{sample:true,current:true,active_run_id:1}],
    focus_order:{status:'approved',payment:{state:'authorized'}}});assert.match(h.el['next-step-title'].textContent,/funds are on hold/);
  h.data('purchase',null,'error');assert.equal(h.el['dash-plan'].textContent,'—');assert.match(h.el['dash-plan-note'].textContent,/unavailable/);
  h.data('orders',null,'error');assert.equal(h.el['dash-incoming'].textContent,'—');assert.match(h.el['dash-orders'].children[0].textContent,/could not load/);
  h.data('restock',null,'loading');assert.equal(h.el['dash-restock'].textContent,'—');assert.equal(h.el['nav-restock-count'].hidden,true);
  const phone=harness('real','inventory',true);assert.equal(phone.el['app-sidebar'].inert,true);
  phone.el['menu-toggle'].dispatchEvent(new Event('click'));assert.equal(phone.el['nav-backdrop'].hidden,false);
  assert.equal(phone.el['app-sidebar'].inert,false);assert.equal(phone.el['menu-toggle'].attributes['aria-expanded'],'true');
  phone.document.activeElement=phone.nav.at(-1);assert.equal(phone.key('Tab').prevented,true);assert.equal(phone.document.activeElement,phone.el['menu-toggle']);
  assert.equal(phone.key('Escape').prevented,true);assert.equal(phone.el['app-sidebar'].inert,true);assert.equal(phone.el['nav-backdrop'].hidden,true);
  phone.el['menu-toggle'].dispatchEvent(new Event('click'));phone.click('orders');assert.equal(phone.el['nav-backdrop'].hidden,true);
  assert.equal(phone.window.location.pathname,'/orders');assert.deepEqual(phone.visible(),['orders']);
  phone.media.matches=false;phone.media.onchange();assert.equal(phone.el['app-sidebar'].inert,false);
  const direct=harness('demo','history');assert.deepEqual(direct.visible(),['history']);assert.equal(direct.paths.length,0);
  assert.ok(h.emitted.some(event=>event.type==='resupply-view-changed'&&event.detail.previous==='assistant'));
  await tick();console.log('PASS: ten scoped pages, direct loads, history, unsaved forms, dialog/payment guards, mobile focus/Escape, honest dashboard data/error states, XSS-safe names and zero navigation requests.');
})().catch(error=>{console.error(error);process.exit(1)});
