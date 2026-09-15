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
  function axisPixel(axis, value, range, vertical) {
    if (!range) return axis.d2p(value) + axis._offset;
    const toValue = v => axis.type === "date"
      ? (typeof v === "number" ? v : Date.parse(v)) : Number(v);
    const low = toValue(range[0]), high = toValue(range[1]);
    const data = axis.type === "log" ? Math.log10(value) : toValue(value);
    const fraction = (data - low) / (high - low);
    return axis._offset + axis._length * (vertical ? 1 - fraction : fraction);
  }
  if (typeof module !== "undefined") module.exports = {measure, axisPixel};
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
    const fmt = n => n !== 0 && Math.abs(n) < 0.0001
      ? n.toExponential(4) : n.toLocaleString(undefined, {maximumFractionDigits: 4});
    const date = n => new Date(n).toISOString().slice(0, 10);
    function clear() { svg.replaceChildren(); }
    function element(tag, attrs, text) {
      const el = document.createElementNS(svg.namespaceURI, tag);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
      if (text !== undefined) el.textContent = text;
      svg.appendChild(el);
      return el;
    }
    function refresh(changes) {
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
      const leftDate = point.origin, bottomPrice = point.baseline;
      const result = measure(point.x, point.y, leftDate, bottomPrice, y.type === "log");
      if (!result) { output.textContent = "Area is unavailable for this point."; return; }
      function liveRange(name, axis) {
        if (!changes) return null;
        if (Array.isArray(changes[name + ".range"])) return changes[name + ".range"];
        if (changes[name + ".range[0]"] !== undefined || changes[name + ".range[1]"] !== undefined)
          return [changes[name + ".range[0]"] ?? axis.range[0],
                  changes[name + ".range[1]"] ?? axis.range[1]];
        return null;
      }
      const xr = liveRange("xaxis", x), yr = liveRange("yaxis", y);
      const left = axisPixel(x, point.origin, xr, false);
      const bottom = axisPixel(y, bottomPrice, yr, true);
      const right = axisPixel(x, point.x, xr, false);
      const top = axisPixel(y, point.y, yr, true);
      if (![left, bottom, right, top].every(Number.isFinite)) return;
      svg.setAttribute("width", layout.width);
      svg.setAttribute("height", layout.height);
      const clip = element("clipPath", {id:"axis-area-clip"});
      const bounds = document.createElementNS(svg.namespaceURI, "rect");
      Object.entries({x:x._offset, y:y._offset, width:x._length, height:y._length})
        .forEach(([key, value]) => bounds.setAttribute(key, value));
      clip.appendChild(bounds);
      element("rect", {x:Math.min(left,right), y:Math.min(top,bottom),
        width:Math.abs(right-left), height:Math.abs(bottom-top), fill:"#f59e0b",
        opacity:0.12, "clip-path":"url(#axis-area-clip)"});
      element("path", {d:`M ${left} ${top} H ${right} V ${bottom}`,
        fill:"none", stroke:"#b45309", "stroke-width":2, "stroke-dasharray":"5 3",
        "clip-path":"url(#axis-area-clip)"});
      element("circle", {cx:right, cy:top, r:4, fill:"#b45309", "clip-path":"url(#axis-area-clip)"});
      const labelStyle = {fill:"#92400e", "font-size":11, "font-weight":600,
        stroke:"white", "stroke-width":3, "paint-order":"stroke"};
      if (top >= y._offset && top <= y._offset+y._length)
        element("text", {...labelStyle, x:x._offset-4, y:top-5, "text-anchor":"end"}, "$" + fmt(point.y));
      if (right >= x._offset && right <= x._offset+x._length)
        element("text", {...labelStyle, x:Math.min(right, x._offset+x._length-38),
          y:y._offset+y._length+30, "text-anchor":"middle"}, date(result.time));
      output.textContent = `${pinned ? "Held" : "Cursor"}: ${date(result.time)} · $${fmt(point.y)}\n` +
        `Fixed origin: ${date(result.start)} · $${fmt(bottomPrice)}\n` +
        `Width: ${fmt(result.days)} calendar days\n` +
        `Price–time area: ${fmt(result.dollarDays)} dollar-days\n` +
        (result.logScale ? `Log-chart area: ${fmt(result.axisArea)} log₁₀-price × days\n` : "") +
        "Held boxes move with the chart; panning and zooming preserve their area. Predictive value has not been tested.";
    }
    function readPoint(event) {
      const p = event && event.points && event.points[0];
      if (!p || (p.data && p.data.yaxis && p.data.yaxis !== "y") ||
          (p.xaxis && p.xaxis._id !== "x") || (p.yaxis && p.yaxis._id !== "y")) return null;
      const value = Number(p.y);
      const layout = chart._fullLayout;
      return Number.isFinite(value) && layout ? {
        x:p.x, y:value, origin:layout.xaxis.p2d(0),
        baseline:Number(layout.yaxis.p2d(layout.yaxis._length))
      } : null;
    }
    toggle.addEventListener("click", () => {
      enabled = !enabled;
      if (!enabled) {point = null; pinned = false;}
      toggle.setAttribute("aria-pressed", String(enabled));
      toggle.classList.toggle("active", enabled);
      refresh();
      if (typeof root.fitRailContent === "function") root.fitRailContent();
    });
    follow.addEventListener("click", () => {pinned = false; point = null; refresh();});
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
    chart.on("plotly_relayouting", refresh);
    chart.on("plotly_afterplot", refresh);
    chart._axisArea = {refresh};
    refresh();
  };
})(typeof window === "undefined" ? globalThis : window);