(() => {
  'use strict';
  const el = id => document.getElementById(id);
  let context = null, preview = null, busy = false, previewBusy = false, pending = null;
  let previewVersion = 0, listVersion = 0, queued = false, rowControls = [];
  const num = value => Number(value).toLocaleString('en-US',{maximumFractionDigits:2});
  const money = value => '$' + Number(value).toFixed(2);
  const signal = name => window.dispatchEvent(new Event(name));
  const shopSource = window.resupplyWorkspace?.mode === 'demo' ? 'demo' : 'actual';
  const simulation = () => context?.source === 'demo' && shopSource === 'actual';
  const matches = () => context && String(context.product.id) === el('forecast-product').value && context.source === el('forecast-source').value;
  const show = (id,text='') => {el(id).textContent=text;el(id).hidden=!text;};

  async function api(path, options={}) {
    const response = await window.resupplyFetch(path,{cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}});
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'Check the entered values and refresh.');
      error.status = response.status; throw error;
    }
    return data;
  }

  function controls() {
    const locked = busy || !!pending;
    const valid = matches() && context.report_current;
    el('impact-preview').disabled = locked || previewBusy || !valid;
    el('impact-average').disabled = locked || !matches() || context.source !== shopSource || !context.planning?.reviewed_run_id;
    el('impact-use').hidden = !matches() || context.source !== shopSource;
    el('impact-use').disabled = locked || previewBusy || !preview || !valid || !context.planning?.can_use || preview.run_id !== context.run_id;
    el('impact-demo-stock').disabled = locked || previewBusy;
    el('incoming-refresh').disabled = busy;
    el('purchasing-retry').hidden = !pending;
    el('purchasing-retry').disabled = busy;
    for (const item of rowControls) item.disabled = locked;
    if (window.resupplyPurchasingBusy !== locked) {
      window.resupplyPurchasingBusy = locked;
      signal('resupply-purchasing-lock');
    }
  }

  function clearPreview() {
    preview = null; ++previewVersion;
    el('impact-result').hidden = true;
    controls();
  }

  function view(data) {
    if (String(data.product.id) !== el('forecast-product').value || data.source !== el('forecast-source').value) return;
    context = data;
    clearPreview();
    el('impact-demo-stock-label').hidden = data.source !== 'demo' || shopSource === 'demo';
    el('impact-status').textContent = data.source === 'demo' && shopSource === 'actual' ? 'DEMO simulation only. Preview delivery, buffer and a sample budget; it cannot be used for real purchasing.' : data.planning?.message || 'Review a current actual forecast for purchasing.';
    controls();
  }

  async function loadIncoming(force=false) {
    if ((busy || pending) && !force) {queued=true;return;}
    const version = ++listVersion;
    try {
      const data = await api('/api/incoming-stock');
      if (version !== listVersion) return;
      el('incoming-status').textContent = data.items.length ? data.message : 'No fully captured orders are awaiting stock. After Capture, refresh this list to set an expected arrival.';
      const body = el('incoming-rows'); body.replaceChildren(); rowControls = [];
      const limit = new Date(data.shop_date+'T00:00:00Z');limit.setUTCDate(limit.getUTCDate()+90);
      for (const item of data.items) {
        const row = document.createElement('tr');
        const order = document.createElement('td');order.textContent=item.number;
        const goods = document.createElement('td');goods.textContent=item.items.map(i=>`${i.name} (${i.sku}): ${i.quantity}`).join(' · ');
        const dateCell = document.createElement('td');
        const input = document.createElement('input');input.type='date';input.className='incoming-date';
        input.value=item.arrival_date||'';input.min=data.shop_date;input.max=limit.toISOString().slice(0,10);input.required=true;
        input.setAttribute('aria-label','Expected arrival for '+item.number);
        const status = document.createElement('span');status.className='hint';
        status.textContent=item.status==='overdue'?'Overdue · excluded from planning':item.status==='no_date'?'No date · excluded from planning':'Expected at end of day';
        dateCell.append(input,status);
        const actions = document.createElement('td');
        const save = document.createElement('button');save.type='button';save.className='secondary';save.textContent='Save date';
        const clear = document.createElement('button');clear.type='button';clear.className='secondary';clear.textContent='Clear date';
        const change = value => write('/api/incoming-stock/'+item.order_id,'PUT',{
          request_id:crypto.randomUUID(),expected_order_version:item.order_version,expected_revision:item.revision,arrival_date:value});
        save.addEventListener('click',()=>{
          if (busy || pending || !input.reportValidity()) return;
          if (!input.value) {show('purchasing-error','Enter an expected date or use Clear date.');return;}
          return change(input.value);
        });
        clear.addEventListener('click',()=>{if (!busy && !pending) return change(null);});
        actions.append(save,clear);rowControls.push(input,save,clear);
        row.append(order,goods,dateCell,actions);body.append(row);
      }
    } catch (error) {if(version===listVersion)show('purchasing-error',error.message);}
    controls();
  }

  async function refreshForecast() {
    signal('resupply-forecast-refresh');
  }

  async function write(path,method,body) {
    if (busy || pending) return;
    pending={path,method,body};
    await commit();
  }

  async function commit() {
    if (busy || !pending) return;
    busy=true;controls();show('purchasing-error');show('purchasing-feedback');
    let result=null;
    try {
      result=await api(pending.path,{method:pending.method,body:JSON.stringify(pending.body)});
    } catch (error) {
      if ([400,404,409,422].includes(error.status)) {
        pending=null;show('purchasing-error',error.message);
      } else {
        try {result=await api('/api/forecast-planning/requests/'+pending.body.request_id);} catch (_) {}
        if (!result) show('purchasing-error','Change is not confirmed. Retry same change; the original values and request ID stay locked.');
      }
    }
    if (result) {
      pending=null;show('purchasing-feedback',result.message);
      signal('resupply-planning-changed');
    }
    busy=false;controls();
    if (!pending) {queued=false;await loadIncoming();await refreshForecast();}
  }

  el('impact-preview').addEventListener('click',async()=>{
    if (busy || pending || previewBusy || !matches() || !context.report_current) return;
    const fields=['lead-time','coverage-days','buffer-days','purchase-budget'];
    const invalid=fields.find(id=>el(id).checkValidity&&!el(id).checkValidity());
    if(invalid) {
      clearPreview();
      if(window.resupplyNavigate&&!window.resupplyNavigate('purchasing'))return;
      el(invalid).reportValidity();return;
    }
    if (fields.some(id=>!el(id).reportValidity()) || (simulation() && !el('impact-demo-stock').reportValidity())) return;
    const query={product_id:context.product.id,run_id:context.run_id,
      lead_time_days:el('lead-time').value,coverage_days:el('coverage-days').value,buffer_days:el('buffer-days').value,
      budget:el('purchase-budget').value,example_stock:el('impact-demo-stock').value};
    const version=++previewVersion;
    previewBusy=true;controls();show('purchasing-error');
    try {
      const data=await api('/api/forecast-planning/preview?'+new URLSearchParams(query));
      if(version!==previewVersion || !matches() || data.run_id!==context.run_id)return;
      preview=data;el('impact-result').hidden=false;
      el('impact-summary').textContent=`${data.demo?'DEMO · ':''}Projected demand: ${num(data.demand_units)} units · Suggested purchase: ${data.suggested_quantity} · Budget can cover: ${data.budget_quantity} units (${money(data.budget_cost)}).`;
      el('impact-detail').textContent=`Stock used: ${data.stock} · Supplier delivery: ${data.lead_time_days} days · Coverage: ${data.coverage_days} · Buffer: ${data.buffer_days} · Incoming counted: ${data.incoming_units}. `+
        `${data.delivery_risk?'Delivery risk: stock may run out before normal supplier arrival. ':''}${data.message}`;
      const rows=el('impact-rows');rows.replaceChildren();
      for(const item of data.daily){
        const row=document.createElement('tr');
        ['date','demand_units','incoming_units','balance_before_arrival'].forEach((field,i)=>{
          const cell=document.createElement('td');cell.textContent=i?num(item[field]):item[field];if(i)cell.className='number';row.append(cell);
        });rows.append(row);
      }
    }catch(error){if(version===previewVersion){clearPreview();show('purchasing-error',error.message);}}
    finally{previewBusy=false;controls();}
  });
  el('impact-use').addEventListener('click',()=>{
    if (el('impact-use').disabled || !matches() || context.source!==shopSource || !preview || preview.run_id!==context.run_id) return;
    return write('/api/forecast-planning/review','POST',{request_id:crypto.randomUUID(),product_id:context.product.id,
      action:'use',expected_run_id:context.run_id,expected_revision:context.planning.review_revision});
  });
  el('impact-average').addEventListener('click',()=>{
    if(el('impact-average').disabled || !matches())return;
    return write('/api/forecast-planning/review','POST',{request_id:crypto.randomUUID(),product_id:context.product.id,
      action:'average',expected_run_id:null,expected_revision:context.planning.review_revision});
  });
  el('purchasing-retry').addEventListener('click',commit);
  el('incoming-refresh').addEventListener('click',()=>loadIncoming());
  for(const id of ['forecast-product','forecast-source'])el(id).addEventListener('change',()=>{context=null;clearPreview();});
  for(const id of ['lead-time','coverage-days','buffer-days','purchase-budget','impact-demo-stock'])el(id).addEventListener('input',clearPreview);
  window.addEventListener('resupply-forecast-view-changed',event=>view(event.detail));
  window.addEventListener('resupply-catalog-changed',()=>loadIncoming());
  window.addEventListener('resupply-orders-changed',()=>loadIncoming());
  window.addEventListener('resupply-planning-changed',()=>loadIncoming());
  loadIncoming();controls();signal('resupply-forecast-refresh');
})();
