"""OpenAI-based quality-control diagnostic.

Verifies the legitimacy of an AI-generated answer two ways:
  1. OpenAI (gpt-5) grades the answer against a rubric for factual soundness,
     internal consistency, and whether it actually answers the request.
  2. GPTZero scores how likely the text is machine-generated (an authenticity /
     provenance signal).
Results are combined into a single legitimacy verdict and persisted to Neon.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests
import streamlit as st

import db
from openai_client import get_openai_client, openai_available

# the newest OpenAI model is "gpt-5" which was released August 7, 2025.
# do not change this unless explicitly requested by the user
_QC_MODEL = "gpt-5"

GPTZERO_API_KEY = os.environ.get("GPTZERO_API_KEY", "")
_GPTZERO_URL = "https://api.gptzero.me/v2/predict/text"


def gptzero_available() -> bool:
    return bool(GPTZERO_API_KEY)


def check_gptzero(text: str) -> dict:
    """Return GPTZero's authenticity assessment for `text`."""
    if not GPTZERO_API_KEY:
        return {"available": False, "error": "GPTZERO_API_KEY not set"}
    try:
        t0 = time.perf_counter()
        r = requests.post(
            _GPTZERO_URL,
            headers={"x-api-key": GPTZERO_API_KEY, "Content-Type": "application/json"},
            json={"document": text[:50000]},
            timeout=30,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        if not r.ok:
            return {"available": True, "ok": False, "status": r.status_code,
                    "error": r.text[:300], "ms": ms}
        data = r.json()
        doc = (data.get("documents") or [{}])[0]
        probs = doc.get("class_probabilities", {}) or {}
        return {
            "available": True,
            "ok": True,
            "ms": ms,
            "completely_generated_prob": doc.get("completely_generated_prob"),
            "predicted_class": doc.get("predicted_class"),
            "class_probabilities": probs,
            "human_prob": probs.get("human"),
            "ai_prob": probs.get("ai"),
            "mixed_prob": probs.get("mixed"),
        }
    except Exception as e:  # noqa: BLE001
        return {"available": True, "ok": False, "error": f"{type(e).__name__}: {e}"}


def grade_with_openai(subject: str, text: str) -> dict:
    """Have OpenAI grade the legitimacy / soundness of an AI answer."""
    client = get_openai_client()
    prompt = (
        "You are a strict quality-control reviewer for an investing-analysis app. "
        f"Evaluate the following AI-generated output (subject: {subject}). "
        "Judge: (a) internal consistency, (b) whether numbers/probabilities are "
        "used coherently, (c) whether it actually answers the user's need, and "
        "(d) presence of unsafe or fabricated claims. "
        "Return strict JSON with keys: legitimate (boolean), score (0-100 integer "
        "overall quality), issues (array of short strings), summary (one sentence).\n\n"
        "=== OUTPUT TO REVIEW ===\n" + text[:12000]
    )
    try:
        resp = client.chat.completions.create(
            model=_QC_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_completion_tokens=8192,
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "legitimate": False,
            "score": None,
            "issues": [],
            "summary": "",
            "error": f"{type(e).__name__}: {e}",
        }
    return {
        "ok": True,
        "legitimate": bool(data.get("legitimate", False)),
        "score": data.get("score"),
        "issues": data.get("issues", []),
        "summary": data.get("summary", ""),
    }


def run_quality_control(subject: str, text: str,
                        user_email: Optional[str] = None) -> dict:
    """Run OpenAI grading + GPTZero, combine, persist. Returns result dict."""
    if not openai_available():
        return {"ok": False, "error": "OpenAI integration not configured."}
    if not text or not text.strip():
        return {"ok": False, "error": "No text provided to evaluate."}

    verdict = grade_with_openai(subject, text)
    if not verdict.get("ok", True):
        return {"ok": False, "error": f"OpenAI grading failed: {verdict.get('error')}"}
    gptzero = check_gptzero(text)

    score = verdict.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    legitimate, rationale = _combine_verdict(verdict, gptzero)

    row_id = db.save_qc_result(
        subject=subject,
        source_text=text,
        openai_verdict=verdict,
        gptzero=gptzero,
        legitimate=legitimate,
        score=score,
        user_email=user_email,
    )

    return {
        "ok": True,
        "subject": subject,
        "verdict": verdict,
        "gptzero": gptzero,
        "legitimate": legitimate,
        "rationale": rationale,
        "score": score,
        "row_id": row_id,
    }


# GPTZero machine-generated probability above this fails the authenticity signal.
_GPTZERO_AI_THRESHOLD = 0.85


def _combine_verdict(verdict: dict, gptzero: dict) -> tuple[bool, str]:
    """Combine the OpenAI soundness verdict with the GPTZero authenticity signal
    into a single legitimacy decision. An answer is legitimate only if OpenAI
    judges it sound AND GPTZero does not flag it as almost-certainly machine
    generated (when GPTZero is available)."""
    openai_ok = bool(verdict.get("legitimate"))
    ai_prob = gptzero.get("completely_generated_prob") if gptzero.get("ok") else None

    if not openai_ok:
        return False, "OpenAI flagged the answer as unsound or unsafe."

    if gptzero.get("ok") and isinstance(ai_prob, (int, float)):
        if ai_prob >= _GPTZERO_AI_THRESHOLD:
            return False, (
                f"OpenAI judged it sound, but GPTZero flags it as "
                f"{ai_prob * 100:.0f}% machine-generated (≥ "
                f"{_GPTZERO_AI_THRESHOLD * 100:.0f}% threshold)."
            )
        return True, (
            f"OpenAI judged it sound and GPTZero authenticity is acceptable "
            f"({ai_prob * 100:.0f}% machine-generated)."
        )

    return True, "OpenAI judged it sound (GPTZero authenticity signal unavailable)."


def render_quality_control_tab(user_email: Optional[str] = None) -> None:
    st.markdown("### ✅ Quality Control")
    st.markdown(
        "Verifies the **legitimacy** of an AI answer: OpenAI grades it against a "
        "soundness rubric, and GPTZero scores how machine-generated it looks. "
        "Use the latest synthetic-user / strategy output, or paste your own text."
    )
    if not openai_available():
        st.error("OpenAI integration is not configured.")
        return
    if not gptzero_available():
        st.warning("GPTZERO_API_KEY not set — the authenticity check will be skipped.")

    last = st.session_state.get("last_ai_answer")
    default_subject = last["subject"] if last else "Strategy output"
    default_text = last["text"] if last else ""

    subject = st.text_input("Subject", value=default_subject)
    text = st.text_area(
        "Text to verify",
        value=default_text,
        height=200,
        placeholder="Paste an AI-generated answer, or run a Synthetic User session first.",
    )

    if st.button("Run quality control", type="primary"):
        if not text.strip():
            st.warning("Provide some text to evaluate.")
        else:
            with st.spinner("Grading with OpenAI and checking authenticity with GPTZero…"):
                st.session_state["qc_result"] = run_quality_control(subject, text, user_email)

    result = st.session_state.get("qc_result")
    if not result:
        return
    if not result.get("ok"):
        st.error(result.get("error", "Quality control failed."))
        return

    verdict = result["verdict"]
    cols = st.columns(3)
    with cols[0]:
        st.metric("Legitimate", "Yes" if result["legitimate"] else "No")
    with cols[1]:
        st.metric("Quality score", f"{result['score']:.0f}/100" if result["score"] is not None else "—")
    with cols[2]:
        gz = result["gptzero"]
        if gz.get("ok"):
            ai_p = gz.get("completely_generated_prob")
            st.metric("AI-generated likelihood", f"{ai_p * 100:.0f}%" if isinstance(ai_p, (int, float)) else "—")
        else:
            st.metric("AI-generated likelihood", "n/a")

    if result.get("rationale"):
        st.caption(f"Verdict basis: {result['rationale']}")
    if verdict.get("summary"):
        st.info(verdict["summary"])
    issues = verdict.get("issues") or []
    if issues:
        st.markdown("**Issues flagged**")
        for it in issues:
            st.markdown(f"- {it}")

    with st.expander("OpenAI verdict (raw)"):
        st.json(verdict)
    with st.expander("GPTZero result (raw)"):
        st.json(result["gptzero"])
    if result.get("row_id"):
        st.caption(f"Saved as qc_results row #{result['row_id']}")
