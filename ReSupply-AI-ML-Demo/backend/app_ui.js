/* Navigation keeps existing forms/callbacks mounted and bound to their shop. */
(() => {
  'use strict';
  const scope=window.resupplyWorkspace,el=id=>document.getElementById(id);
  const pages={
    overview:{path:'/',name:'Dashboard',eyebrow:'SHOP OVERVIEW',title:'Your shop, at a glance.',copy:'Stock, purchasing and next steps—all in one clear view.'},
    inventory:{path:'/inventory',name:'Inventory',eyebrow:'YOUR PRODUCTS',title:'A clear view of your stock.',copy:'Add products, correct stock and record a sale beside the matching product.'},
    sales:{path:'/sales',name:'Sales',eyebrow:'DAILY OPERATIONS',title:'Every sale, accounted for.',copy:'Recent sale records and the stock remaining after each sale.'},
    history:{path:'/sales-history',name:'Sales history',eyebrow:'FORECAST DATA',title:'Good forecasts start with good records.',copy:'Save completed daily totals or preview a CSV before importing it.'},
    forecast:{path:'/forecast',name:'AI forecast',eyebrow:'DEMAND INTELLIGENCE',title:'Know what your shop may need.',copy:'Compare ML with the sales average, check test errors, then review purchasing impact.'},
    suppliers:{path:'/suppliers',name:'Suppliers',eyebrow:'SOURCING',title:'Find the right price and delivery.',copy:'Compare supplier quotes and explicitly choose a source for each product.'},
    purchasing:{path:'/purchasing',name:'Purchase planner',eyebrow:'SMART PURCHASING',title:'A purchase plan within your budget.',copy:'Check demand, delivery and product costs before saving a draft for review.'},
    orders:{path:'/orders',name:'Orders & incoming',eyebrow:'REVIEW & FULFILMENT',title:'Every order, from draft to delivery.',copy:'Review, approve, authorize or capture a test payment. Receive stock when goods arrive.'},
    assistant:{path:'/assistant',name:'Voice assistant',eyebrow:'ASK YOUR ASSISTANT',title:'Bolo ya type karo. Pehle preview dekho.',copy:'Check stock, saved forecasts and USD budgets using supported Hindi, Hinglish or English commands.'},
    'demo-guide':{path:'/demo-guide',name:'Demo guide',eyebrow:'COMPLETE WALKTHROUGH',title:'See ReSupply AI in action.',copy:'Prepare a synthetic shop and follow the full reviewed Sandbox purchasing workflow.'}
  };
  const screens=[...document.querySelectorAll('[data-screen]')],links=[...document.querySelectorAll('[data-view]')];
  const sidebar=el('app-sidebar'),menu=el('menu-toggle'),backdrop=el('nav-backdrop');
  const mobile=window.matchMedia('(max-width: 980px)');
  let current=null,drawer=false;
  const url=view=>scope.prefix+pages[view].path;
  const locationView=()=>{
    const path=window.location.pathname;
    const local=scope.prefix&&path.startsWith(scope.prefix+'/')?path.slice(scope.prefix.length):path;
    return Object.keys(pages).find(key=>pages[key].path===local)||'overview';
  };
  const note=text=>{el('navigation-note').textContent=text;el('navigation-note').hidden=!text;};
  function closeDrawer(focus=false) {
    drawer=false;document.body.classList.remove('nav-open');backdrop.hidden=true;
    menu.setAttribute('aria-expanded','false');sidebar.inert=mobile.matches;
    sidebar.setAttribute('aria-hidden',String(mobile.matches));
    if(focus)menu.focus();
  }
  function navigate(view,{push=true,focus=true,initial=false}={}) {
    if(!pages[view])return false;
    if(!initial&&[...document.querySelectorAll('dialog')].some(dialog=>dialog.open)) {
      note('Close the current dialog before switching pages. Pending actions stay on this shop.');return false;
    }
    const previous=current;current=view;document.body.dataset.startView=view;
    for(const screen of screens)screen.hidden=screen.dataset.screen!==view;
    for(const link of links) {
      const key=link.dataset.view;
      if(!pages[key])continue;
      link.href=url(key);
      if(key===view){link.setAttribute('aria-current','page');const group=link.closest?.('details');if(group?.tagName==='DETAILS'&&group.classList.contains('easy-more-nav'))group.open=true;}else link.removeAttribute('aria-current');
    }
    el('page-crumb').textContent=pages[view].name;
    el('page-eyebrow').textContent=pages[view].eyebrow;
    el('view-title').textContent=pages[view].title;
    el('view-subtitle').textContent=pages[view].copy;
    document.title=(scope.mode==='demo'?'DEMO · ':'')+pages[view].name+' | ReSupply AI';
    if(push&&window.location.pathname!==url(view))window.history.pushState({view},'',url(view));
    note('');closeDrawer();
    if(focus){window.scrollTo({top:0,behavior:'auto'});el('view-title').focus({preventScroll:true});}
    if(previous!==view)window.dispatchEvent(new CustomEvent('resupply-view-changed',{detail:{view,previous}}));
    return true;
  }
  Object.defineProperty(window,'resupplyNavigate',{value:navigate,writable:false});
  document.addEventListener('click',event=>{
    const link=event.target.closest?.('[data-view]');
    if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button>0)return;
    event.preventDefault();navigate(link.dataset.view);
  });
  window.addEventListener('popstate',()=>{
    if(!navigate(locationView(),{push:false}))window.history.replaceState({view:current},'',url(current));
  });
  menu.addEventListener('click',()=>{
    if(drawer){closeDrawer(true);return;}
    if(!mobile.matches)return;
    drawer=true;sidebar.inert=false;sidebar.setAttribute('aria-hidden','false');
    document.body.classList.add('nav-open');backdrop.hidden=false;menu.setAttribute('aria-expanded','true');
    (sidebar.querySelector('[aria-current="page"]')||sidebar.querySelector('a')).focus();
  });
  backdrop.addEventListener('click',()=>closeDrawer(true));
  document.addEventListener('keydown',event=>{
    if(!drawer)return;
    if(event.key==='Escape'){event.preventDefault();closeDrawer(true);return;}
    if(event.key==='Tab') {
      const candidates=[menu,...sidebar.querySelectorAll('a, summary')].filter(item=>item.closest?.('details:not([open])')?.tagName!=='DETAILS'),first=candidates[0],last=candidates.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  const resize=()=>closeDrawer();
  if(mobile.addEventListener)mobile.addEventListener('change',resize);else mobile.addListener(resize);

  // Display saved app responses. There are no payment/stock write requests here.
  const data={products:null,restock:null,purchase:null,orders:null,demo:null};
  const status={products:'loading',restock:'loading',purchase:'loading',orders:'loading'};
  const qty=value=>Number(value).toLocaleString('en-US');
  const money=value=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value));
  const labels={draft:'Draft',approved:'Approved · unpaid',authorized:'Hold · not captured',captured:'Captured · awaiting stock',received:'Stock received',voided:'Hold voided',cancelled:'Cancelled',
    capture_pending:'Capture pending',capture_unknown:'Capture unconfirmed',authorize_unknown:'Hold unconfirmed',review_required:'Needs payment review'};
  function empty(container,text) {const p=document.createElement('p');p.className='quiet-state';p.textContent=text;container.append(p);}
  function nextStep() {
    let view='purchasing',title='Review your next purchase',copy='Use current demand and supplier quotes to build a product-budget plan.',action='Open purchase planner';
    const demo=data.demo,order=demo?.focus_order;
    if(scope.mode==='demo'&&!demo?.prepared){view='demo-guide';title='Try the complete demo shop';copy='Prepare sample products and sales history, then train real demand forecasts.';action='Open demo guide';}
    else if(scope.mode==='demo'&&demo.products.filter(p=>p.sample).some(p=>!p.current)){view='demo-guide';title='Prepare current demo forecasts';copy='Refresh completed synthetic dates and train the current reports. Review happens separately.';action='Open demo guide';}
    else if(data.products&&data.products.length===0){view='inventory';title='Add your first product';copy='Start with a product code, current stock and unit cost. Your catalog is saved in this shop.';action='Open inventory';}
    else if(order?.status==='draft'){view='orders';title='Review your saved draft';copy='Check quantities, suppliers, shipping, tax and the spending limit before approval.';action='Open saved orders';}
    else if(order?.payment?.state==='authorized'){view='orders';title='Your test funds are on hold';copy='The payment is not captured. Review the approved amount, then choose Capture or Void.';action='Review payment';}
    else if(order?.payment?.state==='captured'&&order.status!=='received'){view='orders';title='Receive goods when they arrive';copy='Payment is captured. Stock increases only after you explicitly confirm receiving.';action='Open stock receiving';}
    else if(demo?.prepared&&demo.products.filter(p=>p.sample).some(p=>!p.active_run_id)){view='forecast';title='Review the demand forecasts';copy='Check model errors and purchase impact before using a forecast for this demo shop.';action='Review AI forecast';}
    else if(data.restock&&data.restock.items.length&&data.restock.items.every(p=>p.suggested_quantity===null)){view='history';title='Give your planner sales history';copy='Save completed daily totals or preview and import the appropriate sales CSV.';action='Open sales history';}
    el('next-step-title').textContent=title;el('next-step-copy').textContent=copy;
    const link=el('next-step-link');link.textContent=action+' →';link.dataset.view=view;link.href=url(view);
  }
  function render() {
    const p=data.products,r=data.restock,plan=data.purchase,orders=data.orders;
    el('dash-products').textContent=p?qty(p.length):'—';
    el('dash-products-note').textContent=p?qty(p.reduce((total,item)=>total+item.stock,0))+' units currently on hand':status.products==='error'?'Catalog unavailable. Refresh Inventory.':'Loading your catalog…';
    el('dash-restock').textContent=r?qty(r.suggested_products):'—';
    const unknown=r?.items.filter(item=>item.suggested_quantity===null).length||0;
    el('dash-restock-note').textContent=r?(unknown?unknown+' product(s) need demand data':'Based on current demand and delivery'):status.restock==='error'?'Suggestions unavailable. Open planner.':'Checking demand and stock…';
    el('dash-plan').textContent=plan?money(plan.planned_cost):'—';
    el('dash-plan-note').textContent=plan?'Product costs only · '+money(plan.budget)+' budget':status.purchase==='error'?'Plan unavailable. Use Build plan.':'Product costs only · updating…';
    el('dash-incoming').textContent=orders?qty(orders.filter(order=>order.status==='approved'&&order.payment?.state==='captured').length):'—';
    el('dash-incoming-note').textContent=orders?'From latest 50 saved orders':status.orders==='error'?'Orders unavailable. Refresh Orders.':'Loading latest saved orders…';
    const badge=el('nav-restock-count');badge.hidden=!r?.suggested_products;badge.textContent=r?qty(r.suggested_products):'';
    const attention=el('dash-attention');attention.replaceChildren();
    if(!r)empty(attention,status.restock==='error'?'Restock data could not load. Open the planner to retry.':'Loading suggestions…');
    else {
      const priority={out_of_stock:0,delivery_risk:1,restock:2};
      const items=r.items.filter(item=>(item.suggested_quantity||0)>0).sort((a,b)=>(priority[a.status]??3)-(priority[b.status]??3)).slice(0,4);
      if(!items.length)empty(attention,unknown?'Some products still need completed demand data. Add sales history to estimate purchasing.':r.items.length?'No purchase quantities are currently suggested.':'Add products and sales history to start planning.');
      for(const item of items) {
        const row=document.createElement('div');row.className='attention-row';
        const text=document.createElement('div'),name=document.createElement('strong'),detail=document.createElement('small');
        name.textContent=item.name;detail.textContent=item.sku+' · '+qty(item.stock)+' in stock · '+qty(item.suggested_quantity)+' suggested';text.append(name,detail);
        const tag=document.createElement('span');tag.className='status '+item.status;
        tag.textContent={out_of_stock:'Out of stock',delivery_risk:'Delivery risk',restock:'Restock'}[item.status]||'Review';row.append(text,tag);attention.append(row);
      }
    }
    el('dash-demand-note').textContent=r?('Calculated '+r.shop_date+' (IST). '+(r.method==='reviewed_forecast_mixed'?'Reviewed forecasts where active; averages for other products.':'Sales-average purchasing until a current forecast is reviewed.')):'Purchasing recommendations require your review.';
    const list=el('dash-orders');list.replaceChildren();
    if(!orders)empty(list,status.orders==='error'?'Orders could not load. Open Orders to refresh.':'Loading saved orders…');
    else if(!orders.length)empty(list,'Your first reviewed purchase will appear here. Save a draft from the purchase planner.');
    else for(const order of orders.slice(0,3)) {
      const row=document.createElement('div');row.className='dashboard-order';
      const text=document.createElement('div'),name=document.createElement('strong'),detail=document.createElement('small');
      name.textContent=order.number;detail.textContent=qty(order.units)+' units · '+money(order.grand_total);text.append(name,detail);
      const tag=document.createElement('span'),state=order.status==='received'?'received':order.status==='cancelled'?'cancelled':order.payment?.state||order.status;
      tag.className='status '+(state==='received'||state==='captured'?'received':state==='cancelled'?'cancelled':'');tag.textContent=labels[state]||state.replaceAll('_',' ');row.append(text,tag);list.append(row);
    }
    el('dash-data-note').textContent=scope.mode==='demo'?'DEMO · Synthetic stock and history · USD Sandbox test payments · explicit owner review.':'Current shop data · USD Sandbox test payments · stock updates after confirmed receiving.';
    nextStep();
  }
  window.addEventListener('resupply-dashboard-data',event=>{
    const value=event.detail;if(!value||!['products','restock','purchase','orders'].includes(value.section))return;
    data[value.section]=value.data||null;status[value.section]=value.status||'ready';render();
  });
  window.addEventListener('resupply-demo-state',event=>{data.demo=event.detail;render();});
  navigate(document.body.dataset.startView||locationView(),{push:false,focus:false,initial:true});render();
})();
