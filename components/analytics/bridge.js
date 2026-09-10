(function analyticsBridge(global) {
  "use strict";

  /*
   * This file is intentionally only a bridge.  Replit injects Umami into the
   * published parent page; this component does not load a script or contact a
   * collector.
   */
  var parentWindow;
  try {
    parentWindow = global.parent;
    if (!parentWindow || !parentWindow.document) return;
  } catch (_) {
    return;
  }
  try {
    // Hide only our component's wrapper, not any other iframe or chart.
    var ownFrame = global.frameElement;
    var ownContainer = ownFrame && ownFrame.closest('[data-testid="stElementContainer"]');
    if (ownContainer) ownContainer.style.display = "none";
  } catch (_) {}

  var STATE_KEY = "__soxlAnalyticsBridgeState";
  var MAX_SEEN = 512;
  var MAX_PENDING = 128;
  var RETRIES = 6;
  var RETRY_DELAY = 500;

  var SERVER_EVENTS = {
    checkout_ready: { location: ["buy_dialog"] },
    checkout_error: { stage: ["checkout", "confirmation"] },
    checkout_cancelled: { location: ["return"] },
    payment_confirmed: { plan: ["full_access"] },
    signed_in_session: { tier: ["signed_in", "paid"] },
    market_question_submitted: { feature: ["market_chat"] },
    market_answer_received: { feature: ["market_chat"] },
    strategy_requested: { feature: ["strategy_builder"] },
    strategy_generated: { feature: ["strategy_builder"] },
    sign_in_clicked: { location: ["header", "checkout"] },
    sign_out_clicked: { location: ["header"] },
    buy_clicked: { location: ["header", "feature_gate"] },
    checkout_opened: { location: ["buy_dialog"] },
    probability_calculation_requested: { feature: ["probability_engine"] },
    backtest_requested: { feature: ["backtest", "allocation_engine"] },
    feature_viewed: {
      feature: [
        "chart_probabilities",
        "vol_surface",
        "call_risk_reward",
        "soxl_qqq_dislocation",
        "strategy_builder",
        "backtest",
        "diagnostic"
      ]
    }
  };

  var state;
  try {
    state = parentWindow[STATE_KEY];
    if (!state || typeof state !== "object") {
      state = {
        listenerInstalled: false,
        seenQueueIds: [],
        pending: [],
        retryCount: 0,
        retryTimer: null,
        clickSequence: 0
      };
      parentWindow[STATE_KEY] = state;
    }
    if (!Array.isArray(state.seenQueueIds)) state.seenQueueIds = [];
    if (!Array.isArray(state.pending)) state.pending = [];
    if (typeof state.retryCount !== "number") state.retryCount = 0;
    if (!Object.prototype.hasOwnProperty.call(state, "retryTimer")) {
      state.retryTimer = null;
    }
    if (typeof state.clickSequence !== "number") state.clickSequence = 0;
  } catch (_) {
    return;
  }

  function validatedProperties(name, properties) {
    var spec = SERVER_EVENTS[name];
    if (!spec || !properties || typeof properties !== "object") return null;
    var keys = Object.keys(properties);
    var expected = Object.keys(spec);
    if (keys.length !== expected.length) return null;
    var clean = {};
    for (var i = 0; i < expected.length; i += 1) {
      var key = expected[i];
      if (!Object.prototype.hasOwnProperty.call(properties, key)) return null;
      if (typeof properties[key] !== "string" ||
          spec[key].indexOf(properties[key]) < 0) return null;
      clean[key] = properties[key];
    }
    return clean;
  }

  function allowedEvent(name, properties) {
    return !!validatedProperties(name, properties);
  }

  function seen(id) {
    return state.seenQueueIds.indexOf(id) >= 0;
  }

  function remember(id) {
    if (seen(id)) return;
    state.seenQueueIds.push(id);
    if (state.seenQueueIds.length > MAX_SEEN) {
      state.seenQueueIds.splice(0, state.seenQueueIds.length - MAX_SEEN);
    }
  }

  // Keep all interaction with the injected tracker in one failure-proof
  // wrapper.  The optional chaining handles an unpublished/missing tracker;
  // the promise handler handles an asynchronous rejection.
  function safeTrack(name, properties) {
    try {
      if (!parentWindow.umami || typeof parentWindow.umami.track !== "function") {
        return false;
      }
      var result = parentWindow.umami?.track?.(name, properties);
      if (result && typeof result.catch === "function") {
        result.catch(function () {});
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  function pendingHas(id) {
    for (var i = 0; i < state.pending.length; i += 1) {
      if (state.pending[i].id === id) return true;
    }
    return false;
  }

  function queueForDelivery(event) {
    if (!event || typeof event !== "object") return;
    if (typeof event.id !== "string" || !event.id || event.id.length > 128) return;
    var cleanProperties = validatedProperties(event.name, event.properties);
    if (!cleanProperties) return;
    if (seen(event.id) || pendingHas(event.id)) return;
    if (state.pending.length >= MAX_PENDING) state.pending.shift();
    state.pending.push({
      id: event.id,
      name: event.name,
      properties: cleanProperties
    });
  }

  function removePending(id) {
    state.pending = state.pending.filter(function (event) {
      return event.id !== id;
    });
  }

  function scheduleRetry() {
    if (state.retryTimer || !state.pending.length || state.retryCount >= RETRIES) return;
    var setTimer = parentWindow.setTimeout || global.setTimeout;
    if (typeof setTimer !== "function") return;
    state.retryTimer = setTimer(function () {
      state.retryTimer = null;
      state.retryCount += 1;
      drain();
    }, RETRY_DELAY);
  }

  function drain() {
    var batch = state.pending.slice();
    for (var i = 0; i < batch.length; i += 1) {
      var event = batch[i];
      if (safeTrack(event.name, event.properties)) {
        remember(event.id);
        removePending(event.id);
      }
    }
    if (!state.pending.length) state.retryCount = 0;
    else scheduleRetry();
  }

  function emitBrowserEvent(id, name, properties) {
    var cleanProperties = validatedProperties(name, properties);
    if (!cleanProperties) return;
    queueForDelivery({ id: id, name: name, properties: cleanProperties });
    drain();
  }

  function normalizedText(element) {
    if (!element) return "";
    var text = (element.textContent || "").replace(/\s+/g, " ").trim();
    return text;
  }

  function withoutEmoji(text) {
    // Covers the emoji ranges used by the app without stripping punctuation
    // from labels such as SOXL-QQQ or Call Risk/Reward.
    return text
      .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\uFE0F]/gu, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function clickable(target) {
    var node = target;
    while (node && node !== parentWindow.document) {
      var tag = (node.tagName || "").toLowerCase();
      if (tag === "button" || tag === "a" ||
          (node.getAttribute && node.getAttribute("role") === "tab")) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function stripeCheckoutLink(element, label) {
    if (!element || (element.tagName || "").toLowerCase() !== "a") return false;
    if (!/^Pay .+ with Stripe$/.test(label)) return false;
    try {
      var url = new URL(element.getAttribute("href") || "", parentWindow.location.href);
      return url.hostname.toLowerCase() === "checkout.stripe.com";
    } catch (_) {
      return false;
    }
  }

  function handleClick(event) {
    try {
      var element = clickable(event && event.target);
      if (!element) return;
      var label = normalizedText(element);
      var tabLabel = withoutEmoji(label);
      state.clickSequence += 1;
      var id = "click:" + state.clickSequence;

      if (label === "Sign in with Google") {
        emitBrowserEvent(id, "sign_in_clicked", { location: "header" });
      } else if (label === "Sign in to buy") {
        emitBrowserEvent(id, "sign_in_clicked", { location: "checkout" });
      } else if (label === "Sign out") {
        emitBrowserEvent(id, "sign_out_clicked", { location: "header" });
      } else if (label === "Buy") {
        emitBrowserEvent(id, "buy_clicked", { location: "header" });
      } else if (label === "Buy full access") {
        emitBrowserEvent(id, "buy_clicked", { location: "feature_gate" });
      } else if (stripeCheckoutLink(element, label)) {
        emitBrowserEvent(id, "checkout_opened", { location: "buy_dialog" });
      } else if (label === "Calculate Probability") {
        emitBrowserEvent(
          id, "probability_calculation_requested", { feature: "probability_engine" }
        );
      } else if (label === "Run backtest") {
        emitBrowserEvent(id, "backtest_requested", { feature: "backtest" });
      } else if (label === "Run allocation engine") {
        emitBrowserEvent(id, "backtest_requested", { feature: "allocation_engine" });
      } else {
        var tabs = {
          "Chart & Probabilities": "chart_probabilities",
          "Vol Surface": "vol_surface",
          "Call Risk/Reward": "call_risk_reward",
          "SOXL-QQQ Dislocation": "soxl_qqq_dislocation",
          "Strategy Builder": "strategy_builder",
          "Backtest": "backtest",
          "Diagnostic": "diagnostic"
        };
        if (Object.prototype.hasOwnProperty.call(tabs, tabLabel)) {
          emitBrowserEvent(id, "feature_viewed", { feature: tabs[tabLabel] });
        }
      }
    } catch (_) {
      // A click must never be changed or cancelled by analytics.
    }
  }

  try {
    if (!state.listenerInstalled) {
      parentWindow.document.addEventListener("click", handleClick, true);
      state.listenerInstalled = true;
    }
  } catch (_) {
    return;
  }

  try {
    var initial = global.__APP_ANALYTICS_PENDING__;
    if (Array.isArray(initial)) {
      for (var i = 0; i < initial.length; i += 1) queueForDelivery(initial[i]);
      drain();
    }
    try {
      delete global.__APP_ANALYTICS_PENDING__;
    } catch (_) {}
  } catch (_) {
    // Invalid component input is ignored, while the parent listener remains.
  }
})(window);