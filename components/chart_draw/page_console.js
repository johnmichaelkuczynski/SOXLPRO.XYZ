(function (root) {
  "use strict";

  function placement(state, viewport, frame, plot) {
    const margin = 8;
    const floor = Math.max(margin, viewport.header + margin);
    const width = Math.min(state.width, viewport.width - margin * 2);
    const height = Math.max(140, Math.min(state.height, viewport.height - floor - margin));
    const free = state.dock === "free";
    const below = state.dock === "bottom";
    const origin = frame.top + (below ? plot.parking : plot.top) + 12;
    const end = frame.top + (below ? plot.parking + height + 24 : plot.bottom);
    const wantedLeft = free ? state.left :
      state.dock === "left" ? frame.left + 12 :
      below && Number.isFinite(state.left) ? frame.left + state.left : frame.right - width - 12;
    const left = Math.max(margin, Math.min(Number.isFinite(wantedLeft) ? wantedLeft : margin,
      viewport.width - width - margin));
    const wantedTop = free && Number.isFinite(state.top) ? state.top : origin;
    const top = Math.max(floor, Math.min(wantedTop, free ? viewport.height - 64 : Number.MAX_VALUE));
    return {left, top, width, maxHeight: Math.max(140, Math.min(height, viewport.height - top - margin)),
      visible: free || (origin < viewport.height - 140 && end > floor + 20)};
  }

  function scopeRules(rules, prefix) {
    return Array.from(rules || []).map(function (rule) {
      if (rule.selectorText) {
        const selectors = rule.selectorText.split(",").map(s => s.trim()).filter(s => s !== "body");
        return selectors.length ? selectors.map(s => prefix + " " + s).join(",") +
          "{" + rule.style.cssText + "}" : "";
      }
      if (rule.cssRules && rule.conditionText) {
        return "@media " + rule.conditionText + "{" + scopeRules(rule.cssRules, prefix) + "}";
      }
      return "";
    }).join("\n");
  }

  function install(options) {
    const doc = root.document;
    if (!root.frameElement || new URLSearchParams(root.location.search).has("diagnostics_sandbox"))
      return null;
    let parentDoc;
    try {
      parentDoc = root.parent.document;
      if (!parentDoc.body) return null;
    } catch (_) {
      console.warn("The host does not allow the console outside the embedded chart.");
      return null;
    }

    const prior = parentDoc.getElementById("soxl-floating-console");
    if (prior && prior.disposeConsole) prior.disposeConsole();
    const host = parentDoc.createElement("div");
    host.id = "soxl-floating-console";
    host.style.cssText = "position:fixed;inset:0;z-index:2147483000;pointer-events:none;" +
      "font:14px -apple-system,BlinkMacSystemFont,sans-serif;visibility:hidden";
    const style = parentDoc.createElement("style");
    style.textContent = scopeRules(doc.getElementById("chart-controls-styles").sheet.cssRules,
      "#soxl-floating-console");
    host.appendChild(style);
    const nodes = [options.toolbar, options.handles, options.tab];
    const originals = {};
    const bindings = [];
    const origins = nodes.map(function (node) {
      const marker = doc.createComment("floating console home");
      node.parentNode.insertBefore(marker, node);
      return {node, marker, style:node.getAttribute("style")};
    });
    let observer;
    const api = {active:true, host, position, dispose};
    const frame = root.frameElement;

    function dispose() {
      if (!api.active) return;
      api.active = false;
      if (observer) observer.disconnect();
      nodes.forEach(function (node) {
        node.dispatchEvent(new root.Event("console-dispose"));
      });
      origins.forEach(function (entry) {
        if (entry.marker.parentNode) entry.marker.parentNode.insertBefore(entry.node, entry.marker);
        entry.marker.remove();
        if (entry.style === null) entry.node.removeAttribute("style");
        else entry.node.setAttribute("style", entry.style);
      });
      bindings.forEach(function (binding) {
        binding.node.removeEventListener(binding.type, binding.callback);
        binding.node.setAttribute("on" + binding.type, binding.code);
      });
      Object.keys(originals).forEach(name => { doc[name] = originals[name]; });
      host.remove();
      root.removeEventListener("pagehide", dispose);
      if (options.cleanup) options.cleanup();
    }
    host.disposeConsole = dispose;

    try {
      // Reuse the real controls and their existing listeners. Inline handlers
      // must retain the chart window's functions after document adoption.
      nodes.forEach(function (node) {
        [node].concat(Array.from(node.querySelectorAll("*"))).forEach(function (element) {
          ["click", "input", "change", "keydown"].forEach(function (type) {
            const code = element.getAttribute("on" + type);
            if (!code) return;
            const handler = new root.Function("event", code);
            const callback = function (event) { return handler.call(element, event); };
            bindings.push({node:element, type, callback, code});
            element.removeAttribute("on" + type);
            element.addEventListener(type, callback);
          });
        });
        host.appendChild(node);
      });
      parentDoc.body.appendChild(host);
      options.toolbar.style.pointerEvents = "auto";
      options.tab.style.pointerEvents = "auto";
      options.handles.querySelectorAll(".rail-resize-handle").forEach(function (handle) {
        handle.style.pointerEvents = "auto";
      });
      // Keep existing component lookups working. Only this isolated component
      // document is bridged; the app's document and React tree are untouched.
      ["getElementById", "querySelector", "querySelectorAll"].forEach(function (name) {
        originals[name] = doc[name];
        doc[name] = function (selector) {
          const found = originals[name].call(doc, selector);
          if (name === "querySelectorAll" ? found.length : !!found) return found;
          return name === "getElementById" ?
            host.querySelector("#" + root.CSS.escape(selector)) : host[name](selector);
        };
      });
      root.addEventListener("pagehide", dispose, {once:true});
      observer = new root.parent.MutationObserver(function () {
        if (!frame.isConnected) dispose();
      });
      observer.observe(parentDoc.body, {childList:true, subtree:true});
      return api;
    } catch (error) {
      dispose();
      console.warn("Console undocking failed; original controls were retained.", error.name);
      return null;
    }

    function position() {
      if (!api.active) return;
      const state = options.state();
      const rect = frame.getBoundingClientRect();
      const header = parentDoc.querySelector('[data-testid="stHeader"]');
      const box = placement(state, {
        width:root.parent.innerWidth, height:root.parent.innerHeight,
        header:header ? Math.max(0, header.getBoundingClientRect().bottom) : 0,
      }, rect, options.plot());
      host.style.visibility = box.visible ? "visible" : "hidden";
      options.toolbar.style.left = box.left + "px";
      options.toolbar.style.right = "auto";
      options.toolbar.style.top = box.top + "px";
      options.toolbar.style.maxHeight = box.maxHeight + "px";
      options.tab.style.left = box.left + "px";
      options.tab.style.right = "auto";
      options.tab.style.top = box.top + "px";
      options.positionHandles();
    }
  }

  const api = {placement, scopeRules, install};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SOXLFloatingConsole = api;
})(typeof window !== "undefined" ? window : globalThis);
