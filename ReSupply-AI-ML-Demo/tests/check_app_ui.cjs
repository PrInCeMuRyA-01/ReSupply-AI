const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {randomUUID} = require('node:crypto');
const html = fs.readFileSync(require('node:path').resolve(__dirname,'../backend/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
const elements = {};
let focusedElement;
function element() {
  return {
    dataset: {}, value: '', textContent: '', className: '', hidden: false,
    disabled: false, isConnected: true, children: [], handlers: {},
    append(...children) {this.children.push(...children)},
    replaceChildren() {
      const detach = child => {child.isConnected = false; child.children.forEach(detach)};
      this.children.forEach(detach); this.children = [];
    },
    addEventListener(name, handler) {this.handlers[name] = handler},
    remove() {}, setAttribute() {}, focus() {focusedElement = this}, select() {},
    reportValidity() {return true}, reset() {},
    showModal() {this.open = true},
    close() {this.open = false; this.handlers.close?.()},
    querySelector(selector) {
      const match = selector.match(/data-(sale-product-id|product-id)="(\d+)"/);
      const key = match?.[1] === 'sale-product-id' ? 'saleProductId' : 'productId';
      const all = [];
      const visit = child => {all.push(child); child.children.forEach(visit)};
      visit(this);
      return all.find(child => child.dataset[key] === match?.[2]) || null;
    },
  };
}
for (const match of html.matchAll(/\bid="([^"]+)"/g)) elements[match[1]] = element();
const products = [{id: 1, sku: 'PEN-BLUE', name: 'Blue Pen', stock: 20, unit_cost: '0.90', currency: 'USD'}];
const sales = [];
const suppliers = [], quotes = [], sourcing = new Map();
const orders = [], draftReceipts = new Map(), approvalReceipts = new Map();
const draftPosts = [], approvalPosts = [];
let loseDraftReceiptOnce = false, loseApprovalReceiptOnce = false, stallApprovalOnce = false, releaseApproval;
let rejectApprovalOnce = false, holdOrderId = null, releaseOrderView;
let nextQuoteId = 1, failQuoteSaveOnce = false, failSelectionOnce = false;
let holdQuoteProduct = null, releaseQuoteRead;
const quoteWrites = [];
const receipts = new Map();
const saleRequests = [];
let loseReceiptOnce = false, badJsonOnce = false, stallNext = false, releaseRequest;
let failRestockOnce = false, holdRestockOnce = false, releaseRestock;
let failPurchaseOnce = false, holdPurchaseOnce = false, releasePurchase;
const restockQueries = [];
const purchaseQueries = [];
let NetworkError;
const jsonResponse = (value, ok = true) => ({ok, status: ok ? 200 : 409, json: async () => JSON.parse(JSON.stringify(value))});
function mockPlan(url) {
  const settings = Object.fromEntries([...url.searchParams].map(([key, value]) => [key, Number(value)]));
  const targetDays = settings.lead_time_days + settings.coverage_days + settings.buffer_days;
  const items = products.map(product => {
    const quote = quotes.find(item => item.id === sourcing.get(product.id));
    const supplier = quote ? suppliers.find(item => item.id === quote.supplier_id) : null;
    const lead = quote ? quote.lead_time_days : settings.lead_time_days;
    const itemTargetDays = lead + settings.coverage_days + settings.buffer_days;
    const price = quote ? quote.unit_cost : product.unit_cost;
    const units = sales.filter(record => record.product_id === product.id).reduce((sum, record) => sum + record.quantity, 0);
    const target = units ? units * itemTargetDays : null;
    const quantity = target === null ? null : Math.max(0, target - product.stock);
    return {
      product_id: product.id, name: product.name, sku: product.sku, stock: product.stock,
      unit_cost: price, supplier_id: supplier?.id || null, supplier_name: supplier?.name || null,
      quote_id: quote?.id || null, lead_time_days: lead, target_days: itemTargetDays,
      price_source: quote ? 'supplier_quote' : 'saved_product',
      history_status: units ? 'today_only' : 'no_history',
      window_start: units ? '2026-10-13' : null, window_end: units ? '2026-10-13' : null,
      average_daily_sales: units || null, days_used: units ? 1 : 0,
      units_sold: units, today_units: units, estimated_days_left: units ? product.stock / units : null,
      target_stock: target, suggested_quantity: quantity,
      estimated_cost: quantity === null ? null : (quantity * Number(price)).toFixed(2),
      status: product.stock === 0 ? 'out_of_stock' : !units ? 'no_history' : quantity > 0 ? 'restock' : 'enough_stock',
      reason: units ? "Today's sales are a partial-day estimate." : 'Record sales to estimate how much to buy.',
    };
  });
  return {...settings, shop_date: '2026-10-13', target_days: targetDays, items,
    selected_supplier_products: items.filter(item => item.quote_id !== null).length,
    suggested_products: items.filter(item => item.suggested_quantity > 0).length,
    estimated_total_cost: items.reduce((sum, item) => sum + Number(item.estimated_cost || 0), 0).toFixed(2)};
}
function quoteView(quote) {
  const supplier = suppliers.find(item => item.id === quote.supplier_id);
  const product = products.find(item => item.id === quote.product_id);
  return {...quote, supplier_name: supplier.name, contact: supplier.contact,
    sku: product.sku, product_name: product.name, selected: sourcing.get(quote.product_id) === quote.id,
    updated_at: '2026-10-13T10:00:00+00:00', currency: 'USD'};
}

let paypalConfigured = false, failSdkOnce = false, losePaymentReceiptOnce = false;
const sdkUrls = [], paypalPosts = [], cancelPosts=[];
let stallCancelOnce=false, loseCancelReceiptOnce=false, releaseCancel;
let buttonOptions, closedButtons = 0;
let loseSettlementReceiptOnce=false, loseReceivingReceiptOnce=false, stallSettlementOnce=false, releaseSettlement;
const receivePosts=[];
const fetch = async (path, options = {}) => {
  if (path === '/api/paypal/config') return jsonResponse({configured:paypalConfigured, client_id:paypalConfigured?'SANDBOX_PUBLIC_ID':null});
  const paymentPath = path.match(/^\/api\/orders\/(\d+)\/paypal\/(create|authorize|sync|capture|void)$/);
  if (paymentPath) {
    const order = orders.find(item=>item.id===Number(paymentPath[1]));
    if (paymentPath[2] !== 'sync') assert.equal(order.status,'approved');
    const body = options.body ? JSON.parse(options.body) : null;
    paypalPosts.push({orderId:order.id,operation:paymentPath[2],body});
    if (paymentPath[2] === 'create') {
      assert.equal(body.expected_version,order.version);
      assert.deepEqual(Object.keys(body),['expected_version']);
      order.payment ||= {state:'ready',amount:order.grand_total,paypal_order_id:order.id===2?'P1234567890':'P'+order.id,authorization_id:null,
        paypal_status:'CREATED',authorized_at:null,expires_at:null,message:'Sandbox checkout ready.',environment:'sandbox'};
      order.can_cancel = true;
      return jsonResponse({paypal_order_id:order.payment.paypal_order_id,payment:order.payment});
    }
    if (paymentPath[2] === 'authorize') {
      assert.deepEqual(Object.keys(body),['paypal_order_id']);
      assert.equal(body.paypal_order_id,order.payment.paypal_order_id);
      order.can_cancel = false; order.can_capture=true; order.can_void=true; order.can_receive=false;
      Object.assign(order.payment,{state:'authorized',authorization_id:'A1234567890',paypal_status:'COMPLETED',
        authorized_at:'2026-10-13T10:00:00Z',expires_at:'2026-11-11T10:00:00Z',message:'Test funds held. Payment has not been captured.'});
      if (losePaymentReceiptOnce) {losePaymentReceiptOnce=false; throw new NetworkError('Authorization response lost')}
    }
    if (paymentPath[2] === 'capture' || paymentPath[2] === 'void') {
      assert.deepEqual(Object.keys(body),['expected_version']);
      assert.equal(body.expected_version,order.version);
      if (stallSettlementOnce) {stallSettlementOnce=false; await new Promise(resolve=>{releaseSettlement=resolve})}
      if (paymentPath[2] === 'capture') {
        Object.assign(order.payment,{state:'captured',capture_id:'C1234567890',capture_status:'COMPLETED',message:'Sandbox payment captured.'});
        order.can_receive=true;
      } else {
        Object.assign(order.payment,{state:'voided',message:'Hold released.'});
        order.status='cancelled';order.version++;
      }
      order.can_capture=false;order.can_void=false;order.can_cancel=false;
      if (loseSettlementReceiptOnce) {loseSettlementReceiptOnce=false;throw new NetworkError('Settlement response lost')}
    }
    return jsonResponse(order);
  }
  const receivePath=path.match(/^\/api\/orders\/(\d+)\/receive$/);
  if (receivePath) {
    const order=orders.find(item=>item.id===Number(receivePath[1]));
    const body=JSON.parse(options.body);receivePosts.push(body);
    assert.deepEqual(Object.keys(body).sort(),['expected_version','request_id']);
    assert.equal(order.payment.state,'captured');assert.equal(body.expected_version,2);
    if (!order.receipt) {
      order.receipt={received_at:'2026-10-14T00:00:00Z',units:order.units,item_count:order.item_count,
        items:order.items.map(line=>{const product=products.find(item=>item.id===line.product_id);
          const before=product.stock;product.stock+=line.quantity;
          return {...line,stock_before:before,stock_after:product.stock};})};
      order.status='received';order.version++;order.received_at=order.receipt.received_at;order.can_receive=false;
    }
    if (loseReceivingReceiptOnce) {loseReceivingReceiptOnce=false;throw new NetworkError('Receiving response lost')}
    return jsonResponse({order,replayed:false});
  }

  if (path === '/api/orders') {
    if (options.method !== 'POST') return jsonResponse([...orders].reverse());
    const payload = JSON.parse(options.body);
    draftPosts.push(payload);
    if (draftReceipts.has(payload.request_id)) return jsonResponse({order: draftReceipts.get(payload.request_id), replayed: true});
    const planResponse = await fetch('/api/purchase-plan?' + new URLSearchParams(payload));
    const plan = await planResponse.json();
    const eligible = plan.items.filter(item => item.planned_quantity > 0);
    if (eligible.some(item => !item.quote_id)) return jsonResponse({detail: 'Select suppliers for planned products.'}, false);
    if (orders.some(order => order.status !== 'cancelled' && order.items.some(line => eligible.some(item => item.product_id === line.product_id)))) {
      return jsonResponse({detail: 'A product already has an open order. Review or cancel it first.'}, false);
    }
    const id = orders.length + 1;
    const order = {id, number: 'RS-' + String(id).padStart(6, '0'), status: 'draft', version: 1,
      created_at: '2026-10-13T10:00:00+00:00', approved_at: null, cancelled_at: null,
      source_date: '2026-10-13', budget: payload.budget, products_total: plan.planned_cost,
      shipping_cost: '0.00', tax_cost: '0.00', grand_total: plan.planned_cost,
      spending_limit: payload.budget, item_count: eligible.length, units: plan.planned_units,
      supplier_count: new Set(eligible.map(item => item.supplier_id)).size,
      lead_time_days: payload.lead_time_days, coverage_days: payload.coverage_days, buffer_days: payload.buffer_days,
      items: eligible.map(item => ({...item, quantity: item.planned_quantity, line_total: item.line_cost,
        quote_updated_at: '2026-10-13T10:00:00+00:00'}))};
    orders.push(order); draftReceipts.set(payload.request_id, order);
    if (loseDraftReceiptOnce) {loseDraftReceiptOnce = false; throw new NetworkError('Lost draft receipt after saving')}
    return jsonResponse({order, replayed: false});
  }
  const orderPath = path.match(/^\/api\/orders\/(\d+)(?:\/(approve|cancel))?$/);
  if (orderPath) {
    const order = orders.find(item => item.id === Number(orderPath[1]));
    assert.ok(order);
    if (!orderPath[2]) {
      if (holdOrderId === order.id) {holdOrderId = null; const view = JSON.parse(JSON.stringify(order)); return new Promise(resolve => {releaseOrderView = () => resolve(jsonResponse(view))})}
      return jsonResponse(order);
    }
    const payload = JSON.parse(options.body);
    if (orderPath[2] === 'cancel') {
      cancelPosts.push({orderId:order.id,...payload});
      if(stallCancelOnce) {stallCancelOnce=false; await new Promise(resolve=>{releaseCancel=resolve})}
      if(order.payment?.state==='authorized') return jsonResponse({detail:'Authorization hold exists.'},false);
      if(order.payment?.state==='ready') {order.payment.state='cancelled_unpaid'; order.payment.message='Order cancelled locally; no hold was authorized.'}
      order.can_cancel=false;
      if (order.status !== 'cancelled') {order.status = 'cancelled'; order.version++; order.cancelled_at = '2026-10-13T10:00:00+00:00'}
      if(loseCancelReceiptOnce) {loseCancelReceiptOnce=false; throw new NetworkError('Cancellation receipt lost')}
      return jsonResponse(order);
    }
    approvalPosts.push(payload);
    if (stallApprovalOnce) {stallApprovalOnce = false; await new Promise(resolve => {releaseApproval = resolve})}
    if (rejectApprovalOnce) {rejectApprovalOnce = false; return jsonResponse({detail: 'Supplier quote changed. Create a fresh draft.'}, false)}
    if (approvalReceipts.has(payload.request_id)) return jsonResponse({order, replayed: true});
    if (order.status !== 'draft' || payload.expected_version !== order.version) return jsonResponse({detail: 'Order state changed.'}, false);
    const total = Math.round(Number(order.products_total) * 100) + Math.round(Number(payload.shipping_cost) * 100) + Math.round(Number(payload.tax_cost) * 100);
    if (total > Math.round(Number(payload.spending_limit) * 100)) return jsonResponse({detail: 'Spending limit exceeded.'}, false);
    order.status = 'approved'; order.version++;
    order.shipping_cost = Number(payload.shipping_cost).toFixed(2); order.tax_cost = Number(payload.tax_cost).toFixed(2);
    order.spending_limit = payload.spending_limit; order.grand_total = (total / 100).toFixed(2);
    order.approved_at = '2026-10-13T10:00:00+00:00';
    approvalReceipts.set(payload.request_id, order.id);
    if (loseApprovalReceiptOnce) {loseApprovalReceiptOnce = false; throw new NetworkError('Lost approval receipt after commit')}
    return jsonResponse({order, replayed: false});
  }
  if (path === '/api/suppliers') {
    if (options.method === 'POST') {
      const payload = JSON.parse(options.body);
      const supplier = {...payload, id: suppliers.length + 1};
      suppliers.push(supplier); return jsonResponse(supplier);
    }
    return jsonResponse(suppliers);
  }
  const sourcePath = path.match(/^\/api\/products\/(\d+)\/(quotes|supplier-selection)$/);
  if (sourcePath) {
    const productId = Number(sourcePath[1]);
    if (sourcePath[2] === 'quotes') {
      if (options.method === 'PUT') {
        const payload = JSON.parse(options.body);
        quoteWrites.push(payload);
        if (failQuoteSaveOnce) {
          failQuoteSaveOnce = false;
          return jsonResponse({detail: 'Quote could not be saved.'}, false);
        }
        let quote = quotes.find(item => item.product_id === productId && item.supplier_id === payload.supplier_id);
        if (quote) Object.assign(quote, payload);
        else {quote = {...payload, id: nextQuoteId++, product_id: productId}; quotes.push(quote)}
        return jsonResponse(quoteView(quote));
      }
      const view = quotes.filter(quote => quote.product_id === productId)
        .sort((a, b) => Number(a.unit_cost) - Number(b.unit_cost) || a.lead_time_days - b.lead_time_days)
        .map(quoteView);
      if (holdQuoteProduct === productId) {
        holdQuoteProduct = null;
        return new Promise(resolve => {releaseQuoteRead = () => resolve(jsonResponse(view))});
      }
      return jsonResponse(view);
    }
    if (options.method === 'DELETE') {sourcing.delete(productId); return jsonResponse({status: 'cleared', product_id: productId})}
    if (failSelectionOnce) {failSelectionOnce = false; return jsonResponse({detail: 'Could not select this quote.'}, false)}
    const {quote_id} = JSON.parse(options.body);
    const quote = quotes.find(item => item.id === quote_id && item.product_id === productId);
    assert.ok(quote);
    sourcing.set(productId, quote_id);
    return jsonResponse(quoteView(quote));
  }
  if (path.startsWith('/api/purchase-plan?')) {
    const url = new URL(path, 'http://localhost');
    purchaseQueries.push(url.searchParams);
    if (failPurchaseOnce) {
      failPurchaseOnce = false;
      return jsonResponse({detail: 'Purchase plan temporarily unavailable.'}, false);
    }
    const restock = mockPlan(url);
    const budgetCents = Math.round(Number(url.searchParams.get('budget')) * 100);
    let remainingCents = budgetCents;
    const items = restock.items.map(item => {
      const product = products.find(p => p.id === item.product_id);
      const unitCents = Math.round(Number(item.unit_cost) * 100);
      const planned = item.suggested_quantity === null || unitCents === 0 ? 0
        : Math.min(item.suggested_quantity, Math.floor(remainingCents / unitCents));
      remainingCents -= planned * unitCents;
      return {...item, restock_status: item.status,
        planned_quantity: planned, deferred_quantity: item.suggested_quantity === null ? null : item.suggested_quantity - planned,
        line_cost: (planned * unitCents / 100).toFixed(2),
        allocation_status: item.suggested_quantity === null ? 'no_history' : unitCents === 0 ? 'price_required'
          : item.suggested_quantity === 0 ? 'not_needed' : planned === item.suggested_quantity ? 'included' : planned > 0 ? 'partial' : 'budget_short',
        reason: item.suggested_quantity === null ? 'Record sales before estimating a purchase quantity.' : 'Quantity is allocated within the budget.'};
    });
    const plan = {...restock, items, budget: (budgetCents / 100).toFixed(2),
      planned_cost: ((budgetCents - remainingCents) / 100).toFixed(2), remaining_budget: (remainingCents / 100).toFixed(2),
      planned_products: items.filter(item => item.planned_quantity > 0).length,
      planned_units: items.reduce((sum, item) => sum + item.planned_quantity, 0),
      deferred_products: items.filter(item => item.deferred_quantity > 0).length,
      price_check_products: items.filter(item => item.allocation_status === 'price_required').length,
      no_history_products: items.filter(item => item.allocation_status === 'no_history').length};
    plan.planned_without_supplier = items.filter(item => item.planned_quantity > 0 && item.quote_id === null).length;
    if (holdPurchaseOnce) {
      holdPurchaseOnce = false;
      return new Promise(resolve => {releasePurchase = () => resolve(jsonResponse(plan))});
    }
    return jsonResponse(plan);
  }
  if (path.startsWith('/api/restock?')) {
    const url = new URL(path, 'http://localhost');
    restockQueries.push(url.searchParams);
    if (failRestockOnce) {
      failRestockOnce = false;
      return jsonResponse({detail: 'Suggestions temporarily unavailable.'}, false);
    }
    const plan = mockPlan(url);
    if (holdRestockOnce) {
      holdRestockOnce = false;
      return new Promise(resolve => {releaseRestock = () => resolve(jsonResponse(plan))});
    }
    return jsonResponse(plan);
  }
  if (path === '/api/sales' && options.method === 'POST') {
    const input = JSON.parse(options.body);
    saleRequests.push(input);
    if (stallNext) {
      stallNext = false;
      await new Promise(resolve => {releaseRequest = resolve});
    }
    const product = products.find(p => p.id === input.product_id);
    let receipt;
    if (receipts.has(input.request_id)) {
      receipt = {...receipts.get(input.request_id), product: {...product}, replayed: true};
    } else {
      if (!Number.isInteger(input.quantity) || input.quantity <= 0 || input.quantity > product.stock) {
        return jsonResponse({detail: 'Not enough stock.'}, false);
      }
      product.stock -= input.quantity;
      const record = {id: sales.length + 1, product_id: product.id, sku: product.sku, name: product.name,
        quantity: input.quantity, stock_after: product.stock, sale_date: '2026-10-13', recorded_at: '2026-10-13T10:00:00+00:00'};
      sales.unshift(record);
      receipt = {sale: record, product: {...product}, replayed: false};
      receipts.set(input.request_id, receipt);
    }
    if (loseReceiptOnce) {
      loseReceiptOnce = false;
      throw new NetworkError('Connection lost after commit');
    }
    if (badJsonOnce) {
      badJsonOnce = false;
      return {ok: true, json: async () => {throw new SyntaxError('Incomplete response')}};
    }
    return jsonResponse(receipt);
  }
  if (path === '/api/products' && options.method === 'POST') {
    const product = {...JSON.parse(options.body), id: products.length + 1};
    products.push(product); return jsonResponse(product);
  }
  if (options.method === 'PATCH') {
    const {stock} = JSON.parse(options.body);
    products[0].stock = stock;
    return jsonResponse(products[0]);
  }
  if (path === '/api/products') return jsonResponse(products);
  if (path === '/api/sales') return jsonResponse(sales);
  throw new Error('Unexpected request ' + path);
};
const sandbox = {window:{}, document: {
  head:{append(tag) {
    sdkUrls.push(tag.src);
    if(failSdkOnce) {failSdkOnce=false; tag.onerror(); return}
    sandbox.window.paypal = {FUNDING:{PAYPAL:'paypal'},Buttons(options){buttonOptions=options;
      return {render:async target=>assert.equal(target,'#paypal-buttons'), close:async()=>{closedButtons++}};
    }};
    tag.onload();
  }},
  getElementById(id) {assert.ok(elements[id], id); return elements[id]},
  createElement: element,
}, fetch, Intl, console, URLSearchParams, crypto: {randomUUID}};
const voiceHooks={};
sandbox.window.addEventListener=(name,fn)=>{voiceHooks[name]=fn};
sandbox.window.resupplyFetch=fetch;
vm.createContext(sandbox);
NetworkError = vm.runInContext('TypeError', sandbox);
vm.runInContext(script, sandbox);
const flush = () => new Promise(resolve => setImmediate(resolve));
const saleButton = () => elements['product-rows'].children[0].children[4].children[1];
const stockButton = () => elements['product-rows'].children[0].children[4].children[0];
const submit = () => elements['sale-form'].handlers.submit({preventDefault() {}});
const setQuantity = value => {
  elements['sale-quantity'].value = String(value);
  elements['sale-quantity'].handlers.input();
};
(async () => {
  await flush();
  assert.equal(elements['sales-empty'].hidden, false);
  assert.equal(elements['restock-rows'].children.length, 1);
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, 'Need sales');
  assert.equal(elements['restock-count'].textContent, '0');
  assert.equal(elements['calculate-restock'].disabled, false);
  assert.equal(elements['purchase-rows'].children.length, 1);
  assert.equal(elements['purchase-rows'].children[0].children[1].textContent, 'Need sales');
  assert.equal(elements['purchase-used'].textContent, '$0.00');
  assert.equal(elements['purchase-remaining'].textContent, '$200.00');
  assert.equal(elements['build-plan'].disabled, false);
  assert.equal(elements['orders-empty'].hidden, false);
  assert.equal(elements['create-order'].disabled, true);
  saleButton().handlers.click();
  assert.equal(elements['sale-dialog'].open, true);
  assert.equal(elements['sale-quantity'].max, '20');
  setQuantity(3);
  assert.equal(elements['sale-preview'].textContent, 'Stock after this sale: 17');
  await submit();
  assert.equal(products[0].stock, 17);
  assert.equal(elements['sale-dialog'].open, false);
  assert.equal(elements['product-rows'].children[0].children[2].children[0].textContent, '17');
  assert.equal(elements['sales-rows'].children.length, 1);
  assert.equal(elements['sales-rows'].children[0].children[2].textContent, '3');
  assert.equal(elements['sales-rows'].children[0].children[3].textContent, '17');
  assert.equal(elements['sales-empty'].hidden, true);
  assert.equal(focusedElement, saleButton());
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, '19');
  assert.equal(elements['restock-cost'].textContent, '$17.10');
  assert.match(elements['restock-rows'].children[0].children[1].children[0].textContent, /Today's estimate/);
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '19');
  assert.equal(elements['purchase-used'].textContent, '$17.10');
  assert.equal(elements['purchase-remaining'].textContent, '$182.90');
  assert.equal(elements['create-order'].disabled, true);
  assert.match(elements['purchase-rows'].children[0].children[0].children[2].textContent, /Today's estimate/);
  elements['lead-time'].value = '2';
  elements['coverage-days'].value = '5';
  elements['buffer-days'].value = '1';
  const calculate = () => elements['restock-form'].handlers.submit({preventDefault() {}});
  await calculate();
  assert.equal(restockQueries.at(-1).get('lead_time_days'), '2');
  assert.equal(restockQueries.at(-1).get('coverage_days'), '5');
  assert.equal(restockQueries.at(-1).get('buffer_days'), '1');
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, '7');
  assert.equal(elements['restock-cost'].textContent, '$6.30');
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '7');
  assert.equal(elements['purchase-used'].textContent, '$6.30');
  assert.equal(purchaseQueries.at(-1).get('coverage_days'), '5');
  assert.match(elements['restock-summary'].textContent, /8 days of target stock/);
  assert.equal(products[0].stock, 17);
  assert.equal(sales.length, 1);

  saleButton().handlers.click();
  elements['cancel-sale'].handlers.click();
  assert.equal(saleRequests.length, 1);

  saleButton().handlers.click();
  setQuantity(2);
  loseReceiptOnce = true;
  await submit();
  assert.equal(products[0].stock, 15);
  assert.equal(elements['sale-dialog'].open, true);
  assert.match(elements['sale-error'].textContent, /Retry here without changing quantity/);
  assert.equal(elements['save-sale'].disabled, false);
  const retryId = saleRequests.at(-1).request_id;
  await submit();
  assert.equal(saleRequests.at(-1).request_id, retryId);
  assert.equal(products[0].stock, 15);
  assert.equal(sales.length, 2);
  assert.match(elements['sales-feedback'].textContent, /already saved/);

  saleButton().handlers.click();
  setQuantity(1);
  badJsonOnce = true;
  await submit();
  const badJsonId = saleRequests.at(-1).request_id;
  assert.match(elements['sale-error'].textContent, /Please retry the same request/);
  await submit();
  assert.equal(saleRequests.at(-1).request_id, badJsonId);
  assert.equal(products[0].stock, 14);
  assert.equal(sales.length, 3);

  saleButton().handlers.click();
  setQuantity(1);
  stallNext = true;
  const pending = submit();
  assert.equal(elements['save-sale'].disabled, true);
  assert.equal(elements['sale-quantity'].disabled, true);
  const requestCount = saleRequests.length;
  await submit();
  assert.equal(saleRequests.length, requestCount);
  let prevented = false;
  elements['sale-dialog'].handlers.cancel({preventDefault() {prevented = true}});
  elements['cancel-sale'].handlers.click();
  assert.equal(prevented, true);
  assert.equal(elements['sale-dialog'].open, true);
  releaseRequest();
  await pending;
  assert.equal(products[0].stock, 13);
  assert.notEqual(saleRequests.at(-1).request_id, badJsonId);

  stockButton().handlers.click();
  elements['new-stock'].value = '0';
  await elements['stock-form'].handlers.submit({preventDefault() {}});
  assert.equal(products[0].stock, 0);
  assert.equal(saleButton().disabled, true);
  assert.equal(sales.length, 4);
  assert.equal(elements['save-sale'].disabled, false);
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, '56');
  assert.equal(elements['restock-count'].textContent, '1');

  failRestockOnce = true;
  await calculate();
  assert.equal(elements['restock-rows'].children.length, 0);
  assert.equal(elements['restock-count'].textContent, '—');
  assert.equal(elements['restock-cost'].textContent, '—');
  assert.match(elements['restock-error'].textContent, /temporarily unavailable/);
  assert.equal(elements['purchase-rows'].children.length, 0);
  assert.equal(elements['purchase-used'].textContent, '—');
  assert.equal(elements['build-plan'].disabled, false);
  assert.equal(elements['calculate-restock'].disabled, false);
  await calculate();
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, '56');
  assert.equal(elements['restock-error'].hidden, true);

  stockButton().handlers.click();
  elements['new-stock'].value = '10';
  await elements['stock-form'].handlers.submit({preventDefault() {}});
  holdRestockOnce = true;
  const oldRefresh = elements['refresh-button'].handlers.click();
  await flush();
  assert.ok(releaseRestock);
  stockButton().handlers.click();
  elements['new-stock'].value = '20';
  await elements['stock-form'].handlers.submit({preventDefault() {}});
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, '36');
  releaseRestock();
  await oldRefresh;
  assert.equal(elements['restock-rows'].children[0].children[3].textContent, '36');
  assert.equal(elements['calculate-restock'].disabled, false);

  elements['sku'].value = 'NEW-PRODUCT';
  elements['name'].value = '<New Pen>';
  elements['stock'].value = '4';
  elements['unit-cost'].value = '1.25';
  await elements['product-form'].handlers.submit({preventDefault() {}});
  assert.equal(elements['restock-rows'].children.length, 2);
  assert.equal(elements['restock-rows'].children[1].children[0].textContent, '<New Pen>');
  assert.equal(elements['restock-rows'].children[1].children[3].textContent, 'Need sales');
  assert.equal(elements['purchase-rows'].children.length, 2);
  assert.equal(elements['purchase-rows'].children[1].children[0].textContent, '<New Pen>');
  const buildPurchase = () => elements['purchase-form'].handlers.submit({preventDefault() {}});
  elements['purchase-budget'].value = '10.00';
  await buildPurchase();
  assert.equal(purchaseQueries.at(-1).get('budget'), '10.00');
  assert.equal(purchaseQueries.at(-1).get('lead_time_days'), '2');
  assert.equal(purchaseQueries.at(-1).get('buffer_days'), '1');
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '11');
  assert.equal(elements['purchase-rows'].children[0].children[3].textContent, '25');
  assert.equal(elements['purchase-rows'].children[0].children[5].children[0].textContent, 'Partially covered');
  assert.equal(elements['purchase-used'].textContent, '$9.90');
  assert.equal(elements['purchase-remaining'].textContent, '$0.10');
  assert.equal(products[0].stock, 20);
  assert.equal(sales.length, 4);
  elements['purchase-budget'].value = '0.00';
  await buildPurchase();
  assert.equal(elements['purchase-used'].textContent, '$0.00');
  assert.equal(elements['purchase-units'].textContent, '0');
  assert.equal(elements['purchase-rows'].children[0].children[3].textContent, '36');

  elements['purchase-budget'].value = '10.00';
  failPurchaseOnce = true;
  await buildPurchase();
  assert.equal(elements['purchase-rows'].children.length, 0);
  assert.equal(elements['purchase-used'].textContent, '—');
  assert.match(elements['purchase-error'].textContent, /temporarily unavailable/);
  assert.equal(elements['build-plan'].disabled, false);
  await buildPurchase();
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '11');
  assert.equal(elements['purchase-error'].hidden, true);

  holdPurchaseOnce = true;
  const oldBudget = buildPurchase();
  assert.equal(elements['build-plan'].disabled, true);
  stockButton().handlers.click();
  elements['new-stock'].value = '50';
  await elements['stock-form'].handlers.submit({preventDefault() {}});
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '6');
  assert.equal(elements['purchase-used'].textContent, '$5.40');
  releasePurchase();
  await oldBudget;
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '6');
  assert.equal(elements['purchase-used'].textContent, '$5.40');

  holdPurchaseOnce = true;
  const oldBeforeFailure = buildPurchase();
  failRestockOnce = true;
  await calculate();
  releasePurchase();
  await oldBeforeFailure;
  assert.equal(elements['purchase-rows'].children.length, 0);
  assert.equal(elements['purchase-used'].textContent, '—');
  assert.equal(elements['build-plan'].disabled, false);
  await buildPurchase();
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '6');
  assert.equal(elements['quote-product'].value, '1');
  assert.equal(elements['quotes-empty'].hidden, false);
  assert.equal(elements['save-quote'].disabled, true);
  const add = async name => {
    elements['supplier-name'].value = name;
    elements['supplier-contact'].value = 'demo reference';
    await elements['supplier-form'].handlers.submit({preventDefault() {}});
  };
  await add('<Supplier A>');
  await add('Supplier B');
  assert.equal(elements['quote-supplier'].children.length, 2);
  assert.equal(elements['quote-supplier'].children[0].textContent, '<Supplier A>');
  assert.equal(elements['save-quote'].disabled, false);
  const saveSupplierQuote = async (supplierId, price, lead) => {
    elements['quote-supplier'].value = String(supplierId);
    elements['quote-supplier'].handlers.change();
    elements['quote-price'].value = price;
    elements['quote-delivery'].value = String(lead);
    await elements['quote-form'].handlers.submit({preventDefault() {}});
  };
  await saveSupplierQuote(1, '0.80', 4);
  await saveSupplierQuote(2, '0.95', 2);
  assert.equal(elements['quote-rows'].children.length, 2);
  assert.equal(elements['quote-rows'].children[0].children[0].textContent, '<Supplier A>');
  assert.equal(elements['quote-rows'].children[0].children[3].children[0].textContent, 'Lowest unit price');
  assert.equal(elements['quote-rows'].children[1].children[3].children[0].textContent, 'Fastest delivery');
  assert.equal(elements['purchase-used'].textContent, '$5.40');
  const choose = name => elements['quote-rows'].children.find(row => row.children[0].textContent === name).children[4].children[0];
  await choose('<Supplier A>').handlers.click();
  assert.equal(choose('<Supplier A>').textContent, 'Selected');
  assert.equal(choose('<Supplier A>').disabled, true);
  assert.equal(elements['purchase-used'].textContent, '$9.60');
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '12');
  assert.match(elements['purchase-rows'].children[0].children[0].children.at(-1).textContent, /Supplier: <Supplier A> · 4 days/);
  assert.equal(elements['quote-price'].value, '0.80');
  assert.equal(elements['quote-delivery'].value, '4');

  elements['quote-price'].value = '0.75';
  elements['quote-delivery'].value = '3';
  failQuoteSaveOnce = true;
  await elements['quote-form'].handlers.submit({preventDefault() {}});
  assert.match(elements['quote-form-error'].textContent, /could not be saved/);
  assert.equal(elements['quote-price'].value, '0.75');
  assert.equal(elements['quote-delivery'].value, '3');
  assert.equal(elements['purchase-used'].textContent, '$9.60');
  await elements['quote-form'].handlers.submit({preventDefault() {}});
  assert.equal(quotes.length, 2);
  assert.equal(elements['purchase-used'].textContent, '$9.75');
  assert.equal(elements['purchase-rows'].children[0].children[2].textContent, '13');
  assert.equal(elements['quote-form-error'].hidden, true);

  await choose('Supplier B').handlers.click();
  assert.equal(elements['purchase-used'].textContent, '$5.70');
  assert.equal(elements['quote-price'].value, '0.95');
  assert.equal(elements['quote-delivery'].value, '2');
  await elements['clear-supplier-selection'].handlers.click();
  assert.equal(elements['purchase-used'].textContent, '$5.40');
  assert.equal(elements['clear-supplier-selection'].disabled, true);
  assert.equal(sourcing.size, 0);
  await choose('Supplier B').handlers.click();

  elements['quote-product'].value = '2';
  await elements['quote-product'].handlers.change();
  assert.equal(elements['quote-rows'].children.length, 0);
  assert.equal(elements['quotes-empty'].hidden, false);
  await saveSupplierQuote(1, '0.25', 1);
  assert.equal(elements['quote-rows'].children.length, 1);
  assert.equal(elements['quote-rows'].children[0].children[1].textContent, '$0.25');
  assert.equal(elements['purchase-used'].textContent, '$5.70');

  holdQuoteProduct = 1;
  elements['quote-product'].value = '1';
  const oldQuotes = elements['quote-product'].handlers.change();
  elements['quote-product'].value = '2';
  await elements['quote-product'].handlers.change();
  releaseQuoteRead();
  await oldQuotes;
  assert.equal(elements['quote-product'].value, '2');
  assert.equal(elements['quote-rows'].children.length, 1);
  assert.equal(elements['quote-rows'].children[0].children[1].textContent, '$0.25');

  elements['quote-product'].value = '1';
  await elements['quote-product'].handlers.change();
  failSelectionOnce = true;
  await choose('<Supplier A>').handlers.click();
  assert.match(elements['quotes-error'].textContent, /Could not select/);
  assert.equal(choose('Supplier B').disabled, true);
  assert.equal(elements['purchase-used'].textContent, '$5.70');

  holdPurchaseOnce = true;
  const oldSupplierPlan = buildPurchase();
  await choose('<Supplier A>').handlers.click();
  assert.equal(elements['purchase-used'].textContent, '$9.75');
  releasePurchase();
  await oldSupplierPlan;
  assert.equal(elements['purchase-used'].textContent, '$9.75');
  assert.equal(products[0].stock, 50);
  assert.equal(products[0].unit_cost, '0.90');
  assert.equal(sales.length, 4);
  assert.equal(elements['create-order'].disabled, false);
  await elements['create-order'].handlers.click();
  assert.equal(orders.length, 1);
  assert.equal(elements['order-dialog'].open, true);
  assert.equal(elements['review-rows'].children[0].children[3].textContent, '$0.75');
  assert.equal(elements['review-rows'].children[0].children[2].textContent, '13');
  assert.equal(elements['review-grand-total'].textContent, '$9.75');
  const fee = (id, value) => {elements[id].value = value; elements[id].handlers.input()};
  fee('order-shipping', '0.50'); fee('order-tax', '0.00'); fee('order-limit', '10.00');
  assert.equal(elements['review-grand-total'].textContent, '$10.25');
  assert.equal(elements['approve-order'].disabled, true);
  assert.match(elements['review-limit-message'].textContent, /Exceeds/);
  fee('order-shipping', '0.001');
  assert.equal(elements['approve-order'].disabled, true);
  assert.equal(elements['review-grand-total'].textContent, '—');
  fee('order-shipping', '0.15'); fee('order-tax', '0.10');
  assert.equal(elements['review-grand-total'].textContent, '$10.00');
  assert.equal(elements['approve-order'].disabled, false);
  const approve = () => elements['order-review-form'].handlers.submit({preventDefault() {}});
  stallApprovalOnce = true; loseApprovalReceiptOnce = true;
  const approving = approve();
  assert.equal(elements['approve-order'].disabled, true);
  assert.equal(elements['close-review'].disabled, true);
  let modalDismissalPrevented = false;
  elements['order-dialog'].handlers.cancel({preventDefault() {modalDismissalPrevented = true}});
  assert.equal(modalDismissalPrevented, true);
  const postCount = approvalPosts.length;
  await approve();
  assert.equal(approvalPosts.length, postCount);
  releaseApproval(); await approving;
  assert.equal(orders[0].status, 'approved');
  assert.equal(elements['approve-order'].textContent, 'Retry approval');
  assert.equal(elements['order-shipping'].disabled, true);
  assert.equal(elements['order-tax'].disabled, true);
  assert.equal(elements['order-limit'].disabled, true);
  const approvalId = approvalPosts.at(-1).request_id;
  await approve();
  assert.equal(approvalPosts.at(-1).request_id, approvalId);
  assert.equal(orders[0].version, 2);
  assert.equal(elements['approve-order'].hidden, true);
  assert.equal(elements['review-grand-total'].textContent, '$10.00');
  assert.equal(elements['order-rows'].children[0].children[4].children[0].textContent, 'Approved');
  assert.equal(products[0].stock, 50);
  assert.equal(sales.length, 4);
  elements['close-review'].handlers.click();

  await saveSupplierQuote(1, '0.76', 3);
  await elements['order-rows'].children[0].children[5].children[0].handlers.click();
  assert.equal(elements['review-rows'].children[0].children[3].textContent, '$0.75');
  assert.equal(elements['order-shipping'].disabled, true);
  elements['close-review'].handlers.click();
  await elements['order-rows'].children[0].children[5].children[1].handlers.click();
  assert.equal(orders[0].status, 'cancelled');
  assert.equal(elements['order-rows'].children[0].children[4].children[0].textContent, 'Cancelled');

  loseDraftReceiptOnce = true;
  await elements['create-order'].handlers.click();
  assert.equal(orders.length, 2);
  assert.equal(elements['create-order'].textContent, 'Retry draft save');
  const draftId = draftPosts.at(-1).request_id;
  await elements['create-order'].handlers.click();
  assert.equal(draftPosts.at(-1).request_id, draftId);
  assert.equal(orders.length, 2);
  assert.equal(elements['order-dialog'].open, true);
  rejectApprovalOnce = true;
  await approve();
  assert.match(elements['review-error'].textContent, /fresh draft/);
  assert.equal(elements['order-shipping'].disabled, false);
  assert.equal(elements['approve-order'].textContent, 'Approve order');
  elements['close-review'].handlers.click();

  holdOrderId = 2;
  const oldView = elements['order-rows'].children[0].children[5].children[0].handlers.click();
  await elements['order-rows'].children[1].children[5].children[0].handlers.click();
  assert.equal(elements['order-review-status'].textContent, 'Cancelled');
  releaseOrderView(); await oldView;
  assert.equal(elements['order-review-status'].textContent, 'Cancelled');
  assert.equal(elements['approve-order'].hidden, true);

  // Step 10: exercise PayPal SDK callbacks with a mock browser/PayPal server.
  assert.equal(elements['paypal-checkout'].hidden,true);
  await elements['order-rows'].children[0].children[5].children[0].handlers.click();
  await approve();
  assert.equal(orders[1].status,'approved');
  assert.equal(elements['paypal-checkout'].hidden,false);
  assert.equal(elements['paypal-start'].hidden,false);
  await elements['paypal-start'].handlers.click();
  assert.match(elements['paypal-error'].textContent,/Setup pending/);
  assert.equal(sdkUrls.length,0);
  assert.equal(paypalPosts.length,0);
  paypalConfigured=true; failSdkOnce=true;
  await elements['paypal-start'].handlers.click();
  assert.match(elements['paypal-error'].textContent,/Could not load PayPal/);
  assert.equal(paypalPosts.length,0);
  await elements['paypal-start'].handlers.click();
  const sdkUrl = new URL(sdkUrls.at(-1));
  assert.equal(sdkUrl.origin,'https://www.paypal.com');
  assert.equal(sdkUrl.searchParams.get('intent'),'authorize');
  assert.equal(sdkUrl.searchParams.get('currency'),'USD');
  assert.equal(sdkUrl.searchParams.get('buyer-country'),'US');
  assert.equal(sdkUrl.searchParams.get('client-id'),'SANDBOX_PUBLIC_ID');
  assert.equal(buttonOptions.fundingSource,'paypal');
  assert.equal(elements['paypal-start'].hidden,true);
  const actions={resolve:()=>true,reject:()=>false};
  assert.equal(buttonOptions.onClick({},actions),true);
  assert.equal(elements['close-review'].disabled,true);
  let paymentDismissalPrevented=false;
  elements['order-dialog'].handlers.cancel({preventDefault(){paymentDismissalPrevented=true}});
  assert.equal(paymentDismissalPrevented,true);
  elements['close-review'].handlers.click();
  assert.equal(elements['order-dialog'].open,true);
  assert.equal(buttonOptions.onClick({},actions),false);
  const remoteId=await buttonOptions.createOrder();
  assert.equal(remoteId,'P1234567890');
  assert.equal(paypalPosts.at(-1).operation,'create');
  const savedCount=orders.length, stockBefore=products[0].stock, salesBefore=sales.length;
  await buttonOptions.onCancel();
  assert.equal(orders[1].status,'approved');
  assert.equal(orders[1].payment.state,'ready');
  assert.equal(elements['close-review'].disabled,false);
  assert.match(elements['paypal-error'].textContent,/does not cancel the saved order/);
  const failedCallbacks=buttonOptions;
  elements['paypal-error'].textContent='';
  await buttonOptions.onError({message:'PAYER_CANNOT_PAY token=PRIVATE_TOKEN email=buyer@example.com'});
  assert.match(elements['paypal-error'].textContent,/PAYER_CANNOT_PAY/);
  assert.doesNotMatch(elements['paypal-error'].textContent,/PRIVATE_TOKEN|buyer@example.com/);
  assert.equal(elements['paypal-start'].hidden,false);
  assert.equal(elements['close-review'].disabled,false);
  const beforeStale=paypalPosts.length;
  await failedCallbacks.onApprove({orderID:remoteId});
  assert.equal(paypalPosts.length,beforeStale);
  await elements['paypal-start'].handlers.click();
  assert.equal(buttonOptions.onClick({},actions),true);
  assert.equal(await buttonOptions.createOrder(),remoteId);
  losePaymentReceiptOnce=true;
  const oldCallbacks=buttonOptions;
  await buttonOptions.onApprove({orderID:remoteId});
  assert.equal(orders[1].payment.state,'authorized');
  assert.match(elements['paypal-payment-message'].textContent,/not captured/);
  assert.match(elements['paypal-ids'].textContent,/A1234567890/);
  assert.equal(elements['paypal-error'].hidden,true);
  assert.equal(elements['paypal-start'].hidden,true);
  assert.equal(elements['paypal-buttons'].hidden,true);
  assert.equal(elements['order-rows'].children[0].children[5].children.length,1);
  assert.equal(elements['close-review'].disabled,false);
  assert.ok(closedButtons>=1);
  const postsBeforeOldCallback=paypalPosts.length;
  await oldCallbacks.onApprove({orderID:remoteId});
  assert.equal(paypalPosts.length,postsBeforeOldCallback);
  elements['close-review'].handlers.click();
  await elements['order-rows'].children[0].children[5].children[0].handlers.click();
  assert.match(elements['paypal-payment-message'].textContent,/funds held/);
  assert.match(elements['paypal-ids'].textContent,/P1234567890/);
  await elements['paypal-refresh'].handlers.click();
  assert.equal(paypalPosts.at(-1).operation,'sync');
  assert.equal(orders.length,savedCount);
  assert.equal(products[0].stock,stockBefore);
  assert.equal(sales.length,salesBefore);
  console.log('PASS: PayPal setup, SDK load failure/retry, AUTHORIZE callbacks, cancel window, uncertain authorization recovery, saved hold, disabled order cancellation and unchanged inventory.');


  // Fixture: prior held order was externally voided; close it locally before an unpaid-order scenario.
  Object.assign(orders[1].payment,{state:'voided',message:'PayPal reports the hold was voided.'});
  orders[1].can_cancel=true;
  await elements['paypal-refresh'].handlers.click();
  await elements['cancel-unpaid-order'].handlers.click();
  assert.equal(orders[1].status,'cancelled');
  elements['close-review'].handlers.click();
  await buildPurchase();
  await elements['create-order'].handlers.click();
  await approve();
  assert.equal(orders[2].status,'approved');
  await elements['paypal-start'].handlers.click();
  buttonOptions.onClick({},actions);
  const unpaidRemote=await buttonOptions.createOrder();
  await buttonOptions.onCancel();
  assert.equal(orders[2].payment.state,'ready');
  assert.equal(elements['cancel-unpaid-order'].hidden,false);
  assert.equal(elements['cancel-unpaid-order'].disabled,false);
  assert.equal(elements['order-rows'].children[0].children[5].children[1].textContent,'Cancel unpaid order');
  const unpaidCallbacks=buttonOptions, inventorySnapshot=JSON.stringify(products), salesSnapshot=JSON.stringify(sales);
  stallCancelOnce=true; loseCancelReceiptOnce=true;
  const cancelling=elements['cancel-unpaid-order'].handlers.click();
  assert.equal(elements['cancel-unpaid-order'].disabled,true);
  assert.equal(elements['create-order'].disabled,true);
  assert.equal(unpaidCallbacks.onClick({},actions),false);
  const cancelCount=cancelPosts.length;
  await elements['cancel-unpaid-order'].handlers.click();
  assert.equal(cancelPosts.length,cancelCount);
  releaseCancel(); await cancelling;
  assert.equal(orders[2].status,'cancelled');
  assert.equal(orders[2].payment.state,'cancelled_unpaid');
  assert.match(elements['orders-feedback'].textContent,/cancellation confirmed/);
  assert.equal(elements['order-review-status'].textContent,'Cancelled');
  assert.equal(elements['paypal-checkout'].hidden,true);
  const callbackCount=paypalPosts.length;
  await unpaidCallbacks.onApprove({orderID:unpaidRemote});
  assert.equal(paypalPosts.length,callbackCount);
  elements['close-review'].handlers.click();
  await buildPurchase();
  await elements['create-order'].handlers.click();
  assert.equal(orders.length,4);
  assert.equal(orders[3].status,'draft');
  assert.notEqual(orders[3].number,orders[2].number);
  assert.equal(elements['order-review-status'].textContent,'Draft');
  assert.equal(JSON.stringify(products),inventorySnapshot);
  assert.equal(JSON.stringify(sales),salesSnapshot);
  console.log('PASS: unpaid cancellation button, busy checks, lost cancellation receipt recovery, late callback ignored and a new saved draft with retained history.');

  // New actions on the last saved draft; all prior flows above already passed.
  await approve();
  await elements['paypal-start'].handlers.click();
  buttonOptions.onClick({},actions);
  const newRemote=await buttonOptions.createOrder();
  await buttonOptions.onApprove({orderID:newRemote});
  const payable=orders.at(-1), beforeReceiving=JSON.parse(JSON.stringify(products));
  assert.equal(elements['paypal-capture'].hidden,false);
  assert.equal(elements['paypal-void'].hidden,false);
  elements['paypal-capture'].handlers.click();
  assert.equal(elements['order-action-confirm'].hidden,false);
  assert.match(elements['order-action-description'].textContent,/Inventory will update/);
  const beforeConfirm=paypalPosts.length;
  elements['cancel-order-action'].handlers.click();
  assert.equal(elements['order-action-confirm'].hidden,true);
  assert.equal(paypalPosts.length,beforeConfirm);
  elements['paypal-capture'].handlers.click();
  stallSettlementOnce=true;loseSettlementReceiptOnce=true;
  const capturing=elements['confirm-order-action'].handlers.click();
  assert.equal(elements['close-review'].disabled,true);
  assert.equal(elements['paypal-void'].disabled,true);
  const duringCapture=paypalPosts.length;
  await elements['confirm-order-action'].handlers.click();
  assert.equal(paypalPosts.length,duringCapture);
  await Promise.resolve();releaseSettlement();await capturing;
  assert.equal(payable.payment.state,'captured');
  assert.equal(elements['paypal-error'].hidden,true);
  assert.equal(elements['paypal-capture'].hidden,true);
  assert.equal(elements['paypal-void'].hidden,true);
  assert.equal(elements['receive-stock'].hidden,false);
  assert.deepEqual(products,beforeReceiving);
  elements['receive-stock'].handlers.click();
  assert.match(elements['order-action-description'].textContent,/have arrived/);
  loseReceivingReceiptOnce=true;
  await elements['confirm-order-action'].handlers.click();
  assert.equal(payable.status,'received');
  assert.equal(elements['order-review-status'].textContent,'Received');
  assert.equal(elements['receive-stock'].hidden,true);
  assert.equal(elements['receipt-lines'].hidden,false);
  assert.equal(elements['receipt-lines'].children.length,payable.item_count);
  assert.match(elements['receiving-message'].textContent,/Inventory updated once/);
  assert.match(elements['paypal-payment-message'].textContent,/stock received/);
  const afterReceiving=JSON.stringify(products), receiptCount=receivePosts.length;
  elements['receive-stock'].handlers.click();
  await elements['confirm-order-action'].handlers.click();
  assert.equal(receivePosts.length,receiptCount);
  assert.equal(JSON.stringify(products),afterReceiving);
  assert.ok(payable.items.every(line=>products.find(p=>p.id===line.product_id).stock===beforeReceiving.find(p=>p.id===line.product_id).stock+line.quantity));
  // Separate authorized fixture exercises Void and its lost response recovery.
  elements['close-review'].handlers.click();
  const voidable=JSON.parse(JSON.stringify(payable));
  Object.assign(voidable,{id:orders.length+1,number:'RS-000005',status:'approved',version:2,receipt:null,received_at:null,can_capture:true,can_void:true,can_receive:false});
  Object.assign(voidable.payment,{state:'authorized',capture_id:null,message:'Test funds held.'});
  orders.push(voidable);
  await elements['refresh-orders'].handlers.click();
  await elements['order-rows'].children[0].children[5].children[0].handlers.click();
  elements['paypal-void'].handlers.click();
  assert.match(elements['order-action-description'].textContent,/cancel RS-000005/);
  loseSettlementReceiptOnce=true;
  await elements['confirm-order-action'].handlers.click();
  assert.equal(voidable.status,'cancelled');assert.equal(voidable.payment.state,'voided');
  assert.equal(elements['order-review-status'].textContent,'Cancelled');
  assert.equal(elements['paypal-error'].hidden,true);
  assert.equal(elements['stock-receiving'].hidden,true);
  assert.equal(JSON.stringify(products),afterReceiving);
  console.log('PASS: Capture/Void confirmations, busy click protection, lost settlement/receiving response recovery, full receipt ledger, immediate stock refresh and one-time receiving.');

  const beforeVoice=JSON.stringify({products,sales,orders,draftPosts,approvalPosts});
  const voiceDetail={plan:{budget:'50.00',lead_time_days:4,coverage_days:9,buffer_days:1},applied:false};
  await voiceHooks['resupply-voice-budget']({detail:voiceDetail});
  assert.equal(voiceDetail.applied,true);
  assert.equal(elements['purchase-budget'].value,'50.00');
  assert.equal(elements['lead-time'].value,'4');
  assert.equal(elements['coverage-days'].value,'9');
  assert.equal(elements['buffer-days'].value,'1');
  assert.equal(JSON.stringify({products,sales,orders,draftPosts,approvalPosts}),beforeVoice);
  const invalidVoice={plan:{budget:'50.000',lead_time_days:4,coverage_days:9,buffer_days:1},applied:false};
  await voiceHooks['resupply-voice-budget']({detail:invalidVoice});
  assert.equal(invalidVoice.applied,false);
  const inputEvents=[];
  sandbox.Event=class Event {constructor(type){this.type=type}};
  for(const id of ['purchase-budget','lead-time','coverage-days','buffer-days']) {
    elements[id].dispatchEvent=event=>inputEvents.push([id,event.type]);
  }
  const demoDetail={plan:{budget:'100.00',lead_time_days:3,coverage_days:7,buffer_days:2},applied:false};
  sandbox.window.resupplyPurchasingBusy=true;
  await voiceHooks['resupply-demo-budget']({detail:demoDetail});assert.equal(demoDetail.applied,false);
  sandbox.window.resupplyPurchasingBusy=false;
  await voiceHooks['resupply-demo-budget']({detail:demoDetail});
  assert.equal(demoDetail.applied,true);assert.equal(elements['purchase-budget'].value,'100.00');
  assert.equal(inputEvents.length,4);assert.ok(inputEvents.every(entry=>entry[1]==='input'));
  assert.equal(JSON.stringify({products,sales,orders,draftPosts,approvalPosts}),beforeVoice);
  console.log('PASS: voice and demo budgets open the live planner with reviewed settings; invalid input rejected and no sales/order/payment mutation.');

  console.log(JSON.stringify({passed: [
    'JavaScript syntax', 'sale dialog and remaining-stock preview',
    'sale payload and inventory/history refresh', 'cancel has no sale side effect',
    'uncertain network retry reuses ID and deducts once',
    'incomplete JSON retry reuses ID', 'busy save blocks duplicate submission and dismissal',
    'new sale has new request ID', 'stock correction still works', 'zero-stock sale disabled',
    'missing history is explicit', 'partial-day restock preview and cost',
    'settings use GET and leave stock/sales untouched', 'restock refreshes after sale and stock updates',
    'failed refresh removes old suggestions', 'recovery after failure',
    'older response cannot overwrite newer suggestions', 'new product refresh and safe text rendering',
    'purchase plan missing history and partial-day labels', 'purchase refresh after sale, stock and settings',
    'budget payload preserves cents', 'partial allocation and deferred quantity rendering',
    'zero budget defers quantities', 'build plan does not change inventory or sales',
    'failed purchase refresh clears plan and recovers', 'older purchase response cannot overwrite newer stock plan',
    'restock failure invalidates pending purchase response',
    'supplier form and safe dropdown names', 'quote creation without automatic selection',
    'lowest price and fastest delivery labels', 'supplier selection refreshes price and delivery',
    'quote save error preserves input and can retry', 'selected quote update reprices plan',
    'selection clear restores fallback', 'per-product quotes and stale-read protection',
    'selection error keeps current source', 'supplier change invalidates older budget response',
    'source changes preserve inventory reference cost, stock and sales',
    'draft requires suppliers and opens saved snapshot review', 'shipping/tax preview uses cents',
    'over-limit and invalid charges disable approval', 'busy approval blocks double submission and dismissal',
    'unknown approval retry keeps payload and request ID', 'approved view is read-only and saved in history',
    'later quote changes do not rewrite approved snapshot', 'cancelled order history',
    'unknown draft retry saves one order', 'known approval error unlocks form',
    'older order detail response cannot replace newer review', 'order actions leave stock and sales untouched',
  ]}));
})().catch(issue => {console.error(issue); process.exit(1)});
