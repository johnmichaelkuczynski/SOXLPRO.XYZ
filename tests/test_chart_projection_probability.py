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
        self.assertEqual(html.count(wording), 4)
        self.assertIn("body.projection-readout-active .hoverlayer { visibility: hidden; }", html)
        self.assertIn("document.body.classList.remove('projection-readout-active')", html)
        trend_traces = html.split("var segment = trendPoints(", 1)[1].split("var shapes = []", 1)[0]
        self.assertNotIn("hoverinfo: 'skip'", trend_traces)
        self.assertEqual(trend_traces.count("hovertemplate:"), 3)

    def test_continuous_projection_and_explicit_lower_line_selection(self):
        html = CHART_HTML.read_text()
        source = "function inspectTrendLine(event)" + html.split(
            "function inspectTrendLine(event)", 1)[1].split(
            "chartContainer.addEventListener('pointermove'", 1)[0]
        program = """
var active = false;
var COLORS = ['#888','#E53935','#43A047'];
var chartContainer = {classList: {add:()=>active=true, remove:()=>active=false}};
var trendTooltip = {style:{},offsetWidth:270,offsetHeight:150,innerHTML:'',
 replaceChildren:function(){this.innerHTML='';},appendChild:function(el){this.innerHTML+=el.textContent;}};
var picker={value:''};
var document={body:chartContainer,getElementById:()=>picker,createElement:()=>({textContent:''})};
var window={innerWidth:1000,innerHeight:900,
 frameElement:{getBoundingClientRect:()=>({left:0,top:100})},
 parent:{innerWidth:1000,innerHeight:500}};
var chartData={dates:['1970-01-01']};
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
picker.value='2';
inspectTrendLine({clientX:700,clientY:120});
results.push({active:active,display:trendTooltip.style.display,text:trendTooltip.innerHTML,index:hoveredLineIndex,color:trendTooltip.style.backgroundColor});
inspectTrendLine({clientX:700,clientY:380});
results.push({active:active,display:trendTooltip.style.display,top:trendTooltip.style.top,index:hoveredLineIndex});
console.log(JSON.stringify(results));
"""
        results = json.loads(subprocess.check_output(["node", "-e", program], text=True))
        self.assertEqual(results[0]["index"], 1)
        self.assertEqual(results[1]["index"], 2)
        self.assertEqual(results[3]["index"], 2)
        self.assertEqual(results[3]["color"], "#43A047")
        self.assertIn('Trend line 3', results[3]["text"])
        self.assertIn('2030', results[3]["text"])
        for result in results:
            self.assertTrue(result["active"])
            self.assertEqual(result["display"], "block")
        self.assertLessEqual(float(results[4]["top"].removesuffix("px")) + 150, 392)


if __name__ == "__main__":
    unittest.main()