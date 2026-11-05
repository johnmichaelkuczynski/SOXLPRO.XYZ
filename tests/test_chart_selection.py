from chart_selection import BENCHMARKS, apply_benchmark_selection


def test_selection_applies_before_render_and_can_hide_all_benchmarks():
    state = {}
    assert apply_benchmark_selection(state, {
        "action": "set_benchmarks", "selection_id": "first",
        "selected_benchmarks": ["TQQQ"],
    })
    assert [s for s in BENCHMARKS if state["show_" + s.lower()]] == ["TQQQ"]
    assert apply_benchmark_selection(state, {
        "action": "set_benchmarks", "selection_id": "second",
        "selected_benchmarks": [],
    })
    assert not any(state["show_" + s.lower()] for s in BENCHMARKS)


def test_replayed_checkbox_event_does_not_override_other_controls():
    state = {}
    event = {"action": "set_benchmarks", "selection_id": "one",
             "selected_benchmarks": ["TQQQ"]}
    apply_benchmark_selection(state, event)
    state["show_qqq"] = True
    assert not apply_benchmark_selection(state, event)
    assert state["show_qqq"]
    assert not apply_benchmark_selection(state, {"action": "set_all", "lines": []})
