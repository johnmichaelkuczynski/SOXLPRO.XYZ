"""Fixed, non-user-configurable regression suite. Only sanitized summaries leave here."""
import contextlib
import io
import json
from pathlib import Path

from full_diagnostics import TEST_GROUPS, result


def main():
    rows, mapping, paths = [], {}, []
    for group, files in TEST_GROUPS.items():
        for name in files:
            path = Path("tests") / name
            if path.is_file():
                mapping[path.as_posix()] = group
                paths.append(path.as_posix())
            else:
                rows.append(result(group, "Regression tests", "not_tested",
                                   f"{name} was not included in this deployment."))
    try:
        import pytest
    except ImportError:
        print("SOXL_DIAGNOSTICS=" + json.dumps([
            result("Feature regression suite", "Regression tests", "not_tested",
                   "pytest is not installed in this deployment.")]))
        return
    counts = {group: {"passed": 0, "failed": 0, "skipped": 0} for group in TEST_GROUPS}
    failures = {group: [] for group in TEST_GROUPS}
    collection_errors = []

    class Evidence:
        def pytest_collectreport(self, report):
            if report.failed:
                collection_errors.append(report.nodeid.split("::")[0])

        def pytest_runtest_logreport(self, report):
            group = mapping.get(report.nodeid.split("::")[0])
            if not group:
                return
            if report.failed:
                counts[group]["failed"] += 1
                failures[group].append(report.nodeid)
            elif report.skipped:
                counts[group]["skipped"] += 1
            elif report.when == "call":
                counts[group]["passed"] += 1

    if paths:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pytest.main(["-q", "--tb=no", "--disable-warnings", "-p", "no:cacheprovider", *paths],
                        plugins=[Evidence()])
    for group, count in counts.items():
        status = ("fail" if count["failed"] else "not_tested" if not count["passed"]
                  else "warning" if count["skipped"] else "pass")
        rows.append(result(group, "Regression tests", status,
                           f'{count["passed"]} passed, {count["failed"]} failed, {count["skipped"]} skipped. '
                           "Controlled regression tests, not a live UI/forecast-accuracy guarantee."
                           + (" Failed checks: " + "; ".join(failures[group]) if failures[group] else "")))
    for path in collection_errors:
        rows.append(result("Test collection", "Regression tests", "fail", path + " could not be collected."))
    from importlib import import_module
    for module, function in [
        ("vol_surface", "render_vol_surface_tab"), ("dislocation", "render_dislocation_tab"),
        ("strategy_builder", "compute_probability_table"), ("backtest_ui", "render_backtest_tab"),
        ("options_projection_ui", "render_options_projection"), ("price_scenario_ui", "render_price_scenario"),
    ]:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                loaded = import_module(module)
            exists = callable(getattr(loaded, function, None))
            rows.append(result(module, "Feature availability", "pass" if exists else "fail",
                               f"{function}: module imported and entry point is callable. "
                               "This is an availability check, not an end-to-end form test."))
        except Exception as exc:
            rows.append(result(module, "Feature availability", "fail", type(exc).__name__))
    for name in ["_check_bs_pricer", "_check_call_sleeve_engine", "_check_risk_metrics",
                 "_check_probability_engine", "_check_indicator_registry"]:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                probe = getattr(import_module("diagnostic"), name)()
            rows.append(result(name.removeprefix("_check_").replace("_", " "), "Engine execution",
                               probe["status"], probe.get("info", "Fixed-input calculation executed.")))
        except Exception as exc:
            rows.append(result(name, "Engine execution", "fail", type(exc).__name__))
    print("SOXL_DIAGNOSTICS=" + json.dumps(rows))


if __name__ == "__main__":
    main()
