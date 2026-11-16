const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('components/chart_draw/index.html', 'utf8');
const elements = new Map();
const element = id => {
  if (!elements.has(id)) elements.set(id, {textContent: 'old message', title: 'old title'});
  return elements.get(id);
};
const context = vm.createContext({
  document: {getElementById: element},
  latestMarketQuote: null,
  marketFeedError: 'Current price unavailable. Price feed app keys are not configured.',
});
for (const name of ['updateMarketSummary', 'updateMarketFeedStatus']) {
  const definition = html.match(new RegExp(`function ${name}\\(\\) \\{[\\s\\S]*?\\n\\}`));
  assert.ok(definition, `${name} exists`);
  vm.runInContext(definition[0], context);
}

context.updateMarketFeedStatus();
assert.equal(element('market-feed-status').textContent, '');
assert.equal(element('market-feed-status').title, '');
assert.equal(element('market-summary-state').textContent, '');
for (const session of ['regular', 'post', 'pre']) {
  assert.equal(element(`market-${session}-price`).textContent, '—');
  assert.equal(element(`market-${session}-time`).textContent, '');
}

// Even a retained older quote plus a feed failure must not add warning prose.
context.latestMarketQuote = {
  price: 50.25, session: 'Regular session',
  observed_at: '2020-01-01T15:00:00Z', observed_label: 'Jan 1, 2020 10:00 AM ET',
};
context.updateMarketFeedStatus();
assert.equal(element('market-feed-status').textContent,
  'SOXL $50.25 · Regular session · Jan 1, 2020 10:00 AM ET');
assert.equal(element('market-feed-status').title, '');
assert.equal(element('market-regular-price').textContent, '$50.2500');
assert.equal(element('market-regular-time').textContent, 'Jan 1, 2020 10:00 AM ET');
assert.equal(element('market-summary-state').textContent, '');
console.log('Chart quote presentation: missing-price and feed-error paths passed.');
