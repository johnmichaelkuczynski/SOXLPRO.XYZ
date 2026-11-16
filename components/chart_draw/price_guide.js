(function (root) {
  "use strict";

  function geometry(quote, layout) {
    if (!quote || !["Tiingo", "Schwab"].includes(quote.source)) return null;
    return pointGeometry({price: quote.price, time: quote.observed_at}, layout);
  }

  function pointGeometry(point, layout) {
    if (!point || !Number.isFinite(point.price) || point.price <= 0 ||
        !Number.isFinite(Date.parse(point.time)) || !layout) return null;
    const x = layout.xaxis, y = layout.yaxis;
    if (!x || !y) return null;
    const left = x._offset, right = left + x._length;
    const top = y._offset, bottom = top + y._length;
    // Plotly's data-to-pixel conversion handles both log and linear axes.
    const py = y._offset + y.d2p(point.price);
    const px = x._offset + x.d2p(point.time);
    if (![left, right, top, bottom, px, py].every(Number.isFinite) ||
        py < top || py > bottom || px < left) return null;
    return {left, end: Math.min(px, right), y: py, endpointVisible: px <= right};
  }

  function pickPoint(layout, px, py) {
    if (!layout || !layout.xaxis || !layout.yaxis) return null;
    const x = layout.xaxis, y = layout.yaxis;
    if (!Number.isFinite(px) || !Number.isFinite(py) ||
        px < x._offset || px > x._offset + x._length ||
        py < y._offset || py > y._offset + y._length) return null;
    // p2d is the inverse of d2p, including log-axis conversion.
    const price = y.p2d(py - y._offset);
    const date = x.p2d(px - x._offset);
    const time = typeof date === "number" ? new Date(date).toISOString() : date;
    if (!Number.isFinite(price) || price <= 0 || !Number.isFinite(Date.parse(time))) return null;
    return {price, time};
  }

  function horizontalLinePoints(lines, layout) {
    if (!layout || !layout.yaxis) return [];
    return (lines || []).flatMap(line => {
      if (![line.y1, line.y2].every(value => Number.isFinite(value) && value > 0)) return [];
      const y1 = layout.yaxis.d2p(line.y1), y2 = layout.yaxis.d2p(line.y2);
      // Recognize a hand-drawn horizontal line with a few pixels of tolerance.
      if (!Number.isFinite(y1) || !Number.isFinite(y2) || Math.abs(y2 - y1) > 4) return [];
      const start = Number.isFinite(line.x1_ms) ? line.x1_ms : Date.parse(line.x1);
      const end = Number.isFinite(line.x2_ms) ? line.x2_ms : Date.parse(line.x2);
      if (!Number.isFinite(start) || !Number.isFinite(end) || start === end) return [];
      const price = start > end ? line.y1 : line.y2;
      return [{price, time: new Date(Math.max(start, end)).toISOString(),
        color: line.color || "#92400e"}];
    });
  }

  if (typeof module !== "undefined")
    module.exports = {geometry, pointGeometry, pickPoint, horizontalLinePoints};
  if (!root.document) return;

  root.installPriceGuide = function (chart, getQuote, getLines) {
    if (chart._priceGuide) { chart._priceGuide.refresh(); return; }
    const toggle = document.getElementById("priceGuideToggle");
    const pick = document.getElementById("pickPricePoint");
    const remove = document.getElementById("removePricePoint");
    const status = document.getElementById("pickedPriceStatus");
    let picking = false, picked = null;
    let enabled = true;
    try { enabled = localStorage.getItem("soxl-price-guide") !== "off"; } catch (_) {}
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("aria-hidden", "true");
    svg.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:4;overflow:hidden";
    chart.appendChild(svg);
    function add(tag, attributes, text) {
      const node = document.createElementNS(svg.namespaceURI, tag);
      Object.keys(attributes).forEach(key => node.setAttribute(key, attributes[key]));
      if (text) node.textContent = text;
      svg.appendChild(node);
      return node;
    }
    function priceLabel(price) {
      return "$" + price.toLocaleString("en-US", {
        minimumFractionDigits: 2, maximumFractionDigits: price < 1 ? 6 : 2
      });
    }
    function draw(point, price, color, dashed) {
      add("line", {x1: point.left, x2: point.end, y1: point.y, y2: point.y,
        stroke: color, "stroke-width": 2, "stroke-dasharray": dashed ? "6 4" : ""});
      if (point.endpointVisible)
        add("circle", {cx: point.end, cy: point.y, r: 5, fill: color,
          stroke: "white", "stroke-width": 1.5});
      const label = priceLabel(price);
      const width = Math.max(54, label.length * 7 + 10);
      add("rect", {x: Math.max(0, point.left - width), y: point.y - 12,
        width, height: 24, rx: 3, fill: "#0f172a", stroke: color, "stroke-width": 2});
      add("text", {x: point.left - 5, y: point.y + 4, fill: "white",
        "text-anchor": "end", "font-size": 12, "font-family": "sans-serif",
        "font-weight": 700}, label);
    }
    function refresh() {
      if (!svg.isConnected) chart.appendChild(svg);
      svg.replaceChildren();
      toggle.setAttribute("aria-pressed", String(enabled));
      toggle.classList.toggle("active", enabled);
      toggle.textContent = "Current Price Line: " + (enabled ? "On" : "Off");
      pick.classList.toggle("active", picking);
      pick.setAttribute("aria-pressed", String(picking));
      pick.textContent = picking ? "Cancel Picking Price Point" : "Pick Price Point";
      remove.disabled = !picked;
      status.textContent = picking ? "Click anywhere inside the plot. Escape cancels." :
        picked ? "Picked price: " + priceLabel(picked.price) : "";
      const quote = getQuote();
      toggle.title = quote
        ? "Horizontal guide to the latest price, with its exact dollar price on the Y-axis."
        : "No current quote is available. The guide will appear when a quote arrives.";
      svg.setAttribute("width", chart.clientWidth);
      svg.setAttribute("height", chart.clientHeight);
      const point = enabled && geometry(quote, chart._fullLayout);
      if (point) {
        add("title", {}, "SOXL " + priceLabel(quote.price) + " · " +
          quote.observed_at + " · Latest available trade");
        draw(point, quote.price, "#1565c0", true);
      }
      horizontalLinePoints(getLines ? getLines() : [], chart._fullLayout).forEach(line => {
        const point = pointGeometry(line, chart._fullLayout);
        if (point) draw(point, line.price, line.color, false);
      });
      const selected = pointGeometry(picked, chart._fullLayout);
      if (selected) draw(selected, picked.price, "#92400e", false);
      if (picking && chart._fullLayout) {
        const x = chart._fullLayout.xaxis, y = chart._fullLayout.yaxis;
        const target = add("rect", {x: x._offset, y: y._offset,
          width: x._length, height: y._length, fill: "transparent",
          "pointer-events": "all", cursor: "crosshair"});
        target.addEventListener("pointerdown", event => {
          event.stopPropagation();
        });
        target.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          const rect = svg.getBoundingClientRect();
          const point = pickPoint(chart._fullLayout, event.clientX - rect.left, event.clientY - rect.top);
          if (!point) return;
          if (typeof root.saveUndoState === "function") root.saveUndoState();
          picked = point;
          picking = false;
          refresh();
        });
      }
    }
    toggle.addEventListener("click", function () {
      if (typeof root.saveUndoState === "function") root.saveUndoState();
      enabled = !enabled;
      try { localStorage.setItem("soxl-price-guide", enabled ? "on" : "off"); } catch (_) {}
      refresh();
    });
    pick.addEventListener("click", function () {
      picking = !picking;
      if (picking && typeof root.setMode === "function" && root.currentMode !== "pan")
        root.setMode("pan");
      // Picking is explicit and does not alter Plotly's viewport or drawings.
      refresh();
    });
    remove.addEventListener("click", function () {
      if (typeof root.saveUndoState === "function") root.saveUndoState();
      picked = null;
      picking = false;
      refresh();
    });
    window.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && picking) { picking = false; refresh(); }
    });
    let lastTap = null, press = null, lastActivation = null;
    function pointFromEvent(event) {
      if (event.altKey || event.target.closest &&
          event.target.closest(".modebar, #toolbar, #axisAreaOutput, [data-channel-handle], button, input, select")) return null;
      const rect = chart.getBoundingClientRect();
      return pickPoint(chart._fullLayout, event.clientX - rect.left, event.clientY - rect.top);
    }
    function showPoint(event) {
      const point = pointFromEvent(event);
      if (!point) return false;
      const now = Date.now();
      // A native dblclick can follow the pointer gesture on some browsers.
      // It must not add a second undo entry for the same double-click.
      if (lastActivation && now - lastActivation.time < 500 &&
          Math.hypot(event.clientX - lastActivation.x, event.clientY - lastActivation.y) < 10) return true;
      lastActivation = {time:now, x:event.clientX, y:event.clientY};
      if (typeof root.saveUndoState === "function") root.saveUndoState();
      if (chart._axisArea) chart._axisArea.restore(null);
      picked = point;
      picking = false;
      refresh();
      return true;
    }
    // Plotly's pan/drag layer can suppress the browser's native dblclick.
    // Observe real pointer taps in capture phase instead, including the
    // sibling selection overlay. Ordinary pan/drag gestures remain intact.
    const gestureHost = chart.parentElement || chart;
    gestureHost.addEventListener("pointerdown", function(event) {
      if (event.button !== 0 || !pointFromEvent(event)) { press = null; return; }
      press = {x:event.clientX, y:event.clientY, id:event.pointerId, moved:false};
    }, true);
    gestureHost.addEventListener("pointermove", function(event) {
      if (press && Math.hypot(event.clientX - press.x, event.clientY - press.y) > 7) press.moved = true;
    }, true);
    gestureHost.addEventListener("pointerup", function(event) {
      const start = press;
      press = null;
      if (!start || start.id !== event.pointerId || start.moved || !pointFromEvent(event) ||
          Math.hypot(event.clientX - start.x, event.clientY - start.y) > 7) { lastTap = null; return; }
      const now = Date.now();
      if (lastTap && now - lastTap.time <= 550 &&
          Math.hypot(event.clientX - lastTap.x, event.clientY - lastTap.y) <= 10) {
        lastTap = null;
        showPoint(event);
      } else {
        lastTap = {time:now, x:event.clientX, y:event.clientY};
      }
    }, true);
    gestureHost.addEventListener("pointercancel", function() { press = null; lastTap = null; }, true);
    chart.addEventListener("dblclick", function(event) {
      if (!showPoint(event)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    }, true);
    chart.on("plotly_afterplot", refresh);
    chart.on("plotly_relayout", refresh);
    window.addEventListener("resize", refresh);
    chart._priceGuide = {
      refresh,
      snapshot: () => ({enabled, picked: picked ? {...picked} : null}),
      restore: state => {
        enabled = state ? state.enabled : true;
        picked = state && state.picked ? {...state.picked} : null;
        picking = false;
        try { localStorage.setItem("soxl-price-guide", enabled ? "on" : "off"); } catch (_) {}
        refresh();
      }
    };
    refresh();
  };
})(typeof window !== "undefined" ? window : globalThis);
