(function (root) {
  "use strict";
  const DAY = 86400000;
  function time(line, point) {
    const value = line["x" + point + "_ms"];
    return Number.isFinite(value) ? value : Date.parse(line["x" + point]);
  }
  function priceAt(line, timestamp, scale) {
    const start = time(line, 1), end = time(line, 2);
    if (![start, end, timestamp, line.y1, line.y2].every(Number.isFinite) ||
        start === end || line.y1 <= 0 || line.y2 <= 0) return NaN;
    const first = scale === "log" ? Math.log10(line.y1) : line.y1;
    const last = scale === "log" ? Math.log10(line.y2) : line.y2;
    const value = first + (last - first) * (timestamp - start) / (end - start);
    return scale === "log" ? Math.pow(10, value) : value;
  }
  function resize(line, point, timestamp, scale, formatDate) {
    if (![1, 2].includes(point) || !Number.isFinite(timestamp)) return null;
    const other = time(line, point === 1 ? 2 : 1);
    if (point === 1 ? timestamp >= other - DAY : timestamp <= other + DAY) return null;
    const price = priceAt(line, timestamp, scale);
    if (!Number.isFinite(price) || price <= 0 || price >= 1e12) return null;
    return {...line, ["x" + point + "_ms"]: timestamp,
      ["x" + point]: formatDate(timestamp), ["y" + point]: price, manualExtent: true};
  }
  function handles(line, layout, rightLimit) {
    if (!layout || !line.automaticType) return [];
    const x = layout.xaxis, y = layout.yaxis;
    const x0 = x._offset + x.d2p(new Date(time(line, 1)));
    const y0 = y._offset + y.d2p(line.y1);
    const x1 = x._offset + x.d2p(new Date(time(line, 2)));
    const y1 = y._offset + y.d2p(line.y2);
    if (![x0, x1, y0, y1].every(Number.isFinite)) return [];
    const left = x._offset + 10, top = y._offset + 10;
    const right = Math.max(left + 20, Math.min(x._offset + x._length - 10, rightLimit || Infinity));
    const bottom = y._offset + y._length - 10;
    const dx = x1 - x0, dy = y1 - y0;
    let lo = 0, hi = 1;
    for (const [p, q] of [[-dx, x0 - left], [dx, right - x0],
                          [-dy, y0 - top], [dy, bottom - y0]]) {
      if (p === 0) { if (q < 0) return []; continue; }
      const fraction = q / p;
      if (p < 0) lo = Math.max(lo, fraction);
      else hi = Math.min(hi, fraction);
      if (lo > hi) return [];
    }
    return [{point: 1, x: x0 + lo * dx, y: y0 + lo * dy},
            {point: 2, x: x0 + hi * dx, y: y0 + hi * dy}];
  }
  const api = {priceAt, resize, handles};
  if (typeof module !== "undefined") module.exports = api;
  if (!root.document) return;
  root.SOXLChannelResize = api;
  root.installChannelResize = function (chart, options) {
    if (chart._channelResize) { chart._channelResize.refresh(); return; }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.style.cssText = "position:absolute;inset:0;z-index:115;pointer-events:none;overflow:hidden";
    let drag = null;
    function stop(event) { event.preventDefault(); event.stopPropagation(); }
    function finish(event, cancel) {
      if (!drag || event && event.pointerId !== drag.id) return;
      if (event) stop(event);
      const completed = drag;
      drag = null;
      if (completed.moved) {
        if (cancel) options.cancel(completed.index, completed.original);
        else options.commit(completed.index);
      }
      refresh();
    }
    function refresh() {
      if (!svg.isConnected) chart.appendChild(svg);
      if (drag) return; // Keep pointer capture alive while Plotly updates traces.
      svg.replaceChildren();
      svg.setAttribute("width", chart.clientWidth);
      svg.setAttribute("height", chart.clientHeight);
      const layout = chart._fullLayout;
      if (!layout) return;
      const panel = document.getElementById("toolbar");
      const chartRect = chart.getBoundingClientRect();
      const panelRect = panel && panel.getBoundingClientRect();
      const limit = panelRect && panelRect.left > chartRect.left + layout.xaxis._offset + 80
        ? panelRect.left - chartRect.left - 18 : null;
      options.lines().forEach((line, index) => {
        handles(line, layout, limit).forEach(position => {
          const circle = document.createElementNS(svg.namespaceURI, "circle");
          const attrs = {cx: position.x, cy: position.y, r: 8, fill: "white",
            stroke: line.color || "#475569", "stroke-width": 3,
            "data-channel-handle": position.point, "data-line-index": index,
            tabindex: 0, role: "slider",
            "aria-label": (line.label || "Channel line") + (position.point === 1 ? " start" : " end"),
            "aria-valuetext": line["x" + position.point] + " $" + line["y" + position.point].toFixed(2)};
          Object.entries(attrs).forEach(([key, value]) => circle.setAttribute(key, value));
          circle.style.cssText = "pointer-events:all;cursor:ew-resize;touch-action:none";
          const title = document.createElementNS(svg.namespaceURI, "title");
          title.textContent = "Drag to extend or shorten " + (line.label || "channel line") +
            ". Prices update along its existing slope. Edge handles also control off-screen endpoints.";
          circle.appendChild(title);
          circle.addEventListener("pointerdown", event => {
            if (event.button !== 0) return;
            stop(event);
            drag = {id: event.pointerId, index, point: position.point,
              original: {...line}, clientX: event.clientX, x: position.x, moved: false};
            circle.setPointerCapture(event.pointerId);
            options.active(true);
          });
          circle.addEventListener("pointermove", event => {
            if (!drag || event.pointerId !== drag.id) return;
            stop(event);
            const delta = event.clientX - drag.clientX;
            if (!drag.moved && Math.abs(delta) < 3) return;
            const x = chart._fullLayout.xaxis;
            const raw = x.p2d(drag.x + delta - x._offset);
            const timestamp = typeof raw === "number" ? raw : Date.parse(raw);
            const updated = resize(drag.original, drag.point, timestamp, options.scale(), options.date);
            if (!updated) return;
            if (!drag.moved) { options.begin(); drag.moved = true; }
            options.update(drag.index, updated);
            const y = chart._fullLayout.yaxis;
            circle.setAttribute("cx", Math.max(x._offset + 8,
              Math.min(x._offset + x._length - 8, drag.x + delta)));
            circle.setAttribute("cy", y._offset + y.d2p(updated["y" + drag.point]));
            circle.setAttribute("aria-valuetext",
              updated["x" + drag.point] + " $" + updated["y" + drag.point].toFixed(2));
          });
          circle.addEventListener("pointerup", event => { options.active(false); finish(event, false); });
          circle.addEventListener("pointercancel", event => { options.active(false); finish(event, true); });
          circle.addEventListener("lostpointercapture", event => {
            if (drag) { options.active(false); finish(event, true); }
          });
          circle.addEventListener("dblclick", stop);
          circle.addEventListener("keydown", event => {
            if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
            stop(event);
            const current = options.lines()[index];
            const timestamp = time(current, position.point) + (event.key === "ArrowRight" ? DAY : -DAY) *
              (event.shiftKey ? 30 : 1);
            const updated = resize(current, position.point, timestamp, options.scale(), options.date);
            if (updated) { options.begin(); options.update(index, updated); options.commit(index); }
          });
          svg.appendChild(circle);
        });
      });
    }
    chart.on("plotly_afterplot", refresh);
    chart.on("plotly_relayout", refresh);
    window.addEventListener("resize", refresh);
    chart._channelResize = {
      refresh,
      isDragging: () => Boolean(drag),
      cancel: () => { options.active(false); finish(null, true); }
    };
    refresh();
  };
})(typeof window !== "undefined" ? window : globalThis);
