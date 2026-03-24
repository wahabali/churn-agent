import json
import os
import anthropic
from dotenv import load_dotenv
from models.state import CustomerState
from tools.sql_tool import SQL_TOOL, safe_execute_sql
from tools.rate_limiter import with_rate_limit

load_dotenv()

MAX_ITERATIONS = 8

SYSTEM = """You are a data analyst collecting churn signals for a SaaS customer.
Use the execute_sql tool to query the database and calculate these metrics for the given customer_id:
- login_count_30d: total logins in last 30 days
- feature_use_count_30d: total feature_use events in last 30 days
- api_call_count_30d: total api_call events in last 30 days
- support_tickets_30d: total support_ticket events in last 30 days
- payment_failed_30d: total payment_failed events in last 30 days
- days_since_last_login: days since most recent login (use 999 if never)
- days_since_last_feature_use: days since most recent feature_use (use 999 if never)
- unique_features_used: count of distinct event_types (excluding login/payment_failed)
- avg_logins_per_week: average logins per week over last 30 days

When done, respond with ONLY a valid JSON object with all these fields. No explanation."""


def signal_collector_node(state: CustomerState) -> dict:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    customer_id = state["customer_id"]

    messages = [{
        "role": "user",
        "content": (
            f"Collect churn signals for customer_id='{customer_id}' "
            f"(company: {state['company']}, plan: {state['plan']}, MRR: ${state['mrr']}/month). "
            "Use datetime('now', '-30 days') for the 30-day window in SQLite."
        )
    }]

    input_tokens = output_tokens = tool_calls = 0
    signals = None

    for _ in range(MAX_ITERATIONS):
        response = with_rate_limit(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM,
            tools=[SQL_TOOL],
            messages=messages,
        )
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls += 1
                    result = safe_execute_sql(block.input["query"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    try:
                        text = block.text.strip()
                        if "```" in text:
                            text = text.split("```")[1].replace("json", "").strip()
                        signals = json.loads(text)
                    except Exception:
                        pass
            break

    cost = (input_tokens * 0.8 + output_tokens * 4) / 1_000_000
    return {
        **state,
        "signals": signals,
        "tool_calls_made": tool_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "processing_status": "signals_collected" if signals else "signals_failed",
        "error": None if signals else "Failed to collect signals",
    }
