(function (root) {
  "use strict";
  const DAY = 86400000;
  function measure(x, price, origin, baseline, logScale) {
    const time = typeof x === "number" ? x : Date.parse(x);
    const start = typeof origin === "number" ? origin : Date.parse(origin);
    if (![time, start, price, baseline].every(Number.isFinite) ||
        (logScale && (price <= 0 || baseline <= 0))) return null;
    const days = Math.abs(time - start) / DAY;
    return {
      days, dollarDays: days * Math.abs(price - baseline),
      axisArea: days * Math.abs(logScale ? Math.log10(price / baseline) : price - baseline),
      time, start, price, baseline, logScale
    };
  }
  if (typeof module !== "undefined") module.exports = {measure};
  if (!root.document) return;

  root.installAxisArea = function (chart) {
    if (chart._axisArea) { chart._axisArea.refresh(); return; }
    const toggle = document.getElementById("axisAreaToggle");
    const follow = document.getElementById("axisAreaFollow");
    const output = document.getElementById("axisAreaOutput");
    // Keep measurements readable independently of the resizable controls panel.
    output.style.cssText = "position:absolute;top:38px;left:70px;z-index:5;" +
      "max-width:290px;width:calc(100% - 110px);box-sizing:border-box;" +
      "white-space:pre-line;font:12px/1.5 sans-serif;padding:10px;" +
      "background:rgba(255,251,235,.96);color:#78350f;border:1px solid #f59e0b;" +
      "border-radius:6px;pointer-events:none";
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:visible;z-index:4";
    svg.setAttribute("aria-hidden", "true");
    let enabled = false, pinned = false, point = null;
    const fmt = n => n.toLocaleString(undefined, {maximumFractionDigits: 4});
    const date = n => new Date(n).toISOString().slice(0, 10);
    function clear() { svg.replaceChildren(); }
    function element(tag, attrs, text) {
      const el = document.createElementNS(svg.namespaceURI, tag);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
      if (text !== undefined) el.textContent = text;
      svg.appendChild(el);
    }
    function refresh() {
      if (!svg.isConnected) chart.appendChild(svg);
      if (output.parentNode !== chart) chart.appendChild(output);
      clear();
      output.hidden = !enabled;
      follow.hidden = !enabled;
      follow.disabled = !pinned;
      if (!enabled) return;
      if (!point) {
        output.textContent = "Hover over a price point. Click a point to hold its measurement.";
        return;
      }
      const layout = chart._fullLayout;
      if (!layout || !layout.xaxis || !layout.yaxis) return;
      const x = layout.xaxis, y = layout.yaxis;
      const leftDate = x.p2d(0), bottomPrice = Number(y.p2d(y._length));
      const result = measure(point.x, point.y, leftDate, bottomPrice, y.type === "log");
      if (!result) { output.textContent = "Area is unavailable for this point."; return; }
      const px = x.d2p(point.x), py = y.d2p(point.y);
      if (![px, py, x._offset, y._offset, x._length, y._length].every(Number.isFinite)) return;
      if (px < 0 || px > x._length || py < 0 || py > y._length) {
        output.textContent = "The held point is outside the visible chart. Pan back or choose Follow cursor.";
        return;
      }
      const left = x._offset, bottom = y._offset + y._length;
      const right = left + px, top = y._offset + py;
      svg.setAttribute("width", layout.width);
      svg.setAttribute("height", layout.height);
      element("rect", {x:left, y:top, width:px, height:bottom-top, fill:"#f59e0b", opacity:0.12});
      element("path", {d:`M ${left} ${top} H ${right} V ${bottom}`,
        fill:"none", stroke:"#b45309", "stroke-width":2, "stroke-dasharray":"5 3"});
      element("circle", {cx:right, cy:top, r:4, fill:"#b45309"});
      const labelStyle = {fill:"#92400e", "font-size":11, "font-weight":600,
        stroke:"white", "stroke-width":3, "paint-order":"stroke"};
      element("text", {...labelStyle, x:left-4, y:top-5, "text-anchor":"end"}, "$" + fmt(point.y));
      element("text", {...labelStyle, x:Math.min(right, left+x._length-38), y:bottom+30,
        "text-anchor":"middle"}, date(result.time));
      output.textContent = `${pinned ? "Held" : "Cursor"}: ${date(result.time)} · $${fmt(point.y)}\n` +
        `Origin: ${date(result.start)} · $${fmt(bottomPrice)} (visible axes)\n` +
        `Width: ${fmt(result.days)} calendar days\n` +
        `Price–time area: ${fmt(result.dollarDays)} dollar-days\n` +
        (result.logScale ? `Log-chart area: ${fmt(result.axisArea)} log₁₀-price × days\n` : "") +
        "Area changes with the axis origin when you pan or zoom. Predictive value has not been tested.";
    }
    function readPoint(event) {
      const p = event && event.points && event.points[0];
      if (!p || (p.data && p.data.yaxis && p.data.yaxis !== "y") ||
          (p.xaxis && p.xaxis._id !== "x") || (p.yaxis && p.yaxis._id !== "y")) return null;
      const value = Number(p.y);
      return Number.isFinite(value) ? {x:p.x, y:value} : null;
    }
    toggle.addEventListener("click", () => {
      enabled = !enabled;
      if (!enabled) {point = null; pinned = false;}
      toggle.setAttribute("aria-pressed", String(enabled));
      toggle.classList.toggle("active", enabled);
      refresh();
      if (typeof root.fitRailContent === "function") root.fitRailContent();
    });
    follow.addEventListener("click", () => {pinned = false; refresh();});
    chart.on("plotly_hover", event => {
      if (!enabled || pinned) return;
      point = readPoint(event);
      refresh();
    });
    chart.on("plotly_click", event => {
      if (!enabled) return;
      const selected = readPoint(event);
      if (selected) {point = selected; pinned = true; refresh();}
    });
    chart.on("plotly_unhover", () => {
      if (enabled && !pinned) {point = null; refresh();}
    });
    chart.on("plotly_relayout", refresh);
    chart.on("plotly_afterplot", refresh);
    chart._axisArea = {refresh};
    refresh();
  };
})(typeof window === "undefined" ? globalThis : window);