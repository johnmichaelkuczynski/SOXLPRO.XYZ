// Browser-only display preferences. Never sends a Streamlit widget update.
(function () {
  const names = ['QQQ', 'TQQQ', 'TLT', 'XLU', 'VIX', 'SOX', 'GUSH', 'BTC'];
  // Keep selections only in this open page, never across page reloads.
  const key = '__soxlPageBenchmarkVisibility';
  const diagnosticSandbox = new URLSearchParams(location.search).has('diagnostics_sandbox');
  const listeners = [];
  let memory = null;
  function valid(state) {
    return state && names.every(name => typeof state[name] === 'boolean');
  }
  function read(initialSelected) {
    try {
      const saved = diagnosticSandbox ? null : window.parent[key];
      if (valid(saved)) return {...saved};
    } catch (_) { /* A restricted host still supports local controls. */ }
    if (valid(memory)) return {...memory};
    return Object.fromEntries(names.map(name =>
      [name, Array.isArray(initialSelected) && initialSelected.includes(name)]));
  }
  function notify(state) {
    listeners.forEach(listener => listener({...state}));
  }
  function save(state) {
    memory = {...state};
    if (diagnosticSandbox) return;
    try { window.parent[key] = {...state}; } catch (_) {}
  }
  function write(state) {
    if (!valid(state)) return;
    save(state);
    notify(state);
    if (diagnosticSandbox) return;
    // The original button row and the chart are sibling Streamlit iframes.
    try {
      window.parent.document.querySelectorAll('iframe').forEach(frame => {
        if (frame.contentWindow !== window)
          frame.contentWindow.postMessage({
            type:'soxl:benchmark-visibility', state
          }, window.location.origin);
      });
    } catch (_) { /* A standalone chart has no accessible sibling frames. */ }
  }
  window.addEventListener('message', event => {
    if (diagnosticSandbox) return;
    if (event.origin !== window.location.origin ||
        event.data?.type !== 'soxl:benchmark-visibility' ||
        !valid(event.data.state)) return;
    save(event.data.state);
    notify(event.data.state);
  });
  window.SOXLBenchmarkVisibility = {
    names, read, write,
    subscribe(listener) { listeners.push(listener); }
  };
})();
