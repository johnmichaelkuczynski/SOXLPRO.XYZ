"""Natural-language strategy assistant.

Talks to the user about a trading idea, produces a formal strategy JSON that
matches the Custom Strategy Builder schema, then lets the UI populate the
entry / exit / controls panels with one click.
"""
import os
import json
import re
from anthropic import Anthropic

from custom_strategy import (
    ALL_INDICATORS, INDICATORS_NEEDS_N, OPERATORS, DEFAULT_N, DEFAULT_N2,
    APP_SIGNALS_CATEGORICAL, APP_SIGNALS_NUMERIC_TWO_PARAM,
    NEEDS_OPTIONS_DATA,
)

_client = None


def get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
        base_url = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")
        if not api_key or not base_url:
            raise RuntimeError("Anthropic AI Integration is not configured.")
        _client = Anthropic(api_key=api_key, base_url=base_url)
    return _client


# ---------------------------------------------------------------------------
# System prompt describing the indicator catalog & required output schema
# ---------------------------------------------------------------------------
def _indicator_catalog_text():
    lines = ["INDICATOR CATALOG (use these EXACT names):"]
    cats = APP_SIGNALS_CATEGORICAL
    two_param = APP_SIGNALS_NUMERIC_TWO_PARAM

    for ind in ALL_INDICATORS:
        if ind in cats:
            lines.append(f"  • {ind!r}  → categorical, equals one of {cats[ind]}")
        elif ind in two_param:
            lines.append(f"  • {ind!r}  → numeric output, requires TWO params: n=M (% move) and n2=H (days)")
        elif ind in INDICATORS_NEEDS_N:
            d = DEFAULT_N.get(ind, 14)
            lines.append(f"  • {ind!r}  → numeric, requires param n (default {d})")
        else:
            lines.append(f"  • {ind!r}  → numeric, no parameter")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are an expert trading strategy architect for SOXL (Direxion Daily Semiconductor Bull 3X).

You help the user turn an INFORMAL, qualitative idea ("buy SOXL when vol is cheap and it's down a lot") into a FORMAL strategy that the app's backtest engine can execute.

The app's Custom Strategy Builder accepts a strategy as JSON with this schema:

{
  "entry": {
    "combinator": "AND" | "OR",
    "conditions": [
      {
        "lhs": {"kind": "indicator", "indicator": "<name>", "n": <int|float|null>, "n2": <int|null>},
        "op":  ">" | "<" | "=" | "crosses above" | "crosses below",
        "rhs": {"kind": "value", "value": <number>}
              OR {"kind": "category", "value": "<CATEGORY>"}
              OR {"kind": "indicator", "indicator": "<name>", "n": <int|null>}
      },
      ...
    ]
  },
  "exit":  { same shape — may be empty conditions if user only uses stop/tp/max_hold },
  "controls": {
    "max_hold": <int days, e.g. 60>,
    "stop_pct": <number, e.g. 15.0>,
    "tp_pct":   <number, e.g. 30.0>,
    "direction": "Long" | "Short" | "Both"
  }
}

CRITICAL RULES:
- For CATEGORICAL indicators (Vol Regime Label, Vol Surface Signal (Calls)/(Puts)), the operator MUST be "=" and the rhs MUST be {"kind":"category","value":"<one of the listed categories>"}.
- For 'Probability Engine P(M%, Hd)', set "n" = M (percent move, e.g. 10.0) and "n2" = H (days horizon, e.g. 30). The output is a probability between 0 and 1, so the rhs value should be like 0.65.
- For 'Period Analysis Percentile(N)', the output is a percentile 0–100.
- For 'SOXL z-score vs QQQ(N)', the output is roughly in [-3, +3].
- The "Days held in position" indicator is only meaningful in the EXIT panel.
- If the user uses Vol Surface signals, remind them the backtest will be auto-restricted to 2022-present.

""" + _indicator_catalog_text() + """

CONVERSATION FLOW:
1. Read the user's qualitative description.
2. If the idea is clear enough, draft the formal strategy and show it.
3. If something is ambiguous (thresholds, exit logic, position sizing parameters), ask ONE focused clarifying question — don't interrogate.
4. When you produce a strategy draft, ALWAYS:
   a. First write a short plain-English summary of what the strategy does ("Enters when X, exits when Y, with stop Z and target W")
   b. Then output the JSON wrapped EXACTLY between these markers:

===STRATEGY_JSON_START===
{ ... valid JSON ... }
===STRATEGY_JSON_END===

5. After showing a draft, invite the user to refine: "Want to tweak anything? Adjust thresholds, swap signals, change the stop?"

JSON RULES:
- Plain ASCII only, double quotes, no trailing commas, no comments.
- Every "lhs" indicator field must be an EXACT name from the catalog above.
- Numeric fields should be unquoted numbers, not strings.
- Always include "controls" with sensible defaults if user didn't specify (max_hold=60, stop_pct=15.0, tp_pct=30.0, direction="Long").

EXAMPLES of valid strategies:

Example 1 — "Buy when calls vol surface says BUY, sell when SELL":
===STRATEGY_JSON_START===
{
  "entry": {"combinator": "AND", "conditions": [
    {"lhs": {"kind":"indicator","indicator":"Vol Surface Signal (Calls)","n":null,"n2":null},
     "op":"=", "rhs":{"kind":"category","value":"BUY"}}
  ]},
  "exit": {"combinator": "AND", "conditions": [
    {"lhs": {"kind":"indicator","indicator":"Vol Surface Signal (Calls)","n":null,"n2":null},
     "op":"=", "rhs":{"kind":"category","value":"SELL"}}
  ]},
  "controls": {"max_hold": 60, "stop_pct": 15.0, "tp_pct": 30.0, "direction": "Long"}
}
===STRATEGY_JSON_END===

Example 2 — "Buy when vol regime is cheap AND SOXL is dislocated below QQQ by >2 sigma":
===STRATEGY_JSON_START===
{
  "entry": {"combinator": "AND", "conditions": [
    {"lhs":{"kind":"indicator","indicator":"Vol Regime Label","n":null,"n2":null},
     "op":"=", "rhs":{"kind":"category","value":"CHEAP"}},
    {"lhs":{"kind":"indicator","indicator":"SOXL z-score vs QQQ(N)","n":60,"n2":null},
     "op":"<", "rhs":{"kind":"value","value":-2.0}}
  ]},
  "exit": {"combinator": "AND", "conditions": [
    {"lhs":{"kind":"indicator","indicator":"SOXL z-score vs QQQ(N)","n":60,"n2":null},
     "op":">", "rhs":{"kind":"value","value":0.0}}
  ]},
  "controls": {"max_hold": 90, "stop_pct": 20.0, "tp_pct": 40.0, "direction": "Long"}
}
===STRATEGY_JSON_END===

Be conversational and concise. Don't lecture. Don't restate the user's words back at them. Just help them build a working strategy.
"""


def chat_refine(messages):
    """messages: list of {role: 'user'|'assistant', content: str}. Returns assistant text."""
    resp = get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_VALID_OPS = set(OPERATORS)
_VALID_INDICATORS = set(ALL_INDICATORS)


def extract_strategy_json(text):
    """Pull the JSON block out of the assistant message, if present."""
    if "===STRATEGY_JSON_START===" not in text or "===STRATEGY_JSON_END===" not in text:
        return None
    raw = text.split("===STRATEGY_JSON_START===", 1)[1].split("===STRATEGY_JSON_END===", 1)[0].strip()
    # Tolerate fenced code blocks
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _validate_side(side):
    if not isinstance(side, dict):
        return False
    kind = side.get("kind")
    if kind == "value":
        return isinstance(side.get("value"), (int, float))
    if kind == "category":
        return isinstance(side.get("value"), str)
    if kind == "indicator":
        return side.get("indicator") in _VALID_INDICATORS
    return False


def _normalize_side(side):
    if not isinstance(side, dict):
        return {"kind": "value", "value": 0.0, "indicator": None, "n": None, "n2": None}
    out = dict(side)
    out.setdefault("indicator", None)
    out.setdefault("n", None)
    out.setdefault("n2", None)
    out.setdefault("value", None)
    if out["kind"] == "indicator":
        ind = out["indicator"]
        if ind in INDICATORS_NEEDS_N and out["n"] is None:
            out["n"] = DEFAULT_N.get(ind, 14)
        if ind in APP_SIGNALS_NUMERIC_TWO_PARAM and out["n2"] is None:
            out["n2"] = DEFAULT_N2.get(ind, 30)
    return out


def _normalize_panel(panel):
    if not isinstance(panel, dict):
        return {"combinator": "AND", "conditions": []}
    out = {
        "combinator": panel.get("combinator", "AND") if panel.get("combinator") in ("AND", "OR") else "AND",
        "conditions": [],
    }
    for c in panel.get("conditions") or []:
        if not isinstance(c, dict):
            continue
        op = c.get("op")
        if op not in _VALID_OPS:
            continue
        if not _validate_side(c.get("lhs")) or not _validate_side(c.get("rhs")):
            continue
        out["conditions"].append({
            "lhs": _normalize_side(c["lhs"]),
            "op": op,
            "rhs": _normalize_side(c["rhs"]),
        })
    return out


def normalize_strategy(data):
    """Validate + fill defaults so the result drops directly into session_state."""
    if not isinstance(data, dict):
        return None
    entry = _normalize_panel(data.get("entry") or {})
    if not entry["conditions"]:
        return None  # an entry rule is required
    exit_p = _normalize_panel(data.get("exit") or {"combinator": "AND", "conditions": []})
    ctrls = data.get("controls") or {}
    controls = {
        "max_hold": int(ctrls.get("max_hold", 60) or 60),
        "stop_pct": float(ctrls.get("stop_pct", 15.0) or 15.0),
        "tp_pct": float(ctrls.get("tp_pct", 30.0) or 30.0),
        "direction": ctrls.get("direction", "Long") if ctrls.get("direction") in ("Long", "Short", "Both") else "Long",
    }
    return {"entry": entry, "exit": exit_p, "controls": controls}


def uses_options_signals(cfg):
    for panel_key in ("entry", "exit"):
        for c in (cfg.get(panel_key, {}).get("conditions") or []):
            for side in (c.get("lhs", {}), c.get("rhs", {})):
                if side.get("kind") == "indicator" and side.get("indicator") in NEEDS_OPTIONS_DATA:
                    return True
    return False
