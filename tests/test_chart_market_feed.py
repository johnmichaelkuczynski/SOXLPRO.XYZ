import json
from pathlib import Path
import subprocess
import unittest

import pandas as pd

from chart_market_feed import make_market_payload


class ChartMarketFeedTests(unittest.TestCase):
    def test_all_sessions_preserve_intraday_timestamps_and_exclude_uncovered_hours(self):
        bars = pd.DataFrame(
            {"Close": [10, 11, 12, 13, 14]},
            index=pd.to_datetime(["2026-09-10 04:00", "2026-09-10 09:30",
                                  "2026-09-10 16:00", "2026-09-10 20:00",
                                  "2026-09-10 23:00"]).tz_localize("America/New_York"),
        )
        periods = pd.DataFrame([{
            key: pd.Timestamp("2026-09-10 " + time, tz="America/New_York")
            for key, time in [("pre_start", "04:00"), ("start", "09:30"),
                              ("end", "16:00"), ("post_end", "20:00")]
        }])
        payload = make_market_payload(bars, periods, "checked")
        self.assertEqual([p["session"] for p in payload["points"]],
                         ["Pre-market", "Regular session", "After-hours"])
        self.assertEqual(payload["points"][1]["date"], "2026-09-10 09:30:00")
        self.assertEqual(payload["points"][1]["time"], "2026-09-10T09:30:00-04:00")

    def test_trace_merges_history_without_polluting_daily_calibration(self):
        html = Path("components/chart_draw/index.html").read_text()
        source = html.split("function soxlMarketTrace()", 1)[1].split("function refreshMarketTrace()", 1)[0]
        program = """
var chartData = {dates:['2026-09-08','2026-09-09','2026-09-10'], prices:[9,10,11]};
var marketFeed = {points:[
{date:'2026-09-10 04:00:00',time:'2026-09-10T04:00:00-04:00',price:12,session:'Pre-market'},
{date:'2026-09-10 09:30:00',time:'2026-09-10T09:30:00-04:00',price:13,session:'Regular session'}
]};
function soxlMarketTrace()""" + source + """
console.log(JSON.stringify({trace:soxlMarketTrace(),daily:chartData}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", program], text=True))
        self.assertEqual(result["daily"]["prices"], [9, 10, 11])
        self.assertEqual(result["trace"]["y"], [9, 10, 12, None, 13])
        self.assertEqual(result["trace"]["customdata"][-1][0], "Regular session")

    def test_background_update_only_changes_price_trace_not_layout_or_lines(self):
        html = Path("components/chart_draw/index.html").read_text()
        source = html.split("function refreshMarketTrace()", 1)[1].split(
            "chartDiv.addEventListener('pointerdown'", 1)[0]
        program = """
var calls=[];
var chartData={}, chartDiv={data:[{}]}, chartGestureActive=false, pendingMarketUpdate=false;
var Plotly={restyle:function(...args){calls.push(args);}};
function soxlMarketTrace(){return {x:['date'],y:[42],customdata:[['Pre-market','date']]};}
function refreshMarketTrace()""" + source + """
refreshMarketTrace();
chartGestureActive=true;
refreshMarketTrace();
console.log(JSON.stringify({calls:calls,pending:pendingMarketUpdate}));
"""
        result = json.loads(subprocess.check_output(["node", "-e", program], text=True))
        self.assertEqual(len(result["calls"]), 1)
        self.assertEqual(result["calls"][0][2], [0])
        self.assertEqual(set(result["calls"][0][1]), {"x", "y", "customdata"})
        self.assertTrue(result["pending"])

    def test_no_separate_overnight_panel_in_app(self):
        source = Path("app.py").read_text()
        self.assertNotIn("render_overnight_market", source)
        self.assertIn("market_feed=fetch_chart_market_feed()", source)
        self.assertIn("update_chart_market_feed()", source)


if __name__ == "__main__":
    unittest.main()