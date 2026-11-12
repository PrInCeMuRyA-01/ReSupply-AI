const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../backend'),html=fs.readFileSync(path.join(root,'index.html'),'utf8'),js=fs.readFileSync(path.join(root,'voice_assistant_ui.js'),'utf8');
function element(){return {children:[],handlers:{},value:'',textContent:'',disabled:false,hidden:false,
  append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},setAttribute(){},focus(){},scrollIntoView(){},reportValidity(){return true},
  addEventListener(name,fn){this.handlers[name]=fn},dispatchEvent(event){return this.handlers[event.type]?.(event)}};}
class Event{constructor(type,options={}){this.type=type;Object.assign(this,options)}}
class CustomEvent extends Event{}
const tick=async()=>{for(let i=0;i<10;i++)await new Promise(resolve=>setImmediate(resolve))};
function harness(supported=true){
  const el={};for(const m of html.matchAll(/\bid="([^"]+)"/g))el[m[1]]=element();
  el['voice-language'].value='en-IN';el['voice-source'].value='actual';
  for(const [id,value] of Object.entries({'lead-time':'3','coverage-days':'7','buffer-days':'2'}))el[id].value=value;
  const events={},docEvents={},calls=[],instances=[],timers=new Map();let timer=0,hold=null,release=null,nextError=null,throwStart=false,endOnStop=true;
  const window={addEventListener(name,fn){(events[name]??=[]).push(fn)},dispatchEvent(e){for(const fn of events[e.type]||[])fn(e)}};
  class Recognition{
    constructor(){instances.push(this)}
    start(){if(throwStart){throwStart=false;throw Error('Start blocked')}this.onstart?.();if(nextError){const e=nextError;nextError=null;this.onerror({error:e})}}
    stop(){this.stopped=true;if(endOnStop)this.onend?.()}
    abort(){this.aborted=true;this.onend?.()}
    result(text){this.onresult({results:[[{transcript:text}]]})}
  }
  if(supported)window.webkitSpeechRecognition=Recognition;
  const response=data=>({ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(data))});
  const fetch=async(url,options={})=>{
    calls.push({url,options,body:options.body?JSON.parse(options.body):null});assert.equal(options.cache,'no-store');
    if(url==='/api/products')return response([{id:1,sku:'PEN',name:'<b>Pen</b>'},{id:2,sku:'PEN-BLUE',name:'Blue Pen'}]);
    assert.equal(url,'/api/assistant/preview');assert.equal(options.method,'POST');
    const body=JSON.parse(options.body);let data;
    if(body.text.startsWith('50'))data={status:'ready',intent:'budget',message:'USD budget $50.00',items:[],plan:{budget:'50.00',planned_units:10,planned_cost:'9.50',remaining_budget:'40.50',lead_time_days:3,coverage_days:7,buffer_days:2,items:[{name:'Pen',sku:'PEN',suggested_quantity:10,planned_quantity:10,line_cost:'9.50',forecast_run_id:null}]}};
    else if(body.text.includes('Forecast'))data={status:'ready',intent:'forecast',message:'DEMO synthetic forecast',source:'demo',product:{id:1},selected_method:'random_forest',model_mae:1,baseline_mae:2,items:[{date:'2026-10-15',selected_units:5,model_units:5,baseline_units:7}]};
    else if(body.text==='unknown stock')data={status:'needs_product',intent:'stock',message:'Choose a product.',items:[{id:1,sku:'PEN',name:'<b>Pen</b>'}]};
    else data={status:'ready',intent:'stock',message:'Pen: 17 units in stock.',product:{id:1,stock:17},items:[]};
    if(hold){hold=false;return new Promise(resolve=>release=()=>resolve(response(data)))}return response(data);
  };
  const document={hidden:false,getElementById:id=>el[id],createElement:element,addEventListener(name,fn){docEvents[name]=fn}};
  window.resupplyFetch=fetch;
const context=vm.createContext({document,window,fetch,Event,CustomEvent,Date,Error,
    setTimeout(fn,delay){const id=++timer;timers.set(id,{fn,delay});return id},clearTimeout(id){timers.delete(id)}});
  vm.runInContext(js,context);
  return {el,window,document,docEvents,calls,instances,timers,
    submit:()=>el['voice-form'].handlers.submit({preventDefault(){}}),start:()=>el['voice-start'].handlers.click(),
    setError(error){nextError=error},startThrows(){throwStart=true},stallStop(){endOnStop=false},
    hold(){hold=true},release(){release()},emit(type){window.dispatchEvent(new Event(type))}};
}
(async()=>{
  const h=harness();await tick();
  assert.equal(h.instances.length,0);assert.equal(h.el['voice-start'].disabled,false);
  assert.equal(h.el['voice-product'].children[1].textContent,'<b>Pen</b> · PEN');
  h.el['voice-text'].value='Previous typed command';h.start();const first=h.instances.at(-1);
  assert.equal(first.lang,'en-IN');assert.equal(h.el['voice-text'].disabled,true);
  first.result('Pen ka stock');first.result('Pen ka stock kitna hai');
  assert.equal(h.el['voice-text'].value,'Pen ka stock kitna hai');assert.equal(h.calls.filter(c=>c.url.includes('/preview')).length,0);
  h.el['voice-stop'].handlers.click();assert.equal(h.el['voice-text'].disabled,false);
  assert.equal(h.timers.size,0);await h.submit();assert.match(h.el['voice-answer'].textContent,/17 units/);
  // Cancel restores prior text and ignores old callbacks after a new session.
  h.el['voice-text'].value='Keep this';h.start();const cancelled=h.instances.at(-1);cancelled.result('Wrong text');
  h.el['voice-cancel'].handlers.click();assert.equal(h.el['voice-text'].value,'Keep this');
  cancelled.result('Late overwrite');assert.equal(h.el['voice-text'].value,'Keep this');
  h.start();const newest=h.instances.at(-1);cancelled.onend();assert.equal(h.el['voice-text'].disabled,true);
  newest.result('Stock PEN');newest.onend();assert.equal(h.el['voice-text'].value,'Stock PEN');
  h.setError('not-allowed');h.start();assert.match(h.el['voice-error'].textContent,/permission was denied/);assert.equal(h.el['voice-text'].disabled,false);
  h.setError('network');h.start();assert.match(h.el['voice-error'].textContent,/working connection/);
  h.startThrows();h.start();assert.match(h.el['voice-error'].textContent,/could not start/);
  h.el['voice-language'].value='hi-IN';h.start();assert.equal(h.instances.at(-1).lang,'hi-IN');
  h.instances.at(-1).result('पेन का स्टॉक कितना है');h.document.hidden=true;h.docEvents.visibilitychange();assert.equal(h.el['voice-text'].disabled,false);
  // A stalled speech service is released by the bounded finish timeout.
  h.document.hidden=false;h.stallStop();h.start();h.instances.at(-1).result('Stock PEN');h.el['voice-stop'].handlers.click();
  const timeout=[...h.timers.values()].find(t=>t.delay===5000);assert.ok(timeout);timeout.fn();assert.equal(h.el['voice-text'].disabled,false);
  // A stale preview is never displayed after the shop data refreshes.
  h.el['voice-text'].value='Stock PEN';h.hold();const pending=h.submit();await tick();
  assert.equal(h.el['voice-preview'].disabled,true);h.emit('resupply-planning-changed');h.release();await pending;
  assert.equal(h.el['voice-result'].hidden,true);assert.match(h.el['voice-error'].textContent,/Preview.*again/);
  h.el['voice-text'].value='unknown stock';await h.submit();const choice=h.el['voice-choices'].children[0];
  assert.equal(choice.textContent,'<b>Pen</b> · PEN');choice.handlers.click();await tick();assert.equal(h.el['voice-text'].value,'Stock PEN');
  h.el['voice-text'].value='50 dollar budget ka plan banao';await h.submit();
  assert.match(h.el['voice-note'].textContent,/remaining \$40.50/);
  let opened=null;h.window.addEventListener('resupply-voice-budget',e=>{opened=e.detail.plan;e.detail.applied=true});
  h.el['voice-open'].handlers.click();assert.equal(opened.budget,'50.00');
  h.el['voice-text'].value='Forecast PEN';h.el['voice-source'].value='demo';await h.submit();
  h.el['forecast-product'].disabled=true;h.el['voice-open'].handlers.click();assert.match(h.el['voice-error'].textContent,/Finish the current/);
  h.el['forecast-product'].disabled=false;h.el['voice-open'].handlers.click();assert.equal(h.el['forecast-source'].value,'demo');
  assert.ok(h.calls.every(c=>c.url==='/api/products'||c.url==='/api/assistant/preview'));
  h.el['voice-text'].value='Keep this typed command';h.start();const leaving=h.instances.at(-1);
  leaving.result('Temporary speech');
  h.window.dispatchEvent({type:'resupply-view-changed',detail:{previous:'assistant',view:'inventory'}});
  assert.equal(leaving.aborted,true);assert.equal(h.el['voice-text'].value,'Keep this typed command');
  assert.equal(h.el['voice-text'].disabled,false);
  const fallback=harness(false);await tick();assert.equal(fallback.el['voice-start'].disabled,true);
  fallback.el['voice-text'].value='Stock PEN';await fallback.submit();assert.match(fallback.el['voice-answer'].textContent,/17 units/);
  console.log('PASS: mic lifecycle, editable transcript, no automatic command, cancel/late callbacks, permission/network/start errors, language selection, hidden-page abort, timeouts, stale previews, product choice, explicit planner opening and typed fallback.');
})().catch(error=>{console.error(error);process.exitCode=1});
