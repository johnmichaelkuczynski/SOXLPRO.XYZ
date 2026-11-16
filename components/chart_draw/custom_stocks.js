(function(root) {
  'use strict';
  function normalize(symbol) {
    symbol = String(symbol || '').trim().toUpperCase();
    if (!/^[A-Z0-9][A-Z0-9._-]{0,29}$/.test(symbol))
      throw Error('Enter a stock symbol such as AAPL, MSFT, or BRK.B.');
    return symbol;
  }
  function scaled(stock, base) {
    var baseline = new Map(base.dates.map(function(date, i) { return [date, base.prices[i]]; }));
    var ratio = null;
    for (var i = 0; i < stock.dates.length; i++) {
      var anchor = baseline.get(stock.dates[i]), price = stock.prices[i];
      if (Number.isFinite(anchor) && anchor > 0 && Number.isFinite(price) && price > 0) {
        ratio = anchor / price;
        break;
      }
    }
    if (ratio === null) throw Error('This stock has no trading dates in common with the SOXL chart.');
    return stock.prices.map(function(price) { return price * ratio; });
  }
  function install(options) {
    var stocks = new Map(), doc = options.document || document;
    var form = doc.getElementById('custom-stock-form');
    var input = doc.getElementById('custom-stock-symbol');
    var add = doc.getElementById('custom-stock-add');
    var status = doc.getElementById('custom-stock-status');
    var list = doc.getElementById('custom-stock-list');
    var colors = ['#7c3aed', '#0e7490', '#be185d', '#b45309', '#166534', '#37474f'];
    function entries() { return Array.from(stocks.values()); }
    function renderList() {
      list.replaceChildren();
      stocks.forEach(function(stock, symbol) {
        var row = doc.createElement('div');
        row.style.cssText = 'display:flex;gap:6px;align-items:center;margin:5px 0;';
        var label = doc.createElement('label'), toggle = doc.createElement('input');
        toggle.type = 'checkbox'; toggle.checked = stock.visible;
        toggle.setAttribute('aria-label', 'Show ' + symbol + ' on chart');
        toggle.addEventListener('change', function() { stock.visible = toggle.checked; options.changed(); });
        label.appendChild(toggle);
        label.appendChild(doc.createTextNode(' ' + symbol));
        label.style.cssText = 'flex:1;color:' + stock.color + ';font-weight:700;';
        var remove = doc.createElement('button');
        remove.type = 'button'; remove.textContent = 'Remove';
        remove.setAttribute('aria-label', 'Remove ' + symbol + ' from chart');
        remove.addEventListener('click', function() {
          stocks.delete(symbol); renderList(); options.changed();
          status.textContent = symbol + ' removed.';
        });
        row.appendChild(label); row.appendChild(remove); list.appendChild(row);
      });
    }
    async function submit(event) {
      event.preventDefault();
      if (add.disabled) return;
      var symbol;
      try { symbol = normalize(input.value); } catch (error) { status.textContent = error.message; return; }
      input.value = symbol;
      if (symbol === 'SOXL') { status.textContent = 'SOXL is already on the chart.'; return; }
      if (options.showExisting && options.showExisting(symbol)) {
        status.textContent = symbol + ' is now shown on the chart.'; return;
      }
      if (stocks.has(symbol)) {
        stocks.get(symbol).visible = true; renderList(); options.changed();
        status.textContent = symbol + ' is already added.'; return;
      }
      add.disabled = true;
      status.textContent = 'Loading ' + symbol + '…';
      try {
        var response = await (options.fetch || fetch)('/api/chart/stock?symbol=' + encodeURIComponent(symbol));
        var stock = await response.json();
        if (!response.ok) throw Error(stock.error || 'Could not load that stock.');
        if (!stock.dates || stock.dates.length < 2 || stock.dates.length !== stock.prices.length ||
            stock.prices.some(function(value) { return !Number.isFinite(value) || value <= 0; }))
          throw Error('The provider returned no usable daily price history.');
        scaled(stock, options.base());
        stock.visible = true; stock.color = colors[stocks.size % colors.length];
        stocks.set(symbol, stock);
        if (stock.quote && options.quotes) options.quotes(stock.quote);
        renderList(); options.changed();
        status.textContent = symbol + ' added · ' + stock.source + ' · daily history through ' +
          stock.through + '. Scaled for comparison; hover for actual prices.';
      } catch (error) {
        status.textContent = error.message || 'Stock history is unavailable.';
      } finally { add.disabled = false; }
    }
    form.addEventListener('submit', submit);
    return {
      entries: entries,
      traces: function(base) {
        return entries().filter(function(stock) { return stock.visible; }).map(function(stock) {
          return {x:stock.dates, y:scaled(stock, base), customdata:stock.prices,
            mode:'lines', name:stock.symbol, yaxis:'y',
            line:{color:stock.color, width:2.2},
            hovertemplate:stock.symbol + ': %{x|%Y-%m-%d}<br>Actual adjusted close: $%{customdata:,.2f}<extra></extra>'};
        });
      }
    };
  }
  var api = {normalize:normalize, scaled:scaled, install:install};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SOXLCustomStocks = api;
})(typeof window !== 'undefined' ? window : globalThis);
