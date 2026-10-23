// Rotate a vector snapshot, not Plotly's interactive coordinate system.
// Returning to the chart preserves its exact view, lines and pointer mapping.
async function openRotationView() {
  if (!chartDiv._fullLayout || document.getElementById('rotation-view')) return;
  const view = document.createElement('div');
  view.id = 'rotation-view';
  view.setAttribute('role', 'dialog');
  view.setAttribute('aria-label', 'Rotate graph');
  view.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:#fff;display:flex;flex-direction:column;color:#172b4d;font:15px system-ui';
  const bar = document.createElement('div');
  bar.style.cssText = 'padding:12px;display:flex;gap:12px;flex-wrap:wrap;align-items:center;background:#edf2f8';
  const text = document.createElement('span');
  text.textContent = 'Drag to rotate · Full graph fitted to screen';
  const angle = document.createElement('input');
  angle.type = 'range'; angle.min = '-180'; angle.max = '180'; angle.value = '0';
  angle.setAttribute('aria-label', 'Graph rotation angle');
  const output = document.createElement('span');
  output.textContent = '0°';
  const reset = document.createElement('button');
  reset.textContent = 'Upright';
  const close = document.createElement('button');
  close.textContent = 'Back to interactive chart';
  [reset, close].forEach(b => b.style.cssText = 'padding:8px 12px;cursor:pointer');
  const stage = document.createElement('div');
  stage.style.cssText = 'position:relative;flex:1;min-height:0;overflow:hidden;touch-action:none;cursor:grab';
  stage.textContent = 'Preparing graph…';
  const note = document.createElement('div');
  note.textContent = 'Rotation view is a snapshot. Return to the chart for live prices, projection popups and drawing.';
  note.style.cssText = 'padding:8px 12px;font-size:12px;background:#edf2f8';
  bar.append(text, angle, output, reset, close);
  view.append(bar, stage, note);
  document.body.appendChild(view);
  // Fullscreen avoids the tall chart iframe being clipped by the parent page.
  // If the browser disallows it, fit within the visible parent viewport.
  const oldScroll = window.scrollY;
  view.style.height = Math.max(320, Math.min(window.innerHeight,
    (() => {try {return window.parent.innerHeight - 100;} catch (_) {return 650;}})())) + 'px';
  try {
    if (view.requestFullscreen) await view.requestFullscreen();
  } catch (_) { /* embedded browsers can disallow fullscreen */ }
  if (document.fullscreenElement === view) view.style.height = '100%';
  let image, degrees = 0, dragging = null;
  const width = chartDiv._fullLayout.width, height = chartDiv._fullLayout.height;
  function fit() {
    if (!image) return;
    const radians = degrees * Math.PI / 180;
    const w = Math.abs(width * Math.cos(radians)) + Math.abs(height * Math.sin(radians));
    const h = Math.abs(height * Math.cos(radians)) + Math.abs(width * Math.sin(radians));
    const scale = Math.min((stage.clientWidth-24)/w, (stage.clientHeight-24)/h);
    image.style.transform = `translate(-50%,-50%) rotate(${degrees}deg) scale(${Math.max(.01, scale)})`;
    angle.value = Math.round(degrees);
    output.textContent = Math.round(degrees) + '°';
  }
  function end() { dragging = null; stage.style.cursor = 'grab'; }
  function dispose() {
    window.removeEventListener('keydown', key);
    window.removeEventListener('resize', fit);
    observer.disconnect();
    if (document.fullscreenElement === view) document.exitFullscreen().catch(()=>{});
    view.remove();
    window.scrollTo(0, oldScroll);
  }
  function key(e) { if (e.key === 'Escape') dispose(); }
  close.onclick = dispose;
  reset.onclick = () => {degrees = 0; fit();};
  angle.oninput = () => {degrees = Number(angle.value); fit();};
  stage.onpointerdown = e => {
    if (e.button !== 0) return;
    dragging = {x:e.clientX, y:e.clientY, angle:degrees};
    stage.setPointerCapture(e.pointerId);
    stage.style.cursor = 'grabbing';
  };
  stage.onpointermove = e => {
    if (!dragging) return;
    degrees = ((dragging.angle + (e.clientX-dragging.x)*.4 +
      (e.clientY-dragging.y)*.2 + 540) % 360)-180;
    fit();
  };
  stage.onpointerup = end;
  stage.onpointercancel = end;
  const observer = new ResizeObserver(fit);
  observer.observe(stage);
  window.addEventListener('keydown', key);
  window.addEventListener('resize', fit);
  try {
    const url = await Plotly.toImage(chartDiv, {format:'svg', width, height});
    if (!view.isConnected) return;
    image = document.createElement('img');
    image.alt = 'Rotatable snapshot of the SOXL chart and trendlines';
    image.draggable = false;
    image.src = url;
    image.style.cssText = `position:absolute;left:50%;top:50%;width:${width}px;height:${height}px;max-width:none;pointer-events:none;transform-origin:center`;
    stage.replaceChildren(image);
    fit();
  } catch (_) {
    stage.textContent = 'The rotation view could not be created. Return to the chart and try again.';
  }
}
