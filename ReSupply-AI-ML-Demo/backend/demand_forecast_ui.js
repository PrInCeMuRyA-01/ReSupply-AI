(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const product = el('forecast-product'), source = el('forecast-source');
  const train = el('forecast-train'), refresh = el('forecast-refresh');
  let busy = false, pending = null, ready = false, readVersion = 0, catalogVersion = 0, queued = false;
  const number = value => Number(value).toLocaleString('en-US', {maximumFractionDigits:2});

  async function api(path, options = {}) {
    const response = await window.resupplyFetch(path, {cache:'no-store', ...options,
      headers:{'Content-Type':'application/json', ...options.headers}});
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Refresh and try again.');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function errorMessage(message = '') {
    el('forecast-error').textContent = message;
    el('forecast-error').hidden = !message;
  }

  function controls() {
    const locked = busy || !!pending || !!window.resupplyPurchasingBusy;
    product.disabled = locked || !product.value;
    source.disabled = locked;
    refresh.disabled = busy || !product.value;
    train.disabled = busy || !!window.resupplyPurchasingBusy || (!pending && !ready);
    train.textContent = busy ? 'Training…' : pending ? 'Retry same training' : 'Train & forecast';
    el('forecast-form').setAttribute('aria-busy', String(busy));
  }

  function clearResult(message) {
    ready = false;
    el('forecast-results').hidden = true;
    el('forecast-readiness').textContent = message;
    el('forecast-coverage').textContent = '';
    controls();
  }

  function tableRows(id, rows, fields) {
    const body = el(id);
    body.replaceChildren();
    for (const row of rows) {
      const tr = document.createElement('tr');
      fields.forEach((field, index) => {
        const cell = document.createElement('td');
        cell.textContent = index === 0 ? row[field] : number(row[field]);
        if (index) cell.className = 'number';
        tr.append(cell);
      });
      body.append(tr);
    }
  }

  function chart(rows) {
    const svg = el('forecast-chart');
    svg.replaceChildren();
    const node = (tag, attributes, text) => {
      const item = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, String(value));
      if (text !== undefined) item.textContent = text;
      svg.append(item);
      return item;
    };
    const max = Math.max(1, ...rows.flatMap(r => [r.model_units, r.baseline_units, r.selected_units]));
    const x = index => 55 + index * 103;
    const y = value => 188 - value / max * 153;
    [0, .5, 1].forEach(fraction => {
      node('line', {x1:55,x2:673,y1:y(max*fraction),y2:y(max*fraction),stroke:'#e0e9e2'});
      node('text', {x:45,y:y(max*fraction)+4,'text-anchor':'end',fill:'#647268','font-size':11}, number(max*fraction));
    });
    node('text', {x:55,y:20,fill:'#647268','font-size':11}, 'Expected units / day');
    for (const [field, color, width, dashed] of [
      ['model_units','#246647',2,false], ['baseline_units','#bb873d',2,true], ['selected_units','#5f60bd',3,true]]) {
      const attributes = {points:rows.map((r,i) => `${x(i)},${y(r[field])}`).join(' '),fill:'none',stroke:color,'stroke-width':width};
      if (dashed) attributes['stroke-dasharray'] = field === 'selected_units' ? '3 4' : '8 4';
      node('polyline', attributes);
    }
    rows.forEach((row,index) => {
      const circle = node('circle', {cx:x(index),cy:y(row.selected_units),r:4,fill:'#5f60bd'});
      const title = document.createElementNS('http://www.w3.org/2000/svg','title');
      title.textContent = `${row.date}: ${number(row.selected_units)} selected units`;
      circle.append(title);
      node('text', {x:x(index),y:213,'text-anchor':'middle',fill:'#647268','font-size':11}, row.date.slice(5));
    });
  }

  function render(data) {
    ready = data.ready;
    el('forecast-readiness').textContent = data.reason;
    const c = data.coverage;
    el('forecast-coverage').textContent = `${data.product.sku} · ${c.consecutive_days} consecutive ${data.source} days · ${c.stockout_days} stockout days excluded` +
      (c.last_day ? ` · Latest usable date: ${c.last_day} (IST)` : '');
    el('forecast-notice').textContent = data.message;
    const r = data.report;
    window.dispatchEvent?.(new CustomEvent('resupply-forecast-view-changed', {detail:data}));
    el('forecast-results').hidden = !r || !data.report_current;
    if (!r || !data.report_current) { controls(); return; }
    el('forecast-total').textContent = `${number(r.selected_total_units)} units`;
    el('forecast-period').textContent = `${r.items[0].date} → ${r.items.at(-1).date}`;
    el('forecast-model-error').textContent = number(r.evaluation.model_mae);
    el('forecast-baseline-error').textContent = number(r.evaluation.baseline_mae);
    el('forecast-test-days').textContent = `${r.evaluation.test_days} tested days · ${r.evaluation.folds.length} time-based splits`;
    const method = r.selected_method === 'random_forest' ? 'ML forecast selected' : 'Average forecast selected';
    el('forecast-choice').textContent = `${r.demo ? 'DEMO · synthetic data. ' : 'Actual shop data. '}${method}. ${r.selection_reason}`;
    el('forecast-stock-gap').textContent = window.resupplyWorkspace?.mode === 'demo' ? 'DEMO shop stock: '+data.product.stock+' units. Preview purchase impact, then review this synthetic forecast for demo purchasing.' : r.demo ? 'Demo simulation only. Import actual shop history for a real stock comparison.' :
      `Stock now: ${data.advice.stock_now} units · 7-day gap: ${data.advice.seven_day_gap} units. ${data.advice.message}`;
    tableRows('forecast-rows', r.items, ['date','model_units','baseline_units','selected_units']);
    tableRows('forecast-test-rows', r.evaluation.items, ['date','observed_units','model_units','baseline_units']);
    chart(r.items);
    el('forecast-validation').textContent = `Trained on ${r.training_days} completed days (${r.data_start} → ${r.data_end}). ` +
      `Each split trains on older days, then predicts later dates without seeing their sales. MAE means average absolute error in units/day; lower is better. ` +
      `${r.bridge_days} unobserved date(s), including today's partial day, are estimated before tomorrow's forecast. Those estimates are not saved as sales. ` +
      'Model features: weekday, previous day, same weekday last week, last 7-day and 14-day averages.';
    el('forecast-limitations').textContent = r.limitations;
    controls();
  }

  async function loadStatus(force = false) {
    if (busy && !force) { queued = true; return; }
    if (!product.value) return;
    const version = ++readVersion, selected = product.value, selectedSource = source.value;
    clearResult('Checking daily sales data…');
    try {
      const data = await api(`/api/forecast?product_id=${selected}&source=${selectedSource}`);
      if (version !== readVersion || product.value !== selected || source.value !== selectedSource) return;
      render(data);
      errorMessage();
    } catch (error) {
      if (version !== readVersion) return;
      clearResult('Status could not load. Refresh status to try again.');
      errorMessage(error.message);
    }
  }

  async function loadProducts() {
    if (busy || pending || window.resupplyPurchasingBusy) { queued = true; return; }
    const version = ++catalogVersion;
    try {
      const products = await api('/api/products');
      if (version !== catalogVersion || busy || pending) { queued = true; return; }
      const previous = product.value;
      product.replaceChildren();
      for (const item of products) {
        const option = document.createElement('option');
        option.value = String(item.id);
        option.textContent = `${item.name} · ${item.sku}`;
        product.append(option);
      }
      product.value = products.some(item => String(item.id) === previous) ? previous : products.length ? String(products[0].id) : '';
      if (!products.length) { clearResult('Add a product, then import or save daily totals.'); return; }
      await loadStatus();
    } catch (error) { errorMessage(error.message); }
    controls();
  }

  async function savedRequest() {
    if (!pending) return null;
    try { return await api(`/api/forecast/requests/${pending.request_id}`); }
    catch (error) { if (error.status === 404) return null; throw error; }
  }

  async function runTraining(event) {
    event.preventDefault();
    if (busy || window.resupplyPurchasingBusy || (!pending && !ready)) return;
    pending ??= {request_id:crypto.randomUUID(), product_id:Number(product.value), source:source.value};
    const payload = pending;
    busy = true;
    ++readVersion; ++catalogVersion;
    controls(); errorMessage();
    el('forecast-readiness').textContent = 'Training model and comparing predictions with the sales average…';
    el('forecast-results').hidden = true;
    try {
      const data = await api('/api/forecast/train', {method:'POST',body:JSON.stringify(payload)});
      pending = null;
      render(data);
    } catch (error) {
      if ([400,404,409,422,503].includes(error.status)) {
        pending = null;
        await loadStatus(true);
        errorMessage(error.message);
      } else {
        let saved = null;
        try { saved = await savedRequest(); } catch (_) { /* Keep the same ID available for retry. */ }
        if (saved) { pending = null; render(saved); }
        else {
          el('forecast-readiness').textContent = 'Result is not confirmed. Retry the same training request or check its status.';
          errorMessage('Training response was interrupted. Your product and source stay locked until the saved result is confirmed.');
        }
      }
    } finally {
      busy = false;
      controls();
      if (queued && !pending) { queued = false; await loadProducts(); }
    }
  }

  product.addEventListener('change', () => loadStatus());
  source.addEventListener('change', () => loadStatus());
  el('forecast-form').addEventListener('submit', runTraining);
  refresh.addEventListener('click', async () => {
    if (busy) return;
    if (!pending) { await loadProducts(); return; }
    busy = true; controls(); errorMessage();
    try {
      const saved = await savedRequest();
      if (saved) { pending = null; render(saved); }
      else errorMessage('No saved result yet. Retry same training; the request ID is unchanged.');
    } catch (error) { errorMessage(error.message); }
    finally { busy = false; controls(); if (queued && !pending) { queued = false; await loadProducts(); } }
  });
  window.addEventListener('resupply-catalog-changed', loadProducts);
  window.addEventListener('resupply-history-changed', loadProducts);
  window.addEventListener('resupply-purchasing-lock', () => {
    controls();
    if (!window.resupplyPurchasingBusy && queued && !pending && !busy) { queued = false; loadProducts(); }
  });
  window.addEventListener('resupply-forecast-refresh', () => loadStatus());
  loadProducts();
})();
