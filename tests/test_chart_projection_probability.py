import json
import re
import subprocess
import unittest
from pathlib import Path


CHART_HTML = Path("components/chart_draw/index.html")


def _probability_source():
    html = CHART_HTML.read_text(encoding="utf-8")
    match = re.search(
        r"(function normalCdf\(value\).*?)(?=\nfunction lineTimestamp)",
        html,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("Projection probability functions were not found")
    return html, match.group(1)


def _run_probability_checks(chart_data, checks):
    _, source = _probability_source()
    program = f"""
var chartData = {json.dumps(chart_data)};
var hitProbabilityModel = null;
{source}
var results = [];
{checks}
console.log(JSON.stringify(results));
"""
    completed = subprocess.run(
        ["node", "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _representative_history(count=90):
    prices = []
    dates = []
    price = 40.0
    for index in range(count):
        # Alternating returns provide stable, nonzero volatility.
        price *= 1.012 if index % 2 == 0 else 0.994
        prices.append(price)
        dates.append(f"2025-{1 + index // 28:02d}-{1 + index % 28:02d}")
    return {"prices": prices, "dates": dates}


class ChartProjectionProbabilityTests(unittest.TestCase):
    def test_probabilities_are_finite_and_bounded(self):
        history = _representative_history()
        results = _run_probability_checks(
            history,
            """
var model = getHitProbabilityModel();
for (var years of [0.01, 0.25, 1, 5, 30, 100]) {
  for (var multiple of [0.01, 0.5, 1, 1.01, 2, 10, 1e100]) {
    results.push(estimateHitProbability(
      model.latestPrice * multiple,
      model.latestTimestamp + years * 365.25 * 86400000
    ));
  }
}
""",
        )
        for probability in results:
            self.assertIsInstance(probability, (int, float))
            self.assertGreaterEqual(probability, 0)
            self.assertLessEqual(probability, 1)

    def test_higher_targets_never_have_higher_probability(self):
        history = _representative_history()
        results = _run_probability_checks(
            history,
            """
var model = getHitProbabilityModel();
var deadline = model.latestTimestamp + 3 * 365.25 * 86400000;
results = [1.01, 1.1, 1.25, 1.5, 2, 3, 5].map(function(multiple) {
  return estimateHitProbability(model.latestPrice * multiple, deadline);
});
""",
        )
        for easier, harder in zip(results, results[1:]):
            self.assertGreaterEqual(easier + 1e-12, harder)

    def test_later_deadlines_never_have_lower_probability(self):
        history = _representative_history()
        results = _run_probability_checks(
            history,
            """
var model = getHitProbabilityModel();
var target = model.latestPrice * 1.75;
results = [1, 7, 30, 90, 365, 730, 1825].map(function(days) {
  return estimateHitProbability(
    target,
    model.latestTimestamp + days * 86400000
  );
});
""",
        )
        for earlier, later in zip(results, results[1:]):
            self.assertLessEqual(earlier, later + 1e-12)

    def test_missing_or_insufficient_history_is_unavailable(self):
        cases = [
            {},
            {"prices": [40.0] * 29, "dates": ["2025-01-01"] * 29},
            {"prices": [40.0] * 30, "dates": ["2025-01-01"] * 29},
        ]
        for chart_data in cases:
            with self.subTest(chart_data=chart_data):
                result = _run_probability_checks(
                    chart_data,
                    "results.push(formatHitProbability(80, Date.now()));",
                )
                self.assertEqual(result, ["Unavailable"])

    def test_probability_wording_remains_in_both_projection_hover_paths(self):
        html, _ = _probability_source()
        wording = "Probability of hitting this by or before this date:"
        # Plotly's projection trace and the custom pointer tooltip are separate paths.
        self.assertGreaterEqual(html.count(wording), 3)
        self.assertRegex(
            html,
            r"(?s)trendTooltip\.innerHTML\s*=.*?" + re.escape(wording),
        )
        self.assertRegex(
            html,
            r"(?s)forward\.hitProbabilities.*?hovertemplate:.*?"
            + re.escape(wording),
        )


if __name__ == "__main__":
    unittest.main()