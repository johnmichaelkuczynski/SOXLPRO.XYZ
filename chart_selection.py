"""Apply chart checkbox events before Streamlit builds chart arguments."""

BENCHMARKS = ("QQQ", "TQQQ", "TLT", "XLU", "VIX", "SOX", "GUSH", "BTC")


def apply_benchmark_selection(state, event):
    if not isinstance(event, dict) or event.get("action") != "set_benchmarks":
        return False
    event_id = event.get("selection_id")
    if not event_id or event_id == state.get("_last_benchmark_selection"):
        return False
    selected = event.get("selected_benchmarks")
    if not isinstance(selected, list):
        return False
    state["_last_benchmark_selection"] = event_id
    for symbol in BENCHMARKS:
        state["show_" + symbol.lower()] = symbol in selected
    return True
