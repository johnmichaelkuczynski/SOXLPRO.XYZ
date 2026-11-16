"""Public, read-only daily stock history for user-added comparison lines."""
import asyncio
import logging
import re
import time
from collections import OrderedDict

import tornado.web

log = logging.getLogger(__name__)
_cache = OrderedDict()
_inflight = {}


class StockHistoryUnavailable(RuntimeError):
    pass


def normalize_stock_symbol(value):
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,29}", symbol):
        raise ValueError("Enter a stock symbol such as AAPL, MSFT, or BRK.B.")
    return symbol


def load_stock_history(symbol):
    import os
    from chart_payload import clean_chart_points
    if not os.environ.get("EODHD_API_KEY", "").strip():
        raise StockHistoryUnavailable("Stock history is not configured. The owner must set EODHD_API_KEY.")
    from data_providers import get_custom_benchmark_history
    code = re.sub(r"\.([AB])$", r"-\1.US", symbol)
    history = get_custom_benchmark_history(code)
    values = history["Close"] if "Close" in history else []
    dates, prices = clean_chart_points(history.index, values)
    if len(dates) < 2:
        raise ValueError(f"No daily price history was found for {symbol}. Check the symbol and exchange.")
    return {"symbol": symbol, "dates": dates, "prices": prices, "source": "EODHD",
            "price_type": "Adjusted daily close", "through": dates[-1]}


async def stock_history(symbol):
    cached = _cache.get(symbol)
    if cached and time.monotonic() - cached[0] < 3600:
        _cache.move_to_end(symbol)
        return cached[1]
    if symbol not in _inflight:
        if len(_inflight) >= 8:
            raise RuntimeError("Stock history is busy. Please try again shortly.")
        _inflight[symbol] = asyncio.create_task(asyncio.to_thread(load_stock_history, symbol))
    task = _inflight[symbol]
    try:
        payload = await asyncio.shield(task)
        _cache[symbol] = (time.monotonic(), payload)
        _cache.move_to_end(symbol)
        while len(_cache) > 64:
            _cache.popitem(last=False)
        return payload
    finally:
        if task.done():
            _inflight.pop(symbol, None)


class StockHistory(tornado.web.RequestHandler):
    async def get(self):
        self.set_header("Content-Type", "application/json")
        self.set_header("Cache-Control", "no-store")
        try:
            symbol = normalize_stock_symbol(self.get_query_argument("symbol", ""))
            result = await stock_history(symbol)
            # Subscribe to the same quote worker used by existing benchmarks.
            from benchmark_quotes import read_quotes
            result = {**result, "quote": await asyncio.to_thread(read_quotes, symbol)}
            self.finish(result)
        except ValueError as exc:
            self.set_status(400)
            self.finish({"error": str(exc)})
        except StockHistoryUnavailable as exc:
            self.set_status(503)
            self.finish({"error": str(exc)})
        except Exception as exc:
            log.warning("Custom stock history unavailable: %s", type(exc).__name__)
            self.set_status(503)
            self.finish({"error": "Stock history is unavailable right now. Please try again."})
