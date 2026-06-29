"""Synthetic-user diagnostic.

Uses OpenAI (Replit AI Integration) to invent a realistic SOXL investor persona
and a question, then drives the REAL strategy-builder pipeline (Anthropic) with
that persona to confirm the app produces a coherent, parseable strategy
end-to-end. Sessions are persisted to Neon.
"""

from __future__ import annotations

import json
import time
from typing import Optional

import pandas as pd
import streamlit as st
import yfinance as yf

import db
from openai_client import get_openai_client, openai_available
from strategy_builder import generate_strategy, parse_strategy_json

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
_PERSONA_MODEL = "gpt-5"


def _soxl_close() -> pd.Series:
    df = yf.Ticker("SOXL").history(period="max", auto_adjust=True)
    df.index = df.index.tz_localize(None)
    return df["Close"]


def generate_persona() -> dict:
    """Ask OpenAI for a realistic investor persona + an opening message."""
    client = get_openai_client()
    prompt = (
        "Invent a realistic retail investor who is considering buying SOXL "
        "(a 3x leveraged semiconductor ETF). Return strict JSON with keys: "
        "persona (1-2 sentence description including portfolio size, cash on "
        "hand, risk tolerance, and timeline), and message (a natural first "
        "message THIS investor would type to an AI strategy builder, in first "
        "person, including all the concrete numbers from the persona so the "
        "builder has enough to produce a full strategy). Output JSON only."
    )
    try:
        resp = client.chat.completions.create(
            model=_PERSONA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_completion_tokens=8192,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {"persona": "", "message": "", "error": f"{type(e).__name__}: {e}"}
    return {
        "persona": str(data.get("persona", "")).strip(),
        "message": str(data.get("message", "")).strip(),
    }


def run_synthetic_session(user_email: Optional[str] = None) -> dict:
    """Run one full synthetic session and persist it. Returns a result dict."""
    t0 = time.perf_counter()
    if not openai_available():
        return {"ok": False, "error": "OpenAI integration not configured."}

    persona = generate_persona()
    if persona.get("error"):
        return {"ok": False, "error": f"Persona generation failed: {persona['error']}"}
    if not persona["message"]:
        return {"ok": False, "error": "Persona generation returned no message."}

    try:
        close = _soxl_close()
        # Drive the real strategy builder. Append a nudge so it commits to output.
        messages = [
            {"role": "user", "content": persona["message"]},
            {"role": "assistant", "content": "Understood. Generating your strategy now."},
            {"role": "user", "content": "Yes, please generate the full strategy now."},
        ]
        response_text = generate_strategy(messages, close)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "persona": persona["persona"],
                "prompt": persona["message"],
                "error": f"Strategy builder failed: {type(e).__name__}: {e}"}
    parsed = parse_strategy_json(response_text)
    has_strategy = parsed is not None
    n_tranches = len(parsed.get("tranches", [])) if isinstance(parsed, dict) else 0

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    outcome = {
        "produced_strategy": has_strategy,
        "tranches": n_tranches,
        "response_chars": len(response_text),
        "elapsed_ms": elapsed_ms,
    }
    transcript = messages + [{"role": "assistant", "content": response_text}]

    row_id = db.save_synthetic_session(
        persona=persona["persona"],
        prompt=persona["message"],
        response=response_text,
        transcript=transcript,
        outcome=outcome,
        user_email=user_email,
    )

    return {
        "ok": has_strategy,
        "persona": persona["persona"],
        "prompt": persona["message"],
        "response": response_text,
        "parsed": parsed,
        "outcome": outcome,
        "row_id": row_id,
    }


def render_synthetic_user_tab(user_email: Optional[str] = None) -> None:
    st.markdown("### 🧪 Synthetic User")
    st.markdown(
        "OpenAI invents a realistic investor persona and message, then drives the "
        "**real** Strategy Builder (Anthropic) end-to-end. A pass means the app "
        "produced a complete, parseable strategy for a user it had never seen."
    )
    if not openai_available():
        st.error("OpenAI integration is not configured.")
        return

    if st.button("Run synthetic session", type="primary"):
        with st.spinner("Generating persona, running the strategy builder…"):
            st.session_state["synthetic_result"] = run_synthetic_session(user_email)

    result = st.session_state.get("synthetic_result")
    if not result:
        st.info("No synthetic session run yet. Click **Run synthetic session**.")
        return

    if not result.get("ok"):
        st.error(f"Session did not produce a valid strategy. {result.get('error', '')}")
    else:
        oc = result["outcome"]
        st.success(
            f"Produced a complete strategy with {oc['tranches']} tranche(s) "
            f"in {oc['elapsed_ms']} ms."
            + (f"  ·  saved as row #{result['row_id']}" if result.get("row_id") else "")
        )

    if result.get("persona"):
        st.markdown("**Persona**")
        st.caption(result["persona"])
    if result.get("prompt"):
        with st.expander("Synthetic user message"):
            st.write(result["prompt"])
    if result.get("response"):
        with st.expander("Strategy builder response"):
            st.write(result["response"])
    if result.get("parsed"):
        with st.expander("Parsed strategy JSON", expanded=False):
            st.json(result["parsed"])

    # store last response so the QC tab can grade it
    if result.get("response"):
        st.session_state["last_ai_answer"] = {
            "subject": "Synthetic-user strategy",
            "text": result["response"],
        }
