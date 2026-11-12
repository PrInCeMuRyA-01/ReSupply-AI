(() => {
  'use strict';
  const el=id=>document.getElementById(id), source=window.resupplyWorkspace.mode==='demo'?'demo':'actual';
  let products=[],auto=null,busy=false,timer=null,policyRevision=-1,setupInitialized=false;
  let pendingProduct=null,pendingStock=null;
  const payRequests=new Map();
  const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
  function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function message(id,text=''){el(id).textContent=text;el(id).hidden=!text;}
  async function api(path,options={}){
    const response=await window.resupplyFetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
    const result=await response.json();
    if(!response.ok){const e=new Error(typeof result.detail==='string'?result.detail:'Check the fields and try again.');e.status=response.status;throw e;}
    return result;
  }
  function controls(){
    for(const id of ['easy-add-product','easy-stock-save','easy-policy-save','easy-pause','easy-refresh','easy-pay','easy-receive','easy-open-order'])el(id).disabled=busy;
    for(const input of el('easy-product-form').querySelectorAll('input'))input.disabled=busy||!!pendingProduct;
    for(const input of el('easy-stock-form').querySelectorAll('input,select'))input.disabled=busy||!!pendingStock||!products.length;
    el('easy-stock-save').disabled=busy||!products.length;
    el('easy-ml-open').disabled=busy||el('forecast-product').disabled||el('forecast-source').disabled;
    el('easy-stock-save').textContent=busy?'Saving / checking stock…':pendingStock?'Retry the same stock update':'Save stock & prepare next step';
    el('easy-add-product').textContent=pendingProduct?'Retry the same product save':'Save product & supplier';
    el('easy-policy-save').textContent=auto?.settings?.enabled?'Save auto-restock settings':'Save & turn on auto restock';
  }
  function stockHint(){
    const p=products.find(p=>String(p.id)===el('easy-sale-product').value),remaining=el('easy-stock-mode').value==='remaining';
    el('easy-quantity-label').textContent=remaining?'How many units are left?':'How many units sold?';
    el('easy-stock-quantity').min=remaining?'0':'1';
    el('easy-stock-hint').textContent=p?`${p.stock} units currently in stock. `+(remaining?
      'A lower count records the difference as sales. For deliveries use “Goods arrived” to avoid counting twice.':'Saving decreases stock and checks your next purchase automatically.'):'Add a product in the one-time setup first.';
  }
  function renderProducts(){
    const select=el('easy-sale-product'),previous=select.value;select.replaceChildren();
    if(!products.length){const option=node('option','Add a product below first');option.value='';select.append(option);}
    for(const p of products){const option=node('option',p.name+' · '+p.stock+' left');option.value=String(p.id);select.append(option);}
    if(products.some(p=>String(p.id)===previous))select.value=previous;
    const list=el('easy-stock-list');list.replaceChildren();
    for(const p of products){const row=node('div',undefined,'easy-stock-row'),text=node('div');text.append(node('strong',p.name),node('small',p.supplier_name||'Supplier not selected'));row.append(text,node('span',p.stock+' left','easy-stock-number'));list.append(row);}
    const suppliers=el('easy-suppliers');suppliers.replaceChildren();
    for(const name of new Set(products.map(p=>p.supplier_name).filter(Boolean))){const option=document.createElement('option');option.value=name;suppliers.append(option);}
    const ai=el('easy-ai-list');ai.replaceChildren();
    for(const p of products){const row=node('div',undefined,'easy-ai-row');row.append(node('strong',p.name));
      row.append(node('span',p.active_run_id?(p.selected_method==='random_forest'?'Random Forest forecast in use':'Tested 7-day average in use'):
        p.daily_units!==null?'Starting estimate available: '+p.daily_units+' units/day':'Uses available recorded sales; add history to improve demand estimates.'));
      row.append(node('small',p.reason));
      if(p.current&&p.model_mae!==null)row.append(node('small','Tested MAE: ML '+p.model_mae+' · average '+p.baseline_mae+' units/day. Lower is better.'));
      ai.append(row);
    }
    const current=products.filter(p=>p.current),selected=current.filter(p=>p.active_run_id&&p.selected_method==='random_forest');
    el('easy-ml-proof').hidden=source!=='demo'||!current.length;
    if(source==='demo'&&current.length){
      el('easy-ml-days').textContent=String(Math.min(...current.map(p=>p.training_days)));
      el('easy-ml-models').textContent=String(current.length);
      el('easy-ml-selected').textContent=String(selected.length);
      el('easy-ml-proof-copy').textContent='Real training and chronological testing on labelled sample data. Open a report to see the 7-day forecast and both measured errors. A simple average stays selected when it performs better.';
    }
    stockHint();
  }
  function renderPolicy(){
    if(!auto?.settings)return;
    const s=auto.settings;
    document.body.classList.toggle('easy-running',s.enabled&&products.length>0);
    document.body.classList.toggle('easy-configuring',!s.enabled||!products.length);
    el('easy-mode').textContent=(source==='demo'?'DEMO · ':'')+(s.enabled?'Auto restock ON':'One-time setup');
    if(policyRevision!==auto.revision){
      for(const [id,key] of [['easy-limit','spending_limit'],['easy-shipping','shipping'],['easy-tax','tax'],['easy-coverage','coverage_days'],['easy-buffer','buffer_days']])el(id).value=s[key];
      for(const [id,key] of [['easy-enabled','enabled'],['easy-auto-history','auto_history'],['easy-zero-days','zero_days_confirmed']])el(id).checked=s[key];
      policyRevision=auto.revision;
    }
    el('easy-pause').hidden=!s.enabled;
    if(!setupInitialized){el('easy-setup').open=!products.length||!s.enabled;setupInitialized=true;}
    if(!products.length||!s.enabled)el('easy-setup').open=true;
  }
  function renderOrder(){
    const box=el('easy-order-content');box.replaceChildren();
    for(const id of ['easy-pay','easy-receive','easy-open-order'])el(id).hidden=true;
    if(!auto){box.append(node('p','Loading your shop…','easy-empty'));return;}
    el('easy-notice').textContent=auto.message||'Keep recording stock. Automatic checks run when this app is open or you save an update.';
    const o=auto.order;
    if(!o){box.append(node('p',auto.settings?.enabled?'No payment is needed right now. Keep updating sales; a low-stock order will appear here.':'Add your products and enable automatic restocking below.','easy-empty'));return;}
    const state=o.payment?.state||o.status;
    box.append(node('div',o.number,'easy-order-status'));
    const labels={draft:'Ready for your payment',approved:'Ready for checkout',authorized:'Funds held — complete payment',captured:'Paid — waiting for goods',
      capture_unknown:'Payment needs a status check',capture_pending:'Payment pending',authorize_unknown:'Checkout needs a status check',review_required:'Payment needs review'};
    box.append(node('strong',labels[state]||state.replaceAll('_',' ')));
    for(const item of o.items){const row=node('div',undefined,'easy-order-line'),name=node('div',item.name);name.append(node('small',item.quantity+' units · '+item.supplier_name));row.append(name,node('span',money(item.line_total)));box.append(row);}
    const shipping=o.status==='draft'?auto.settings.shipping:o.shipping_cost,tax=o.status==='draft'?auto.settings.tax:o.tax_cost;
    const charges=node('div',undefined,'easy-order-line');charges.append(node('span','Shipping + tax'),node('span',money(Number(shipping)+Number(tax))));box.append(charges);
    const total=o.status==='draft'?Number(o.products_total)+Number(shipping)+Number(tax):Number(o.grand_total);
    const grand=node('div',undefined,'easy-grand');grand.append(node('span','Total · USD test money'),node('strong',money(total)));box.append(grand);
    el('easy-open-order').hidden=false;
    if(o.status==='draft'||(o.status==='approved'&&(!o.payment||['ready','create_failed','authorized'].includes(state)))){
      el('easy-pay').hidden=false;el('easy-pay').textContent='Pay '+money(total)+' with PayPal';
    }
    el('easy-receive').hidden=!o.can_receive;
  }
  async function sync(run=false){
    const [status,settings]=await Promise.all([api('/api/easy/status'),api('/api/easy/autopilot')]);
    products=status.products;
    auto={...(auto||{}),...settings};
    if(run&&settings.settings.enabled)auto=await api('/api/easy/autopilot/run',{method:'POST'});
    if(!settings.settings.enabled)auto={...settings,order:null,message:'Finish one-time setup. Then only stock updates and your PayPal approval are needed for purchasing.'};
    if(run){const fresh=await api('/api/easy/status');products=fresh.products;}
    renderProducts();renderPolicy();renderOrder();controls();
  }
  function queue(){clearTimeout(timer);timer=setTimeout(()=>{if(busy)return;sync(true).catch(e=>message('easy-error',e.message));},400);}
  function announce(){window.dispatchEvent(new Event('resupply-easy-data-changed'));}
  async function work(action){
    if(busy)return;busy=true;controls();message('easy-error');
    try{await action();}catch(e){message('easy-error',e.message||'Could not finish. Refresh the shop and check saved results.');}
    finally{busy=false;controls();}
  }
  el('easy-product-form').addEventListener('submit',event=>{
    event.preventDefault();if(!pendingProduct&&!event.currentTarget.reportValidity())return;
    work(async()=>{
      pendingProduct??={request_id:crypto.randomUUID(),name:el('easy-name').value,stock:Number(el('easy-stock').value),unit_cost:el('easy-cost').value,
        supplier_name:el('easy-supplier').value,lead_time_days:Number(el('easy-lead').value),daily_units:el('easy-daily').value===''?null:Number(el('easy-daily').value),sku:el('easy-sku').value||null};controls();
      let result;try{result=await api('/api/easy/products',{method:'POST',body:JSON.stringify(pendingProduct)});}catch(e){if(e.status&&e.status<500)pendingProduct=null;throw e;}
      const supplier=pendingProduct.supplier_name;pendingProduct=null;el('easy-product-form').reset();el('easy-supplier').value=supplier;
      el('easy-product-feedback').textContent=result.name+' saved. Product code: '+result.sku;announce();await sync(true);
    });
  });
  el('easy-stock-form').addEventListener('submit',event=>{
    event.preventDefault();if(!pendingStock&&!event.currentTarget.reportValidity())return;
    work(async()=>{
      const p=products.find(p=>String(p.id)===el('easy-sale-product').value);
      if(!p)throw new Error('Add or choose a product first.');
      pendingStock??={request_id:crypto.randomUUID(),product_id:p.id,mode:el('easy-stock-mode').value,quantity:Number(el('easy-stock-quantity').value),expected_stock:p.stock};controls();
      let result;try{result=await api('/api/easy/stock-update',{method:'POST',body:JSON.stringify(pendingStock)});}catch(e){if(e.status&&e.status<500){pendingStock=null;await sync(false);}throw e;}
      pendingStock=null;el('easy-stock-quantity').value='';auto=result.autopilot;announce();await sync(false);renderOrder();
      if(result.autopilot.needs_retry)message('easy-error',result.autopilot.message);
    });
  });
  el('easy-policy-form').addEventListener('submit',event=>{
    event.preventDefault();if(!event.currentTarget.reportValidity())return;
    work(async()=>{
      const body={expected_revision:auto.revision,enabled:el('easy-enabled').checked,spending_limit:el('easy-limit').value,
        shipping:el('easy-shipping').value,tax:el('easy-tax').value,coverage_days:Number(el('easy-coverage').value),buffer_days:Number(el('easy-buffer').value),
        auto_history:el('easy-auto-history').checked,zero_days_confirmed:el('easy-zero-days').checked};
      auto=await api('/api/easy/autopilot',{method:'PUT',body:JSON.stringify(body)});await sync(false);
      if(products.length&&auto.settings.enabled)el('easy-setup').open=false;
    });
  });
  el('easy-pause').addEventListener('click',()=>work(async()=>{
    auto=await api('/api/easy/autopilot',{method:'PUT',body:JSON.stringify({...auto.settings,expected_revision:auto.revision,enabled:false})});await sync(false);
  }));
  el('easy-refresh').addEventListener('click',()=>work(()=>sync(true)));
  el('easy-ml-open').addEventListener('click',()=>{
    try{
      const p=products.find(p=>p.current&&p.selected_method==='random_forest')||products.find(p=>p.current);
      if(!p)throw new Error('Refresh suggestions to prepare a current forecast.');
      const selector=el('forecast-product'),trainingSource=el('forecast-source');
      if(selector.disabled||trainingSource.disabled||window.resupplyPurchasingBusy)throw new Error('Wait for the current action to finish, then open the forecast.');
      if(![...selector.options].some(o=>o.value===String(p.id)))throw new Error('Product choices are refreshing. Open the forecast again in a moment.');
      if(!window.resupplyNavigate('forecast'))return;
      selector.value=String(p.id);trainingSource.value=source;selector.dispatchEvent(new Event('change'));
    }catch(e){message('easy-error',e.message);}
  });
  el('easy-stock-mode').addEventListener('change',stockHint);el('easy-sale-product').addEventListener('change',stockHint);
  function openOrder(order,completePayment=false){
    const detail={order,completePayment,applied:false};window.dispatchEvent(new CustomEvent('resupply-easy-open-order',{detail}));
    if(!detail.applied)throw new Error('Finish or close the current dialog, then open this order.');
  }
  el('easy-open-order').addEventListener('click',()=>{try{openOrder(auto.order);}catch(e){message('easy-error',e.message);}});
  el('easy-receive').addEventListener('click',()=>{try{openOrder(auto.order);el('receive-stock').click();}catch(e){message('easy-error',e.message);}});
  el('easy-pay').addEventListener('click',()=>work(async()=>{
    let order=auto.order;if(!order)throw new Error('Refresh the shop to see your order.');
    if(order.status==='draft'){
      let request=payRequests.get(order.id);
      if(!request){request={request_id:crypto.randomUUID(),order_id:order.id,expected_version:order.version,expected_policy_revision:auto.revision};payRequests.set(order.id,request);}
      const result=await api('/api/easy/autopilot/pay-ready',{method:'POST',body:JSON.stringify(request)});order=result.order;payRequests.delete(order.id);auto.order=order;
    }
    openOrder(order,true);renderOrder();
  }));
  el('easy-llm-form').addEventListener('submit',event=>{
    event.preventDefault();if(!event.currentTarget.reportValidity())return;
    work(async()=>{
      el('easy-llm-fill').disabled=true;
      try{
        const result=await api('/api/easy/llm/suggest',{method:'POST',body:JSON.stringify({text:el('easy-llm-text').value,consent_to_send:el('easy-llm-consent').checked})});const s=result.suggestion;
        if(s.intent==='add_product'){
          if(pendingProduct)throw new Error('Finish the pending product save first.');
          el('easy-product-form').reset();
          for(const [id,key] of [['easy-name','name'],['easy-stock','stock'],['easy-cost','unit_cost'],['easy-supplier','supplier_name'],['easy-daily','daily_units'],['easy-lead','lead_time_days']])el(id).value=s[key]??'';
          el('easy-setup').open=true;el('easy-name').focus();
        }else if(s.intent==='record_sale'){
          if(pendingStock)throw new Error('Finish the pending stock update first.');
          const name=(s.name||'').trim().toLowerCase(),matches=products.filter(p=>p.name.toLowerCase()===name||p.sku.toLowerCase()===name);
          if(matches.length!==1)throw new Error('Choose the product in the stock form; the spoken name was not an exact unique match.');
          el('easy-sale-product').value=String(matches[0].id);el('easy-stock-mode').value='sold';el('easy-stock-quantity').value=s.quantity??'';stockHint();el('easy-stock-quantity').focus();
        }
        el('easy-llm-feedback').textContent=s.explanation+' Review the form and press Save. Nothing has been saved yet.';
      }finally{el('easy-llm-fill').disabled=false;}
    });
  });
  for(const event of ['resupply-catalog-changed','resupply-history-changed','resupply-orders-changed','resupply-planning-changed'])window.addEventListener(event,queue);
  window.addEventListener('resupply-view-changed',event=>{if(event.detail.view==='overview')queue();});
  window.addEventListener('resupply-forecast-view-changed',()=>setTimeout(controls,0));
  // No timer payments. Saved opt-in automation resumes when the shop is opened.
  sync(true).catch(e=>message('easy-error',e.message));
  api('/api/easy/llm/config').then(c=>{
    el('easy-llm-status').textContent=c.configured?'Optional OpenAI form filling is ready. Only the sentence you submit is sent.':'Optional AI typing is off. The shop and automatic restocking work without it. Setup instructions are in START-HERE.md.';
    el('easy-llm-fill').disabled=!c.configured;
  }).catch(()=>{el('easy-llm-status').textContent='Optional typing helper unavailable. Normal shop forms still work.';});
})();
