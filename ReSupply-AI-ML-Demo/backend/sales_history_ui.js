/* Daily history is separate from current-stock sales and payment operations. */
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const product = byId('history-product'), range = byId('history-range');
  const day = byId('history-date'), units = byId('history-units'), source = byId('history-source');
  const stockout = byId('history-stockout'), dayForm = byId('history-day-form');
  const save = byId('history-save'), reloadDay = byId('history-reload-day');
  const file = byId('history-file'), previewButton = byId('history-preview'), commitButton = byId('history-commit');
  const feedback = byId('history-feedback'), error = byId('history-error');
  let busy = false, dayContext = null, preview = null, csvText = '';
  let pendingSave = null, pendingImport = null;
  let catalogRead = 0, historyRead = 0, dayRead = 0, fileRead = 0;

  function message(element, text) {element.textContent = text; element.hidden = !text;}
  async function api(url, options = {}) {
    const response = await window.resupplyFetch(url, {cache:'no-store', ...options});
    const result = await response.json();
    if (!response.ok) {
      const detail = typeof result.detail === 'string' ? result.detail
        : Array.isArray(result.detail) ? result.detail.map(item => item.msg).join('; ') : 'Sales history request failed.';
      const issue = new Error(detail); issue.status = response.status; throw issue;
    }
    return result;
  }
  function controls() {
    const locked = busy || !!pendingSave || !!pendingImport;
    for (const item of [product, range, day, units, source, stockout, file]) item.disabled = locked || !product.value;
    for (const item of [units, source, stockout]) item.disabled = locked || !dayContext;
    // The selector remains available to choose the first product after loading.
    product.disabled = locked || !product.children.length || !product.value;
    save.disabled = busy || !!pendingImport || (!pendingSave && !dayContext);
    save.textContent = pendingSave ? 'Retry same daily total' : 'Save full-day total';
    previewButton.disabled = locked || !csvText;
    commitButton.hidden = !pendingImport && !preview?.valid;
    commitButton.disabled = busy || !!pendingSave;
    commitButton.textContent = pendingImport ? 'Retry same import' : 'Confirm import';
    reloadDay.disabled = locked || !product.value;
  }
  function links() {
    for (const [id, path] of [['history-template','template'],['history-demo','demo'],['history-export','export']]) {
      const anchor = byId(id);
      anchor.hidden = !product.value;
      anchor.href = window.resupplyUrl('/api/sales-history/' + path + '?product_id=' + product.value);
    }
  }
  async function loadCatalog() {
    const generation = ++catalogRead, previous = product.value;
    try {
      const products = await api('/api/products');
      if (generation !== catalogRead) return;
      product.replaceChildren();
      for (const item of products) {
        const option = document.createElement('option'); option.value = String(item.id);
        option.textContent = item.name + ' · ' + item.sku; product.append(option);
      }
      product.value = products.some(item => String(item.id) === previous) ? previous : products.length ? String(products[0].id) : '';
      links(); controls();
      if (product.value) {
        await loadHistory();
        if (!dayContext || previous !== product.value) await loadDay();
      } else {
        dayContext = null; byId('history-rows').replaceChildren();
        byId('history-description').textContent = 'Add a product to start recording daily history.';
        controls();
      }
    } catch (issue) {message(error, issue.message || 'Could not load history products.');}
  }
  async function loadHistory() {
    if (!product.value) return;
    const generation = ++historyRead, selected = product.value, selectedRange = range.value;
    try {
      const data = await api('/api/sales-history?' + new URLSearchParams({product_id:selected, days:selectedRange}));
      if (generation !== historyRead || selected !== product.value || selectedRange !== range.value) return;
      const yesterday = new Date(data.shop_date + 'T12:00:00Z'); yesterday.setUTCDate(yesterday.getUTCDate()-1);
      day.max = yesterday.toISOString().slice(0,10);
      if (!day.value) day.value = day.max;
      for (const [id, key] of [['history-actual','actual_days'],['history-demo-days','demo_days'],['history-missing','missing_days'],
                              ['history-zero','zero_sales_days'],['history-stockouts','stockout_days'],['history-unconfirmed','unconfirmed_days']]) {
        byId(id).textContent = String(data[key]);
      }
      byId('history-description').textContent = data.sku + ' · ' + data.start_date + ' to ' + data.end_date + ' (IST). ' + data.eligible_actual_days + ' actual days available without stockout flags.';
      byId('history-quality-message').textContent = data.message;
      const rows = byId('history-rows'); rows.replaceChildren();
      for (const item of [...data.items].reverse()) {
        const row = document.createElement('tr');
        const state = item.source === 'demo' ? 'Demo · synthetic' : ({complete:'Actual · full day',stockout:'Stockout flagged',
          logged_only:'Logged only · confirm total',missing:'Missing · unknown',today_partial:'Today · partial'})[item.status];
        for (const value of [item.sale_date, item.units_sold === null ? '—' : String(item.units_sold), state,
                             item.stockout ? 'Yes' : item.source ? 'No flag' : 'Unknown']) {
          const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
        }
        rows.append(row);
      }
    } catch (issue) {
      if (generation !== historyRead) return;
      byId('history-rows').replaceChildren(); byId('history-description').textContent = 'History unavailable. Refresh to retry.';
      for (const id of ['history-actual','history-demo-days','history-missing','history-zero','history-stockouts','history-unconfirmed']) byId(id).textContent = '—';
      message(error, issue.message);
    }
  }
  async function loadDay(force = false) {
    if ((busy && force !== true) || pendingSave || pendingImport || !product.value || !day.value) return;
    const generation = ++dayRead, selected = product.value, date = day.value;
    dayContext = null; units.value = '';
    byId('history-day-hint').textContent = 'Loading this day’s saved total…';
    controls();
    try {
      const data = await api('/api/sales-history/day?' + new URLSearchParams({product_id:selected, sale_date:date}));
      if (generation !== dayRead || selected !== product.value || date !== day.value ||
          (force !== true && (busy || pendingSave || pendingImport))) return;
      dayContext = data;
      units.value = data.units_sold === null ? (data.logged_units > 0 ? String(data.logged_units) : '') : String(data.units_sold);
      source.value = data.source; stockout.checked = data.stockout;
      byId('history-day-hint').textContent = data.revision
        ? 'Saved full-day total: ' + data.units_sold + '. Saving replaces this day’s total after checking its version.'
        : data.logged_units ? data.logged_units + ' units already logged. Enter the full-day total including those sales.'
        : 'No full-day total saved. Enter 0 only if you know there were no sales.';
    } catch (issue) {
      if (generation === dayRead) message(error, issue.message);
    } finally {if (generation === dayRead) controls();}
  }
  async function afterSave(result, kind) {
    pendingSave = pendingImport = null;
    if (kind === 'import') {
      preview = null; byId('history-import-panel').hidden = true;
      message(feedback, (result.replayed ? 'Import already confirmed. ' : '') + result.inserted + ' rows added; ' + result.unchanged + ' already saved. Inventory is unchanged.');
    } else {
      message(feedback, result.replayed ? 'This daily total was already saved. Inventory is unchanged.' : 'Full-day total saved. Inventory is unchanged.');
    }
    dayContext = null; controls();
    await loadHistory(); await loadDay(true);
    window.dispatchEvent(new Event('resupply-history-changed'));
  }
  async function recover(pending) {
    try {return await api('/api/sales-history/requests/' + pending.body.request_id);}
    catch {return null;}
  }
  async function sendPending(pending, kind) {
    if (busy) return;
    busy = true; message(error, ''); controls();
    try {
      const result = await api(pending.url, {method:pending.method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(pending.body)});
      await afterSave(result, kind);
    } catch (issue) {
      const confirmed = await recover(pending);
      if (confirmed) {await afterSave(confirmed, kind);}
      else {
        const known = [400,404,409,422].includes(issue.status);
        if (known) {
          if (kind === 'day') {pendingSave = null; dayContext = null;}
          else {pendingImport = null; preview = null;}
        }
        message(error, known ? issue.message + (kind === 'day' ? ' Click Reload day.' : ' Preview the CSV again.')
          : 'Result is unconfirmed. Retry the same request; its original values are kept.');
      }
    } finally {busy = false; controls();}
  }
  dayForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (save.disabled || busy) return;
    if (!pendingSave) {
      if (!dayContext || !dayForm.reportValidity()) return;
      const quantity = Number(units.value);
      if (units.value.trim() === '' || !Number.isInteger(quantity) || quantity < 0 || quantity > 1000000) {
        message(error, 'Enter a whole-number daily total. Blank is not zero.'); return;
      }
      pendingSave = {url:'/api/sales-history/day', method:'PUT', body:{request_id:crypto.randomUUID(),
        product_id:Number(product.value), sale_date:day.value, units_sold:quantity,
        source:source.value, stockout:!!stockout.checked, expected_revision:dayContext.revision}};
    }
    await sendPending(pendingSave, 'day');
  });
  file.addEventListener('change', async () => {
    const generation = ++fileRead;
    csvText = ''; preview = null; byId('history-import-panel').hidden = true; controls();
    const chosen = file.files?.[0];
    if (!chosen) return;
    if (chosen.size > 300000) {message(error, 'Use a UTF-8 CSV of at most 300 KB.'); return;}
    try {
      const text = await chosen.text();
      if (generation !== fileRead) return;
      csvText = text; message(error, ''); controls();
    } catch {message(error, 'Could not read this CSV. Save it as UTF-8 and choose it again.');}
  });
  previewButton.addEventListener('click', async () => {
    if (previewButton.disabled || busy) return;
    busy = true; message(error, ''); controls();
    preview = null; byId('history-import-panel').hidden = true;
    try {
      preview = await api('/api/sales-history/import/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({csv_text:csvText})});
      byId('history-import-panel').hidden = false;
      byId('history-import-summary').textContent = preview.new_rows + ' new · ' + preview.unchanged_rows + ' already saved · ' + preview.invalid_rows + ' invalid. ' + preview.demo_rows + ' demo rows. Preview has not changed sales totals or inventory.';
      const rows = byId('history-preview-rows'); rows.replaceChildren();
      for (const item of preview.rows) {
        const row = document.createElement('tr');
        for (const value of [item.line, item.sale_date, item.sku, item.units_sold === null ? 'Invalid' : item.units_sold,
                             item.source + (item.stockout ? ' · stockout' : ''), item.errors.length ? item.errors.join(' ') : item.status]) {
          const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell);
        }
        rows.append(row);
      }
      if (!preview.valid) message(error, 'Fix the listed CSV rows and preview again. No daily totals were imported.');
    } catch (issue) {message(error, issue.message);}
    finally {busy = false; controls();}
  });
  commitButton.addEventListener('click', async () => {
    if (commitButton.disabled || busy || (!pendingImport && !preview?.valid)) return;
    if (!pendingImport) pendingImport = {url:'/api/sales-history/import/commit', method:'POST',
      body:{request_id:crypto.randomUUID(), preview_id:preview.preview_id}};
    await sendPending(pendingImport, 'import');
  });
  product.addEventListener('change', async () => {dayContext = null; links(); await loadHistory(); await loadDay();});
  range.addEventListener('change', loadHistory);
  day.addEventListener('change', loadDay);
  reloadDay.addEventListener('click', loadDay);
  byId('history-refresh').addEventListener('click', async () => {
    if (busy) return;
    const pending = pendingSave || pendingImport;
    if (pending) {
      busy = true; controls();
      try {
        const confirmed = await recover(pending);
        if (confirmed) await afterSave(confirmed, pendingSave ? 'day' : 'import');
        else message(error, 'This request is not confirmed yet. Retry the same request.');
      } finally {busy = false; controls();}
    } else {message(error, ''); await loadCatalog(); await loadDay();}
  });
  window.addEventListener('resupply-catalog-changed', () => {if (!busy && !pendingSave && !pendingImport) loadCatalog();});
  range.value = range.value || '90';
  controls(); loadCatalog();
})();
