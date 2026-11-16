(function (root) {
  "use strict";
  root.installPageActions = function (actions) {
    if (root._chartPageActions) return root._chartPageActions;
    const doc = document;
    try {
      const oldOverlay = root.parent.document.getElementById("soxl-page-actions");
      if (oldOverlay) oldOverlay.remove();
    } catch (_) {}
    const prior = doc.getElementById("soxl-page-actions");
    if (prior) prior.remove();
    const box = doc.createElement("div");
    box.id = "soxl-page-actions";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", "Chart emergency controls");
    box.style.cssText = "display:flex;flex-direction:row;gap:8px;align-items:center;" +
      "justify-content:flex-end;max-width:100%";
    function button(label, color, callback, outlined) {
      const el = doc.createElement("button");
      el.type = "button";
      el.textContent = label;
      el.style.cssText = "width:112px;min-height:36px;border:1px solid " + color +
        ";border-radius:6px;font:650 14px system-ui;cursor:pointer;" +
        "box-shadow:0 1px 3px #0002;color:" + (outlined ? color : "white") +
        ";background:" + (outlined ? "#ffffff" : color);
      el.addEventListener("click", callback);
      box.appendChild(el);
      return el;
    }
    button("Clear All", "#b91c1c", actions.clear, true);
    const undo = button("Undo", "#1d4ed8", actions.undo, false);
    (doc.getElementById("chart-action-row") || doc.body).appendChild(box);
    root._chartPageActions = {
      update: function (count) {
        undo.title = count ? "Undo the last chart change" : "No chart changes to undo yet";
        undo.setAttribute("aria-label", undo.title);
      }
    };
    root._chartPageActions.update(0);
    return root._chartPageActions;
  };
})(window);
