import json
import os
import anthropic
from dotenv import load_dotenv
from models.state import CustomerState
from tools.rate_limiter import with_rate_limit

load_dotenv()

SYSTEM = """You are a customer success analyst scoring SaaS customer health.
Given customer signals, return ONLY a JSON object:
{
  "health_score": <integer 0-100>,
  "risk_level": "<HIGH|MEDIUM|LOW>",
  "churn_reason": "<one clear sentence explaining the primary churn risk>",
  "score_confidence": "<LOW|MEDIUM|HIGH>"
}

Scoring guide:
- 80-100: LOW risk — healthy engagement
- 50-79: MEDIUM risk — declining or concerning signals
- 0-49: HIGH risk — critical churn indicators

HIGH risk triggers: payment failures, no login 30+ days, zero feature use 14+ days.
MEDIUM risk triggers: declining login frequency, reduced feature adoption, support tickets.
LOW risk: regular logins, active feature use, no payment issues."""


def health_scorer_node(state: CustomerState) -> dict:
    if not state.get("signals"):
        return {**state, "health_score": 0, "risk_level": "HIGH",
                "churn_reason": "Unable to collect signals", "processing_status": "error"}

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    signals = state["signals"]

    prompt = (
        f"Customer: {state['customer_name']} at {state['company']} "
        f"(Plan: {state['plan']}, MRR: ${state['mrr']}/month)\n\n"
        f"Signals (last 30 days):\n{json.dumps(signals, indent=2)}\n\n"
        "Score this customer's health and churn risk."
    )

    response = with_rate_limit(
        client.messages.create,
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = (input_tokens * 3 + output_tokens * 15) / 1_000_000

    result = {}
    try:
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        result = json.loads(text)
    except Exception:
        result = {"health_score": 50, "risk_level": "MEDIUM",
                  "churn_reason": "Scoring parse error", "score_confidence": "LOW"}

    return {
        **state,
        "health_score": result.get("health_score", 50),
        "risk_level": result.get("risk_level", "MEDIUM"),
        "churn_reason": result.get("churn_reason", "Unknown"),
        "input_tokens": state.get("input_tokens", 0) + input_tokens,
        "output_tokens": state.get("output_tokens", 0) + output_tokens,
        "cost_usd": state.get("cost_usd", 0.0) + cost,
        "processing_status": "scored",
    }
