// This lives outside React so a failed Streamlit render cannot erase it.
(() => {
  let timer;
  function showRecovery() {
    if (document.getElementById('soxl-preview-recovery')) return;
    const panel = document.createElement('section');
    panel.id = 'soxl-preview-recovery';
    panel.setAttribute('role', 'alert');
    panel.style.cssText = 'position:fixed;inset:20px auto auto 20px;max-width:480px;z-index:2147483647;background:#fff;color:#172b4d;padding:24px;border:1px solid #ccd6e3;border-radius:10px;font:16px/1.5 system-ui;box-shadow:0 4px 20px #0002';
    const title = document.createElement('strong');
    title.textContent = 'The chart session could not be displayed.';
    const text = document.createElement('p');
    text.textContent = 'The page may have lost its connection or failed to load. Reopen it to start a fresh session. Unsaved chart adjustments may be lost.';
    const button = document.createElement('button');
    button.textContent = 'Reopen SOXL Analysis';
    button.style.cssText = 'padding:10px 16px;cursor:pointer;background:#1565c0;color:white;border:0;border-radius:6px;font:inherit';
    button.onclick = () => {
      const url = new URL(location.href);
      url.searchParams.set('reconnect', Date.now().toString());
      location.replace(url.toString());
    };
    panel.append(title, text, button);
    document.body.appendChild(panel);
  }
  function fatal(event) {
    const message = String(event.message || event.reason?.message || event.reason || '');
    if (/Bad delta path index|Failed to fetch dynamically imported module|ChunkLoadError/i.test(message)) {
      showRecovery();
    }
  }
  window.addEventListener('error', fatal);
  window.addEventListener('unhandledrejection', fatal);
  function check() {
    const root = document.getElementById('root');
    if (!root || !root.innerText.trim()) {
      if (!timer) timer = setTimeout(showRecovery, 15000);
    } else {
      clearTimeout(timer);
      timer = null;
    }
  }
  window.addEventListener('DOMContentLoaded', () => {
    check();
    new MutationObserver(check).observe(document.getElementById('root') || document.body,
      {childList:true, subtree:true, characterData:true});
  });
})();
