(() => {
  'use strict';
  const mode = document.body.dataset.workspace;
  const prefix = document.body.dataset.apiPrefix;
  if (!['real','demo'].includes(mode) || prefix !== (mode === 'demo' ? '/demo' : '')) {
    throw new Error('Shop scope is unavailable. Restart and reload the app.');
  }
  const request = window.fetch.bind(window);
  const localUrl = path => {
    if (typeof path !== 'string' || !(path.startsWith('/api/') || path === '/health') ||
        path.split(/[?#]/)[0].split('/').some(part => part === '..' || part === '.')) {
      throw new Error('Use a local API path for this shop.');
    }
    return prefix + path;
  };
  Object.defineProperty(window,'resupplyWorkspace',{value:Object.freeze({mode,prefix}),writable:false});
  Object.defineProperty(window,'resupplyUrl',{value:localUrl,writable:false});
  Object.defineProperty(window,'resupplyFetch',{value:(path,options={})=>request(localUrl(path),{cache:'no-store',...options}),writable:false});
  const el = id => document.getElementById(id);
  if (mode === 'demo') {
    el('workspace-name').textContent='DEMO · synthetic shop';
    el('demo-title').textContent='Complete demo shop workflow';
    el('demo-intro').textContent='Sample data → trained forecast → reviewed budget → Sandbox hold / capture → Receive Stock. Har action isi demo shop mein hota hai.';
    el('workspace-link').textContent='Open my shop';el('workspace-link').href='/';
    el('demo-tools').hidden=false;
    for (const id of ['forecast-source','voice-source','history-source']) {
      el(id).value='demo';
      for (const option of el(id).options) if (option.value === 'actual') option.disabled=true;
    }
    el('impact-use').textContent='Use this demo forecast';
    el('forecast-help').textContent='DEMO · 56 completed synthetic days required. Review a current demo forecast to use it for this isolated shop. The existing shop is separate.';
    el('impact-copy').textContent='Preview uses this demo shop’s stock, selected supplier quote and incoming deliveries. Review applies only to demo purchasing. Projections beyond 7 days are not separately tested.';
    el('impact-review-copy').textContent='Review the forecast and its limits. Applying it changes future demo drafts. Approve and pay only after checking quantities, shipping and tax.';
  }
})();
