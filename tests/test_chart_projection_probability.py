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

    def test_only_one_projection_hover_path_retains_probability(self):
        html, _ = _probability_source()
        wording = "Probability of hitting this by or before this date:"
        self.assertEqual(html.count(wording), 1)
        self.assertRegex(
            html,
            r"(?s)trendTooltip\.innerHTML\s*=.*?" + re.escape(wording),
        )
        trend_traces = html.split("var segment = trendPoints(", 1)[1].split("var shapes = []", 1)[0]
        self.assertEqual(trend_traces.count("hoverinfo: 'skip'"), 3)
        self.assertNotIn("hovertemplate:", trend_traces)

    def test_pointer_switches_readout_to_bottom_line_and_clears_in_gaps(self):
        html = CHART_HTML.read_text()
        source = "function inspectTrendLine(event)" + html.split(
            "function inspectTrendLine(event)", 1)[1].split(
            "chartContainer.addEventListener('pointermove'", 1)[0]
        program = """
var active = false;
var chartContainer = {classList: {add:()=>active=true, remove:()=>active=false}};
var trendTooltip = {style:{},offsetWidth:270,innerHTML:''};
var currentMode='pan', scaleMode='linear', hoveredLineIndex=-1, hoveredLineDistance=Infinity;
var chartScroll={scrollLeft:0,clientWidth:1000};
var chartDiv={getBoundingClientRect:()=>({left:0,top:0}),
  _fullLayout:{_size:{l:0,t:0,w:1000,h:600},xaxis:{range:[0,1000]},yaxis:{range:[0,100]}}};
var lines=[{y1:80,y2:80},{y1:50,y2:50},{y1:20,y2:20}];
function lineTimestamp(line,point){return point===1?0:1000;}
function getFutureEndMs(){return 2000;}
function formatHitProbability(){return '75%';}
function estimateHitProbability(){return .75;}
function formatProjectedDate(){return 'Jan 1, 2030';}
function getHitProbabilityModel(){return null;}
""" + source + """
var results=[];
for (var y of [300,480,390]) {
 inspectTrendLine({clientX:700,clientY:y});
 results.push({active:active,display:trendTooltip.style.display,text:trendTooltip.innerHTML,index:hoveredLineIndex});
}
console.log(JSON.stringify(results));
"""
        results = json.loads(subprocess.check_output(["node", "-e", program], text=True))
        self.assertIn("Trend line 2 projection", results[0]["text"])
        self.assertIn("Trend line 3 projection", results[1]["text"])
        self.assertIn("2030", results[1]["text"])
        self.assertTrue(results[1]["active"])
        self.assertFalse(results[2]["active"])
        self.assertEqual(results[2]["display"], "none")


if __name__ == "__main__":
    unittest.main()