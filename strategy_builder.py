import os
import json
import html as html_module
import numpy as np
from datetime import datetime
from anthropic import Anthropic

AI_INTEGRATIONS_ANTHROPIC_API_KEY = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
AI_INTEGRATIONS_ANTHROPIC_BASE_URL = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")

client = None


def get_client():
    global client
    if client is None:
        api_key = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY")
        base_url = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL")
        if not api_key or not base_url:
            raise RuntimeError("Anthropic AI Integration is not configured. Please set up the integration.")
        client = Anthropic(api_key=api_key, base_url=base_url)
    return client


def esc(text):
    if text is None:
        return ""
    return html_module.escape(str(text))


def compute_probability_table(close_prices, horizons_days, magnitudes):
    results = []
    for horizon in horizons_days:
        for mag in magnitudes:
            total = len(close_prices) - horizon
            if total <= 0:
                continue
            up_count = 0
            down_count = 0
            for i in range(total):
                pct = (close_prices[i + horizon] - close_prices[i]) / close_prices[i] * 100
                if pct >= mag:
                    up_count += 1
                if pct <= -mag:
                    down_count += 1
            results.append({
                "horizon_days": horizon,
                "magnitude_pct": mag,
                "up_prob": round(up_count / total * 100, 1),
                "down_prob": round(down_count / total * 100, 1),
                "total_periods": total
            })
    return results


def compute_stats_summary(close_prices):
    current = close_prices[-1]
    high = np.max(close_prices)
    low = np.min(close_prices)
    pct_from_high = (current - high) / high * 100
    pct_from_low = (current - low) / low * 100

    returns_1w = (close_prices[-1] - close_prices[-5]) / close_prices[-5] * 100 if len(close_prices) > 5 else 0
    returns_1m = (close_prices[-1] - close_prices[-21]) / close_prices[-21] * 100 if len(close_prices) > 21 else 0
    returns_3m = (close_prices[-1] - close_prices[-63]) / close_prices[-63] * 100 if len(close_prices) > 63 else 0
    returns_6m = (close_prices[-1] - close_prices[-126]) / close_prices[-126] * 100 if len(close_prices) > 126 else 0
    returns_1y = (close_prices[-1] - close_prices[-252]) / close_prices[-252] * 100 if len(close_prices) > 252 else 0

    max_drawdowns = []
    peak = close_prices[0]
    for p in close_prices:
        if p > peak:
            peak = p
        dd = (p - peak) / peak * 100
        max_drawdowns.append(dd)

    return {
        "current_price": round(current, 2),
        "all_time_high": round(high, 2),
        "all_time_low": round(low, 2),
        "pct_from_ath": round(pct_from_high, 1),
        "pct_from_atl": round(pct_from_low, 1),
        "return_1w": round(returns_1w, 1),
        "return_1m": round(returns_1m, 1),
        "return_3m": round(returns_3m, 1),
        "return_6m": round(returns_6m, 1),
        "return_1y": round(returns_1y, 1),
        "max_drawdown": round(min(max_drawdowns), 1),
        "date": datetime.now().strftime("%B %Y")
    }


def generate_strategy(messages, close_prices):
    stats = compute_stats_summary(close_prices)

    horizons = [5, 21, 63, 126, 252]
    magnitudes = [10, 15, 20, 25, 30, 40, 50]
    prob_table = compute_probability_table(close_prices, horizons, magnitudes)

    system_prompt = f"""You are an expert SOXL (Direxion Daily Semiconductor Bull 3X Shares) strategy architect. You help users build personalized entry/exit strategies based on historical statistical analysis.

CURRENT MARKET DATA (as of {stats['date']}):
- Current Price: ${stats['current_price']}
- All-Time High: ${stats['all_time_high']} ({stats['pct_from_ath']}% from ATH)
- All-Time Low: ${stats['all_time_low']} ({stats['pct_from_atl']}% from ATL)
- Returns: 1W={stats['return_1w']}%, 1M={stats['return_1m']}%, 3M={stats['return_3m']}%, 6M={stats['return_6m']}%, 1Y={stats['return_1y']}%
- Max Historical Drawdown: {stats['max_drawdown']}%

HISTORICAL PROBABILITY DATA:
{json.dumps(prob_table, indent=2)}

YOUR ROLE:
1. Have a conversation with the user to understand their situation: portfolio size, cash available, risk tolerance, investment timeline, goals
2. Ask clarifying questions if needed (one or two at a time, don't overwhelm)
3. When you have enough info, generate a complete strategy

WHEN GENERATING THE FINAL STRATEGY, you MUST output it in this exact format between the markers:

===STRATEGY_START===
{{
  "title": "SOXL ENTRY STRATEGY",
  "subtitle": "Strategy type description",
  "date": "{stats['date']}",
  "current_price": {stats['current_price']},
  "portfolio_total": 0,
  "cash_pct": 0,
  "summary": "Brief strategy description",
  "tranches": [
    {{
      "trigger": "SOXL <= $XX",
      "action": "BUY - Tranche N",
      "deploy_pct": "X%",
      "deploy_amount": "~$XXK",
      "status": "LIVE NOW or WATCH or STANDBY",
      "notes": "Reason for this level"
    }}
  ],
  "reserve": {{
    "amount": "~$XXK",
    "pct": "XX%",
    "label": "NEVER DEPLOY",
    "status": "PERMANENT FLOOR",
    "notes": "Survival capital description"
  }},
  "rules": [
    {{
      "name": "RULE NAME",
      "detail": "Rule description"
    }}
  ],
  "probabilities_used": [
    {{
      "scenario": "Description",
      "probability": "XX%",
      "source": "Based on X-day horizon, Y% magnitude"
    }}
  ],
  "disclaimer": "Personally constructed strategy document. Not financial advice. Leveraged ETFs can go to zero."
}}
===STRATEGY_END===

CRITICAL JSON RULES:
- Use only plain ASCII characters in strings. No special unicode characters.
- All string values must use double quotes
- No trailing commas
- Numbers should not be quoted except when part of a display string
- Ensure valid JSON that can be parsed by json.loads()

The strategy should:
- Use the actual probability data provided to justify price levels and allocations
- Include 3-6 tranches with specific trigger prices
- Always keep a cash reserve (permanent floor)
- Include operating rules (independence, skip rule, zero scenario, etc.)
- Reference specific probabilities when explaining why each level was chosen
- Be tailored to the user's specific situation

If the user hasn't provided enough information yet, DO NOT generate the strategy. Instead, ask questions. Be conversational and helpful.

IMPORTANT: Outside of the strategy JSON, write in plain conversational text. Don't use markdown headers or excessive formatting in your conversation."""

    response = get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=system_prompt,
        messages=messages
    )

    return response.content[0].text


def parse_strategy_json(text):
    if "===STRATEGY_START===" not in text or "===STRATEGY_END===" not in text:
        return None
    json_str = text.split("===STRATEGY_START===")[1].split("===STRATEGY_END===")[0].strip()
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    if not isinstance(data.get("tranches"), list) or len(data.get("tranches", [])) == 0:
        return None
    if not isinstance(data.get("rules"), list) or len(data.get("rules", [])) == 0:
        return None

    for t in data["tranches"]:
        t.setdefault("trigger", "")
        t.setdefault("action", "")
        t.setdefault("deploy_pct", "")
        t.setdefault("deploy_amount", "")
        t.setdefault("status", "WATCH")
        t.setdefault("notes", "")

    for r in data.get("rules", []):
        r.setdefault("name", "")
        r.setdefault("detail", "")

    for p in data.get("probabilities_used", []):
        p.setdefault("scenario", "")
        p.setdefault("probability", "")
        p.setdefault("source", "")

    data.setdefault("title", "SOXL ENTRY STRATEGY")
    data.setdefault("subtitle", "")
    data.setdefault("date", "")
    data.setdefault("current_price", 0)
    data.setdefault("portfolio_total", 0)
    data.setdefault("cash_pct", 0)
    data.setdefault("summary", "")
    data.setdefault("reserve", {})
    data.setdefault("probabilities_used", [])
    data.setdefault("disclaimer", "Not financial advice. Leveraged ETFs can go to zero.")

    reserve = data["reserve"]
    reserve.setdefault("amount", "")
    reserve.setdefault("pct", "")
    reserve.setdefault("label", "NEVER DEPLOY")
    reserve.setdefault("status", "PERMANENT FLOOR")
    reserve.setdefault("notes", "")

    return data


def render_strategy_html(strategy):
    tranches_rows = ""
    for t in strategy.get("tranches", []):
        status = t.get("status", "WATCH")
        if "LIVE" in status.upper():
            status_class = "status-live"
            status_icon = "&#10003; "
        elif "WATCH" in status.upper():
            status_class = "status-watch"
            status_icon = ""
        else:
            status_class = "status-standby"
            status_icon = ""

        tranches_rows += f"""<tr>
            <td class="trigger-cell">{esc(t.get('trigger', ''))}</td>
            <td class="action-cell">{esc(t.get('action', ''))}</td>
            <td class="deploy-cell">{esc(t.get('deploy_pct', ''))} ({esc(t.get('deploy_amount', ''))})</td>
            <td class="status-cell"><span class="{status_class}">{status_icon}{esc(status)}</span></td>
            <td class="notes-cell">{esc(t.get('notes', ''))}</td>
        </tr>"""

    reserve = strategy.get("reserve", {})
    if reserve:
        tranches_rows += f"""<tr class="reserve-row">
            <td class="trigger-cell">{esc(reserve.get('amount', ''))} ({esc(reserve.get('pct', ''))})</td>
            <td class="action-cell">{esc(reserve.get('label', 'NEVER DEPLOY'))}</td>
            <td class="deploy-cell">{esc(reserve.get('status', 'PERMANENT FLOOR'))}</td>
            <td class="status-cell"><span class="status-untouchable">UNTOUCHABLE</span></td>
            <td class="notes-cell">{esc(reserve.get('notes', ''))}</td>
        </tr>"""

    rules_rows = ""
    for r in strategy.get("rules", []):
        rules_rows += f"""<tr>
            <td class="rule-name">{esc(r.get('name', ''))}</td>
            <td class="rule-detail">{esc(r.get('detail', ''))}</td>
        </tr>"""

    prob_rows = ""
    for p in strategy.get("probabilities_used", []):
        prob_rows += f"""<tr>
            <td>{esc(p.get('scenario', ''))}</td>
            <td><strong>{esc(p.get('probability', ''))}</strong></td>
            <td class="prob-source">{esc(p.get('source', ''))}</td>
        </tr>"""

    current_price = strategy.get("current_price", 0)
    portfolio = strategy.get("portfolio_total", 0)
    cash_pct = strategy.get("cash_pct", 0)

    html = f"""
    <div class="strategy-doc">
        <div class="strategy-header">
            <h1>{esc(strategy.get('title', 'SOXL ENTRY STRATEGY'))}</h1>
            <div class="header-meta">
                {esc(strategy.get('subtitle', ''))} &bull; {esc(strategy.get('date', ''))} &bull;
                <strong>Current Price: ~${esc(str(current_price))}</strong> |
                Total Portfolio: ~${portfolio:,.0f} |
                Cash: ~{esc(str(cash_pct))}%
            </div>
            <div class="header-summary">{esc(strategy.get('summary', ''))}</div>
        </div>

        <div class="section">
            <h2>PRICE-TRIGGERED ENTRY LADDER</h2>
            <table class="ladder-table">
                <thead>
                    <tr>
                        <th>TRIGGER PRICE</th>
                        <th>ACTION</th>
                        <th>DEPLOY</th>
                        <th>STATUS</th>
                        <th>NOTES</th>
                    </tr>
                </thead>
                <tbody>
                    {tranches_rows}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>OPERATING RULES</h2>
            <table class="rules-table">
                <thead>
                    <tr>
                        <th>RULE</th>
                        <th>DETAIL</th>
                    </tr>
                </thead>
                <tbody>
                    {rules_rows}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>STATISTICAL BASIS</h2>
            <table class="prob-table">
                <thead>
                    <tr>
                        <th>SCENARIO</th>
                        <th>PROBABILITY</th>
                        <th>DATA SOURCE</th>
                    </tr>
                </thead>
                <tbody>
                    {prob_rows}
                </tbody>
            </table>
        </div>

        <div class="disclaimer">
            &#9888; {esc(strategy.get('disclaimer', 'Not financial advice. Leveraged ETFs can go to zero.'))}
        </div>
    </div>
    """
    return html


STRATEGY_CSS = """
<style>
.strategy-doc {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    background: #fff;
    border: 2px solid #1a2332;
    border-radius: 4px;
    overflow: hidden;
}

.strategy-header {
    background: #1a2332;
    color: white;
    padding: 24px 28px 18px;
}

.strategy-header h1 {
    margin: 0 0 8px 0;
    font-size: 26px;
    font-weight: 800;
    letter-spacing: 1px;
}

.header-meta {
    font-size: 13px;
    color: #b0bec5;
    margin-bottom: 8px;
}

.header-meta strong {
    color: #fff;
}

.header-summary {
    font-size: 13px;
    color: #90a4ae;
    font-style: italic;
}

.section {
    padding: 18px 28px;
}

.section h2 {
    font-size: 15px;
    font-weight: 700;
    color: #1a2332;
    margin: 0 0 12px 0;
    padding-bottom: 6px;
    border-bottom: 2px solid #1a2332;
    letter-spacing: 0.5px;
}

.ladder-table, .rules-table, .prob-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}

.ladder-table th, .rules-table th, .prob-table th {
    background: #1a2332;
    color: white;
    padding: 10px 12px;
    text-align: left;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

.ladder-table td, .rules-table td, .prob-table td {
    padding: 10px 12px;
    border-bottom: 1px solid #e0e0e0;
    vertical-align: top;
}

.ladder-table tr:nth-child(even), .prob-table tr:nth-child(even) {
    background: #f8f9fa;
}

.trigger-cell {
    font-weight: 700;
    color: #c62828;
    white-space: nowrap;
}

.action-cell {
    font-weight: 600;
    color: #1a2332;
}

.deploy-cell {
    font-weight: 600;
    white-space: nowrap;
}

.status-live {
    background: #e8f5e9;
    color: #2e7d32;
    padding: 3px 10px;
    border-radius: 3px;
    font-weight: 700;
    font-size: 11px;
    display: inline-block;
}

.status-watch {
    background: #fff3e0;
    color: #e65100;
    padding: 3px 10px;
    border-radius: 3px;
    font-weight: 700;
    font-size: 11px;
    display: inline-block;
}

.status-standby {
    background: #f3e5f5;
    color: #6a1b9a;
    padding: 3px 10px;
    border-radius: 3px;
    font-weight: 700;
    font-size: 11px;
    display: inline-block;
}

.status-untouchable {
    background: #fce4ec;
    color: #b71c1c;
    padding: 3px 10px;
    border-radius: 3px;
    font-weight: 700;
    font-size: 11px;
    display: inline-block;
}

.reserve-row {
    background: #fafafa !important;
    border-top: 2px solid #ccc;
}

.reserve-row td {
    color: #666;
}

.rule-name {
    font-weight: 700;
    color: #1a2332;
    white-space: nowrap;
    width: 160px;
}

.rule-detail {
    color: #444;
    line-height: 1.5;
}

.prob-source {
    color: #666;
    font-size: 12px;
    font-style: italic;
}

.disclaimer {
    margin: 0;
    padding: 14px 28px;
    background: #fff8e1;
    border-top: 1px solid #ffe082;
    font-size: 12px;
    color: #795548;
}
</style>
"""
