const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("components/analytics/bridge.js", "utf8");

function browser(tracker) {
  const calls = [];
  const listeners = [];
  const timers = [];
  const host = {
    umami: tracker === undefined ? {track: (name, props) => calls.push({name, props})} : tracker,
    document: {addEventListener: (name, fn, capture) => listeners.push({name, fn, capture})},
    location: {href: "https://example.com/?private=not-analytics"},
    setTimeout: (fn) => {timers.push(fn); return timers.length;},
  };
  function mount(events = []) {
    const wrapper = {style: {}};
    const window = {
      parent: host,
      frameElement: {closest: () => wrapper},
      __APP_ANALYTICS_PENDING__: events,
    };
    // Deliberately no global `parent`: the bridge must retain the parent window
    // reference after Streamlit replaces its iframe.
    vm.runInNewContext(source, {window, URL});
    assert.equal(wrapper.style.display, "none");
  }
  function click(label, tagName = "BUTTON", attrs = {}) {
    const node = {
      tagName, textContent: label, parentNode: host.document,
      getAttribute: (key) => attrs[key] || null,
    };
    listeners[0].fn({target: node});
  }
  return {host, calls, listeners, timers, mount, click};
}

test("rerenders install one listener and deliver a queued event once", () => {
  const b = browser();
  const event = {id: "once:verified-payment", name: "payment_confirmed",
    properties: {plan: "full_access"}};
  b.mount([event]);
  b.mount([event]);
  assert.equal(b.listeners.length, 1);
  assert.equal(b.listeners[0].capture, true);
  assert.equal(b.calls.length, 1);
  assert.equal(b.calls[0].name, "payment_confirmed");
  assert.equal(JSON.stringify(b.calls).includes("once:"), false);
  b.click("Buy");
  assert.equal(b.calls[1].name, "buy_clicked");
});

test("login, checkout, feature and tool clicks emit only curated values", () => {
  const b = browser();
  b.mount();
  b.click("Sign in with Google");
  b.click("Sign in to buy");
  b.click("Sign out");
  b.click("Buy full access");
  b.click("Pay $0.99 USD with Stripe", "A",
    {href: "https://checkout.stripe.com/c/pay/private-session-id"});
  b.click("🌊 Vol Surface", "BUTTON", {role: "tab"});
  b.click("Calculate Probability");
  b.click("Run backtest");
  b.click("Run allocation engine");
  assert.deepEqual(b.calls.map(x => x.name), [
    "sign_in_clicked", "sign_in_clicked", "sign_out_clicked", "buy_clicked",
    "checkout_opened", "feature_viewed", "probability_calculation_requested",
    "backtest_requested", "backtest_requested",
  ]);
  assert.equal(JSON.stringify(b.calls).includes("private"), false);
  assert.equal(JSON.stringify(b.calls).includes("$0.99"), false);
});

test("ignores user content, extra event properties and misleading checkout URLs", () => {
  const b = browser();
  b.mount([{id: "bad", name: "payment_confirmed",
    properties: {plan: "full_access", email: "private@example.com"}}]);
  b.click("a private trading question");
  b.click("Pay $0.99 USD with Stripe", "A", {href: "https://example.com/fake"});
  b.click("Pay $0.99 USD with Stripe", "A", {href: "https://checkout.stripe.com.evil.test/fake"});
  assert.equal(b.calls.length, 0);
});

test("a late tracker safely receives queued events", () => {
  const b = browser(null);
  b.mount([{id: "late", name: "checkout_ready", properties: {location: "buy_dialog"}}]);
  assert.equal(b.calls.length, 0);
  b.host.umami = {track: (name, props) => b.calls.push({name, props})};
  b.timers.shift()();
  assert.equal(b.calls[0].name, "checkout_ready");
});

test("throwing and rejected trackers cannot break button handling", async () => {
  const b = browser({track: () => {throw new Error("unavailable");}});
  b.mount();
  assert.doesNotThrow(() => b.click("Buy"));
  b.host.umami = {track: () => Promise.reject(new Error("network unavailable"))};
  assert.doesNotThrow(() => b.click("Sign out"));
  await new Promise(resolve => setImmediate(resolve));
});

test("cross-origin parent access fails harmlessly", () => {
  const window = {};
  Object.defineProperty(window, "parent", {get() {throw new Error("cross-origin");}});
  assert.doesNotThrow(() => vm.runInNewContext(source, {window, URL}));
});