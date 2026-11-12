(() => {
  'use strict';
  if (window.resupplyWorkspace.mode !== 'demo') return;
  const el=id=>document.getElementById(id);
  let state=null,busy=false,readVersion=0;
  const trainingRequests=new Map();
  const show=(id,text='')=>{el(id).textContent=text;el(id).hidden=!text;};
  async function api(path,options={}) {
    const response=await window.resupplyFetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
    const data=await response.json();
    if (!response.ok) {const error=new Error(typeof data.detail==='string'?data.detail:'Demo request failed. Check the server.');error.status=response.status;throw error;}
    return data;
  }
  function controls() {
    const locked=busy || !!window.resupplyPurchasingBusy;
    el('demo-prepare').disabled=locked;
    el('demo-refresh').disabled=busy;
    el('demo-plan').disabled=locked || !state?.prepared;
    for (const button of el('demo-models').querySelectorAll('button')) button.disabled=locked;
  }
  function row(text,done,target) {
    const item=document.createElement('li');
    const label=document.createElement('span');label.textContent=(done?'✓ ':'○ ')+text;item.append(label);
    if(target) {
      const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Open';
      button.addEventListener('click',()=>{const page=target==='forecast-title'?'forecast':target==='purchase-title'?'purchasing':'orders';if(window.resupplyNavigate&&!window.resupplyNavigate(page))return;el(target).scrollIntoView({behavior:'smooth',block:'start'});});item.append(button);
    }
    el('demo-progress').append(item);
  }
  function openForecast(product) {
    if(busy)return;
    const selector=el('forecast-product'),source=el('forecast-source');
    if(selector.disabled || source.disabled || window.resupplyPurchasingBusy) {
      show('demo-error','Finish or retry the pending forecast/review action, then open this product.');return;
    }
    if (![...selector.options].some(option=>option.value===String(product.id))) {
      window.dispatchEvent(new Event('resupply-catalog-changed'));
      show('demo-error','Product choices are refreshing. Open this forecast again in a moment.');return;
    }
    if(window.resupplyNavigate&&!window.resupplyNavigate('forecast'))return;
    selector.value=String(product.id);source.value='demo';selector.dispatchEvent(new Event('change'));
    el('forecast-title').scrollIntoView({behavior:'smooth',block:'start'});
  }
  function render(data) {
    state=data;
    const samples=data.products.filter(p=>p.sample),current=samples.filter(p=>p.current).length;
    const reviewed=samples.filter(p=>p.active_run_id).length,all=samples.length;
    const order=data.focus_order,payment=order?.payment;
    el('demo-summary').textContent=data.prepared
      ? `${data.counts.products} products · ${data.counts.suppliers} suppliers · ${data.counts.daily_sales_history} synthetic daily totals · ${current}/${all} current forecasts · ${reviewed}/${all} reviewed. Shop date ${data.shop_date} (IST).`
      : 'Demo shop ready to prepare. Press Prepare demo shop + forecasts to load samples and train the models.';
    el('demo-prepare').textContent=data.prepared?'Refresh demo data + forecasts':'Prepare demo shop + forecasts';
    el('demo-models').replaceChildren();
    for(const product of samples) {
      const box=document.createElement('p'),text=document.createElement('span');
      const method=product.selected_method==='random_forest'?'ML selected':'Average selected';
      text.textContent=`${product.name} (${product.sku}) · stock ${product.stock} · `+
        (product.current?`${method}, ${product.training_days} days trained`:'Needs current training')+
        (product.active_run_id?` · reviewed run #${product.active_run_id}`:' · review needed');
      const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='Review forecast';
      button.addEventListener('click',()=>openForecast(product));box.append(text,button);el('demo-models').append(box);
    }
    el('demo-progress').replaceChildren();
    row('Prepare samples + train forecasts ('+current+'/'+all+')',data.prepared&&all>0&&current===all,'forecast-title');
    row('Review forecasts ('+reviewed+'/'+all+') + build a budget plan',all>0&&reviewed===all,'purchase-title');
    row(order?`Save + approve order: ${order.number} · ${order.status}`:'Save draft + review quantities, shipping and tax',!!order&&['approved','received'].includes(order.status),'orders-title');
    row(payment?`Sandbox payment: ${payment.state}`:'PayPal Sandbox: authorize hold, then confirm Capture',payment?.state==='captured','orders-title');
    row(order?.receipt?`Receive Stock: ${order.receipt.units} units added once`:'Receive full stock after goods arrive',!!order?.receipt,'orders-title');
    el('demo-note').textContent=data.message+' Sample suppliers are metadata; the Sandbox payment goes to one test merchant.';
    controls();
    window.dispatchEvent(new CustomEvent('resupply-demo-state',{detail:data}));
  }
  async function refresh() {
    const version=++readVersion;
    try {const data=await api('/api/demo-shop');if(version===readVersion)render(data);return data;}
    catch(error){if(version===readVersion)show('demo-error',error.message);throw error;}
  }
  async function train(product) {
    let payload=trainingRequests.get(product.id);
    if(!payload){payload={request_id:crypto.randomUUID(),product_id:product.id,source:'demo'};trainingRequests.set(product.id,payload);}
    let result;
    try {result=await api('/api/forecast/train',{method:'POST',body:JSON.stringify(payload)});}
    catch(error) {
      if([400,404,409,422].includes(error.status)){trainingRequests.delete(product.id);throw error;}
      try{result=await api('/api/forecast/requests/'+payload.request_id);}catch(_){throw new Error('Training result is not confirmed. Retry Prepare; the same request ID is kept.');}
    }
    if(!result.report_current){trainingRequests.delete(product.id);throw new Error('History or shop date changed. Prepare again for a current forecast.');}
    trainingRequests.delete(product.id);
  }
  el('demo-prepare').addEventListener('click',async()=>{
    if(busy || window.resupplyPurchasingBusy){show('demo-error','Finish or retry the pending forecast review before preparing.');return;}
    busy=true;controls();show('demo-error');show('demo-feedback','Preparing synthetic data…');
    try {
      await api('/api/demo-shop/setup',{method:'POST'});
      window.dispatchEvent(new Event('resupply-demo-data-ready'));
      const data=await refresh();
      for(const product of data.products.filter(p=>p.sample)) {
        // Reuse current reports and owner choices. Training never activates a
        // new report or changes approved quantities / payment state.
        if(!product.current) {
          if(!product.ready)throw new Error(product.name+': '+product.reason);
          show('demo-feedback','Training '+product.name+' on synthetic completed days…');
          await train(product);await refresh();
        }
      }
      window.dispatchEvent(new Event('resupply-forecast-refresh'));
      show('demo-feedback','Demo forecasts ready. Review each forecast and Preview purchase impact → Use this demo forecast. Then open the $100 budget plan.');
    }catch(error){show('demo-feedback');show('demo-error',error.message);}
    finally{busy=false;controls();await refresh().catch(()=>{});}
  });
  el('demo-refresh').addEventListener('click',()=>{if(!busy)refresh().catch(()=>{});});
  el('demo-plan').addEventListener('click',async()=>{
    if(busy||!state?.prepared)return;
    busy=true;controls();show('demo-error');
    try {
      const plan=await api('/api/purchase-plan?budget=100.00&lead_time_days=3&coverage_days=7&buffer_days=2');
      const detail={plan,applied:false};window.dispatchEvent(new CustomEvent('resupply-demo-budget',{detail}));
      if(!detail.applied)show('demo-error','Finish the pending order/payment action, then open the plan again.');
      else show('demo-feedback','Fresh $100 demo product-budget plan opened. Shipping/tax are checked with the draft; saving and approval use the existing buttons.');
    }catch(error){show('demo-error',error.message);}
    finally{busy=false;controls();}
  });
  for(const name of ['resupply-catalog-changed','resupply-planning-changed','resupply-orders-changed','resupply-history-changed','resupply-forecast-view-changed']) {
    window.addEventListener(name,()=>{if(!busy)refresh().catch(()=>{});});
  }
  window.addEventListener('resupply-purchasing-lock',controls);
  refresh().catch(()=>{});
})();
