const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const html=fs.readFileSync(require('node:path').resolve(__dirname,'../backend/index.html'),'utf8');
const js=fs.readFileSync(require('node:path').resolve(__dirname,'../backend/sales_history_ui.js'),'utf8');
new vm.Script(js);
function elem(){return {children:[],handlers:{},value:'',textContent:'',disabled:false,hidden:false,checked:false,
  append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},
  addEventListener(name,handler){this.handlers[name]=handler},reportValidity(){return true}};}
const elements={};for(const match of html.matchAll(/\bid="([^"]+)"/g))elements[match[1]]=elem();
elements['history-range'].value='90';
const products=[{id:1,sku:'PEN',name:'<b>Pen</b>'},{id:2,sku:'BOOK',name:'Book'}];
const records=new Map(),receipts=new Map(),calls=[],previews=[];
const key=(id,day)=>id+':'+day;
let loseDayReceipt=false,failDayBefore=false,stallDay=false,releaseDay;
let loseImportReceipt=false,previewInvalid=false,holdDayRead=false,releaseDayRead;
class NetworkError extends Error{}
const response=(body,status=200)=>({ok:status>=200&&status<300,status,json:async()=>JSON.parse(JSON.stringify(body))});
function dayRecord(id,date){const row=records.get(key(id,date));return {product_id:id,sku:products.find(p=>p.id===id).sku,
  sale_date:date,units_sold:row?.units_sold??null,source:row?.source??'actual',stockout:row?.stockout??false,revision:row?.revision??0,logged_units:0};}
function history(id){const days=[{sale_date:'2026-10-14',units_sold:3,source:'live',status:'today_partial',stockout:false},
  {sale_date:'2026-10-13',units_sold:null,source:null,status:'missing',stockout:false}];
  const entries=[...records.values()].filter(r=>r.product_id===id);
  for(const r of entries){const index=days.findIndex(d=>d.sale_date===r.sale_date);if(index>=0)days.splice(index,1);
    days.push({...r,status:r.stockout?'stockout':'complete'});}
  return {sku:products.find(p=>p.id===id).sku,shop_date:'2026-10-14',start_date:'2026-07-17',end_date:'2026-10-14',
    actual_days:entries.filter(r=>r.source==='actual').length,demo_days:entries.filter(r=>r.source==='demo').length,
    zero_sales_days:entries.filter(r=>r.units_sold===0&&!r.stockout).length,stockout_days:entries.filter(r=>r.stockout).length,
    eligible_actual_days:entries.filter(r=>r.source==='actual'&&!r.stockout).length,missing_days:1,unconfirmed_days:0,
    message:'Missing dates are unknown, not zero. Demo is labelled.',items:days.sort((a,b)=>a.sale_date.localeCompare(b.sale_date))};}
const fetch=async(path,options={})=>{
  const url=new URL(path,'http://test'),body=options.body?JSON.parse(options.body):null;
  calls.push({path,method:options.method||'GET',body});
  if(url.pathname==='/api/products')return response(products);
  if(url.pathname==='/api/sales-history')return response(history(Number(url.searchParams.get('product_id'))));
  if(url.pathname==='/api/sales-history/day'){
    if(!options.method){const snapshot=dayRecord(Number(url.searchParams.get('product_id')),url.searchParams.get('sale_date'));
      if(holdDayRead){holdDayRead=false;return new Promise(resolve=>{releaseDayRead=()=>resolve(response(snapshot))})}
      return response(snapshot);}
    assert.equal(options.method,'PUT');assert.deepEqual(Object.keys(body).sort(),['expected_revision','product_id','request_id','sale_date','source','stockout','units_sold']);
    if(failDayBefore){failDayBefore=false;throw new NetworkError('Uncertain daily result')}
    if(stallDay){stallDay=false;await new Promise(resolve=>{releaseDay=resolve})}
    if(receipts.has(body.request_id))return response({...receipts.get(body.request_id),replayed:true});
    const old=records.get(key(body.product_id,body.sale_date));
    if((old?.revision??0)!==body.expected_revision)return response({detail:'This daily total changed.'},409);
    const saved={...body,revision:(old?.revision??0)+1};records.set(key(body.product_id,body.sale_date),saved);
    const result={revision:saved.revision,changed:true,replayed:false,message:'Saved'};receipts.set(body.request_id,result);
    if(loseDayReceipt){loseDayReceipt=false;throw new NetworkError('Lost daily receipt')}
    return response(result);
  }
  if(url.pathname.startsWith('/api/sales-history/requests/')){
    const id=url.pathname.split('/').at(-1);return receipts.has(id)?response({...receipts.get(id),replayed:true}):response({detail:'Unconfirmed'},404);
  }
  if(url.pathname==='/api/sales-history/import/preview'){
    previews.push(body);
    const invalid=previewInvalid;previewInvalid=false;
    return response({valid:!invalid,preview_id:invalid?null:'11111111-1111-4111-8111-111111111111',new_rows:invalid?0:1,
      unchanged_rows:0,invalid_rows:invalid?1:0,demo_rows:1,actual_rows:0,
      rows:[{line:2,sale_date:'2026-10-12',sku:invalid?'<script>BAD</script>':'PEN',units_sold:0,source:'demo',stockout:false,
        status:invalid?'invalid':'new',errors:invalid?['SKU does not exist.']:[]}]});
  }
  if(url.pathname==='/api/sales-history/import/commit'){
    assert.deepEqual(Object.keys(body).sort(),['preview_id','request_id']);
    records.set(key(1,'2026-10-12'),{product_id:1,sale_date:'2026-10-12',units_sold:0,source:'demo',stockout:false,revision:1});
    const result={inserted:1,unchanged:0,replayed:false};receipts.set(body.request_id,result);
    if(loseImportReceipt){loseImportReceipt=false;throw new NetworkError('Lost import receipt')}
    return response(result);
  }
  throw new Error('Unexpected request '+path);
};
const events={},window={addEventListener(name,handler){events[name]=handler},dispatchEvent(event){events[event.type]?.(event)}};
let changedEvents=0;events['resupply-history-changed']=()=>changedEvents++;
window.resupplyFetch=fetch;window.resupplyUrl=path=>path;
const context=vm.createContext({document:{getElementById:id=>elements[id],createElement:elem},window,fetch,crypto:{randomUUID},
  URLSearchParams,Date,Event:class{constructor(type){this.type=type}},Error:NetworkError,console});
vm.runInContext(js,context);
const tick=async()=>{for(let i=0;i<15;i++)await new Promise(resolve=>setImmediate(resolve))};
const event={preventDefault(){}};
async function chooseFile(text){elements['history-file'].files=[{size:text.length,text:async()=>text}];await elements['history-file'].handlers.change();}
(async()=>{
  await tick();
  assert.equal(elements['history-product'].value,'1');
  assert.equal(elements['history-product'].children[0].textContent,'<b>Pen</b> · PEN');
  assert.equal(elements['history-date'].value,'2026-10-13');
  assert.equal(elements['history-units'].value,'');
  assert.equal(elements['history-date'].max,'2026-10-13');
  assert.match(elements['history-demo'].href,/product_id=1/);
  assert.ok(elements['history-rows'].children.some(row=>row.children[1].textContent==='—'));
  elements['history-units'].value='0';loseDayReceipt=true;
  await elements['history-day-form'].handlers.submit(event);
  assert.equal(records.get(key(1,'2026-10-13')).units_sold,0);
  assert.equal(elements['history-error'].hidden,true);
  assert.match(elements['history-feedback'].textContent,/already saved/);
  assert.equal(elements['history-units'].value,'0');
  assert.equal(elements['history-actual'].textContent,'1');
  assert.equal(elements['history-save'].disabled,false);
  // An uncertain result keeps the exact payload locked for retry.
  elements['history-units'].value='6';failDayBefore=true;
  await elements['history-day-form'].handlers.submit(event);
  assert.equal(elements['history-units'].disabled,true);
  assert.equal(elements['history-product'].disabled,true);
  assert.equal(elements['history-save'].textContent,'Retry same daily total');
  const firstBody=calls.filter(c=>c.method==='PUT').at(-1).body;
  elements['history-units'].value='99';
  await elements['history-day-form'].handlers.submit(event);
  const retryBody=calls.filter(c=>c.method==='PUT').at(-1).body;
  assert.deepEqual(retryBody,firstBody);
  assert.equal(records.get(key(1,'2026-10-13')).units_sold,6);
  assert.equal(elements['history-units'].value,'6');
  // Busy submission and stale corrections are blocked.
  elements['history-units'].value='7';stallDay=true;
  const saving=elements['history-day-form'].handlers.submit(event);await tick();
  assert.equal(elements['history-save'].disabled,true);
  const before=calls.filter(c=>c.method==='PUT').length;
  await elements['history-day-form'].handlers.submit(event);
  assert.equal(calls.filter(c=>c.method==='PUT').length,before);
  releaseDay();await saving;
  records.get(key(1,'2026-10-13')).revision++;
  elements['history-units'].value='8';await elements['history-day-form'].handlers.submit(event);
  assert.match(elements['history-error'].textContent,/Reload day/);
  assert.equal(elements['history-save'].disabled,true);
  await elements['history-reload-day'].handlers.click();assert.equal(elements['history-save'].disabled,false);
  // File-size validation and preview do not import data.
  elements['history-file'].files=[{size:300001,text:async()=>''}];await elements['history-file'].handlers.change();
  assert.equal(elements['history-preview'].disabled,true);
  await chooseFile('bad-csv');previewInvalid=true;
  await elements['history-preview'].handlers.click();
  assert.equal(elements['history-commit'].hidden,true);
  assert.equal(elements['history-preview-rows'].children[0].children[2].textContent,'<script>BAD</script>');
  assert.equal(records.has(key(1,'2026-10-12')),false);
  await chooseFile('date,sku,units_sold,source\n2026-10-12,PEN,0,demo');
  await elements['history-preview'].handlers.click();
  assert.equal(elements['history-commit'].hidden,false);
  assert.equal(records.has(key(1,'2026-10-12')),false);
  loseImportReceipt=true;await elements['history-commit'].handlers.click();
  assert.equal(elements['history-commit'].hidden,true);
  assert.equal(elements['history-error'].hidden,true);
  assert.equal(elements['history-demo-days'].textContent,'1');
  assert.match(elements['history-feedback'].textContent,/already confirmed/);
  assert.ok(changedEvents>=3);
  // Older day details cannot overwrite a different product selection.
  holdDayRead=true;const loading=elements['history-reload-day'].handlers.click();await tick();
  records.set(key(2,'2026-10-13'),{product_id:2,sale_date:'2026-10-13',units_sold:12,source:'actual',stockout:false,revision:1});
  elements['history-product'].value='2';await elements['history-product'].handlers.change();
  assert.equal(elements['history-units'].value,'12');releaseDayRead();await loading;
  assert.equal(elements['history-units'].value,'12');
  assert.ok(calls.every(c=>c.method==='GET'||c.path.startsWith('/api/sales-history/')));
  console.log('PASS: history UI, unknown vs zero, safe labels, daily/import lost responses, locked identical retries, explicit preview confirmation, stale reads/edits and no inventory/payment mutations.');
})().catch(issue=>{console.error(issue);process.exit(1)});
