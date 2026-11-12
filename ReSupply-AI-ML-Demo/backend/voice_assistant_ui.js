(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  const text=el('voice-text'),product=el('voice-product'),source=el('voice-source'),language=el('voice-language');
  const Recognition=window.SpeechRecognition || window.webkitSpeechRecognition;
  let active=null,busy=false,version=0,catalogVersion=0,result=null,limitTimer=null,endTimer=null;
  const num=v=>Number(v).toLocaleString('en-US',{maximumFractionDigits:2});
  const showError=(message='')=>{el('voice-error').textContent=message;el('voice-error').hidden=!message;};
  const state=(message,listening=false)=>{el('voice-state').textContent=message;el('voice-state').className='badge'+(listening?' listening':'');};

  function controls(){
    const locked=!!active||busy;
    for(const id of ['voice-text','voice-product','voice-source','voice-language','voice-preview','voice-stock-example','voice-low-example','voice-forecast-example','voice-budget-example'])el(id).disabled=locked;
    el('voice-start').disabled=locked||!Recognition;
    el('voice-stop').disabled=!active||active.stopping;
    el('voice-cancel').disabled=!active;
    el('voice-form').setAttribute('aria-busy',String(busy));
    el('voice-preview').textContent=busy?'Checking…':'Preview command';
  }
  function invalidate(){++version;result=null;el('voice-result').hidden=true;}
  async function api(path,options={}){
    const response=await window.resupplyFetch(path,{cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}});
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Check the command and planner settings, then retry.');
    return data;
  }
  async function catalog(){
    const current=++catalogVersion;
    try{
      const products=await api('/api/products');if(current!==catalogVersion)return;
      const selected=product.value;product.replaceChildren();
      const empty=document.createElement('option');empty.value='';empty.textContent='Use spoken name / SKU';product.append(empty);
      for(const p of products){const option=document.createElement('option');option.value=String(p.id);option.textContent=p.name+' · '+p.sku;product.append(option);}
      product.value=products.some(p=>String(p.id)===selected)?selected:'';
    }catch(error){showError('Products could not load. Refresh the page or retry after the server is available.');}
    controls();
  }
  function table(headers,rows,fields){
    const head=el('voice-columns');head.replaceChildren();const tr=document.createElement('tr');
    for(const title of headers){const th=document.createElement('th');th.textContent=title;th.scope='col';tr.append(th);}head.append(tr);
    const body=el('voice-rows');body.replaceChildren();
    for(const row of rows){const tr=document.createElement('tr');for(const field of fields){const td=document.createElement('td');td.textContent=field(row);tr.append(td);}body.append(tr);}
    el('voice-table-wrap').hidden=false;
  }
  function render(data){
    result=data;el('voice-result').hidden=false;el('voice-answer').textContent=data.message;
    el('voice-note').textContent='';el('voice-choices').replaceChildren();el('voice-table-wrap').hidden=true;el('voice-open').hidden=true;
    if(data.status==='needs_product'){
      for(const p of data.items){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=p.name+' · '+p.sku;
        button.addEventListener('click',()=>{if(busy||active)return;product.value=String(p.id);text.value=(data.intent==='forecast'?'Forecast ':'Stock ')+p.sku;invalidate();preview();});
        el('voice-choices').append(button);
      }return;
    }
    if(data.intent==='budget'&&data.status==='ready'){
      const p=data.plan;
      el('voice-note').textContent=`All-product preview · planned ${num(p.planned_units)} units for $${Number(p.planned_cost).toFixed(2)} · remaining $${Number(p.remaining_budget).toFixed(2)}. Product costs only; shipping/tax are reviewed with the saved order. Uses current reviewed ${window.resupplyWorkspace?.mode === 'demo' ? 'demo / synthetic' : 'actual'} forecasts or the sales-average fallback.`;
      table(['Product / SKU','Suggested','Fits budget','Cost (USD)','Basis'],p.items,[r=>r.name+' · '+r.sku,r=>r.suggested_quantity===null?'Needs history':num(r.suggested_quantity),r=>num(r.planned_quantity),r=>'$'+Number(r.line_cost).toFixed(2),r=>r.forecast_run_id?'Reviewed '+(r.demand_source==='reviewed_ml'?'ML':'forecast average')+' #'+r.forecast_run_id:'Sales average']);
      el('voice-open').textContent='Open this budget in planner';el('voice-open').hidden=false;
    }else if(data.intent==='forecast'&&data.status==='ready'){
      el('voice-note').textContent=`${data.source==='demo'?'DEMO · synthetic data':'Actual shop data'} · ${data.selected_method==='random_forest'?'ML selected':'Forecast average selected'} · tested MAE: ML ${num(data.model_mae)}, average ${num(data.baseline_mae)}.`;
      table(['Date (IST)','Selected units','ML units','Average units'],data.items,[r=>r.date,r=>num(r.selected_units),r=>num(r.model_units),r=>num(r.baseline_units)]);
      el('voice-open').textContent='Open matching forecast';el('voice-open').hidden=false;
    }else if(data.intent==='forecast'&&data.product){el('voice-open').textContent='Open ML forecast section';el('voice-open').hidden=false;}
    else if(data.intent==='low_stock'){
      if(data.items.length)table(['Product / SKU','Stock','Suggested buy','Reason'],data.items,[r=>r.name+' · '+r.sku,r=>num(r.stock),r=>r.suggested_quantity===null?'Needs history':num(r.suggested_quantity),r=>r.reason]);
      else el('voice-note').textContent='No products match the current low-stock/restock estimate. Products with unknown demand may still need full-day sales history.';
    }
  }
  async function preview(event){
    event?.preventDefault();if(busy||active)return;
    if(!text.value.trim()||text.value.length>400){showError('Enter one command, up to 400 characters.');return;}
    if(!el('voice-form').reportValidity())return;
    for(const id of ['lead-time','coverage-days','buffer-days'])if(!el(id).reportValidity()){showError('Correct the planner delivery, coverage and buffer settings first.');return;}
    const body={text:text.value.trim(),product_id:product.value?Number(product.value):null,forecast_source:source.value,
      lead_time_days:Number(el('lead-time').value),coverage_days:Number(el('coverage-days').value),buffer_days:Number(el('buffer-days').value)};
    invalidate();const current=version;busy=true;controls();showError();state('Checking command');
    try{const data=await api('/api/assistant/preview',{method:'POST',body:JSON.stringify(body)});if(current===version)render(data);}
    catch(error){if(current===version)showError(error.message);}
    finally{busy=false;controls();state('Ready for text');}
  }
  function finish(session){
    if(active!==session)return;
    clearTimeout(limitTimer);clearTimeout(endTimer);limitTimer=endTimer=null;
    active=null;controls();state('Review the command');
  }
  function cancel(restore=true){
    const session=active;if(!session)return;
    if(restore)text.value=session.previous;
    finish(session);try{session.rec.abort();}catch(_){}
    state('Listening cancelled');
  }
  function stop(){
    const session=active;if(!session||session.stopping)return;
    session.stopping=true;controls();state('Finishing speech…');clearTimeout(limitTimer);
    try{session.rec.stop();}catch(_){finish(session);showError('Speech stopped unexpectedly. Review or type your command.');return;}
    if(active===session)endTimer=setTimeout(()=>{if(active===session){finish(session);try{session.rec.abort();}catch(_){}showError('Speech service did not finish. Review the text or type your command.');}},5000);
  }
  el('voice-start').addEventListener('click',()=>{
    if(!Recognition||busy||active)return;
    invalidate();showError();
    let rec;try{rec=new Recognition();}catch(_){showError('Speech service is unavailable. Type your command instead.');return;}
    const session={rec,previous:text.value,stopping:false,heard:false};active=session;
    rec.lang=language.value;rec.continuous=false;rec.interimResults=true;rec.maxAlternatives=1;
    rec.onstart=()=>{if(active===session)state('Listening…',true);};
    rec.onresult=event=>{
      if(active!==session)return;
      const chunks=[];for(let i=0;i<event.results.length;i++)chunks.push(event.results[i][0].transcript);
      const recognized=chunks.join(' ').trim();if(recognized){text.value=recognized;session.heard=true;}
      if(text.value.length>400)showError('Speech text is too long. Shorten it before previewing.');
    };
    rec.onerror=event=>{
      if(active!==session)return;
      const messages={'not-allowed':'Microphone permission was denied. Allow it in browser site settings or type your command.',
        'service-not-allowed':'Browser speech service is unavailable. Type your command.',
        'audio-capture':'Microphone could not start. Check the selected microphone or type your command.',
        'network':'Speech service needs a working connection. Retry or type your command.',
        'no-speech':'No speech was recognized. Try again or type your command.',
        'language-not-supported':'This speech language is unavailable. Choose another language or type your command.',
        'aborted':'Listening stopped. Review or type your command.'};
      finish(session);showError(messages[event.error]||'Speech recognition failed. Type your command or try again.');
      try{rec.abort();}catch(_){}
    };
    rec.onend=()=>{if(active!==session)return;finish(session);if(!session.heard)showError('No speech was recognized. Type your command or try again.');};
    controls();state('Starting microphone…');
    try{rec.start();if(active===session)limitTimer=setTimeout(stop,30000);}
    catch(_){finish(session);showError('Microphone could not start. Check browser permission or type your command.');}
  });
  el('voice-stop').addEventListener('click',stop);el('voice-cancel').addEventListener('click',()=>cancel());
  el('voice-form').addEventListener('submit',preview);
  for(const id of ['voice-text','voice-product','voice-source'])el(id).addEventListener(id==='voice-text'?'input':'change',()=>{invalidate();showError();});
  for(const [id,command] of [['voice-stock-example','Stock dikhao'],['voice-low-example','Low stock dikhao'],['voice-forecast-example','Forecast dikhao'],['voice-budget-example','50 dollar budget ka plan banao']])el(id).addEventListener('click',()=>{if(active||busy)return;text.value=command;invalidate();showError();text.focus();});
  el('voice-open').addEventListener('click',()=>{
    if(!result||busy||active)return;
    if(result.intent==='budget'){
      const detail={plan:result.plan,applied:false};window.dispatchEvent(new CustomEvent('resupply-voice-budget',{detail}));
      if(!detail.applied)showError('Finish the current order operation, then open the budget planner.');
    }else if(result.intent==='forecast'){
      const target=el('forecast-product'),mode=el('forecast-source');
      if(target.disabled||mode.disabled){showError('Finish the current forecast or purchasing review before opening another forecast.');return;}
      if(window.resupplyNavigate&&!window.resupplyNavigate('forecast'))return;
      target.value=String(result.product.id);mode.value=result.source;
      mode.dispatchEvent(new Event('change',{bubbles:true}));
      el('forecast-title').scrollIntoView({behavior:'smooth',block:'start'});
    }
  });
  for(const name of ['resupply-catalog-changed','resupply-history-changed','resupply-planning-changed','resupply-orders-changed'])window.addEventListener(name,()=>{if(busy||result)showError('Shop data was refreshed. Preview the command again for current values.');invalidate();if(name==='resupply-catalog-changed')catalog();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)cancel();});
  window.addEventListener('beforeunload',()=>cancel(false));
  window.addEventListener('resupply-view-changed',event=>{if(event.detail?.previous==='assistant'&&event.detail.view!=='assistant')cancel();});
  el('voice-support').textContent=Recognition?'Microphone available. Hindi/English recognition quality depends on your browser; review the text before previewing.':'Speech recognition is unavailable in this browser. Typed commands and all previews still work.';
  controls();catalog();
})();
