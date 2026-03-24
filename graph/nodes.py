"""Non-LLM nodes: change_detector, action_router, notifier."""
from datetime import datetime
from db.database import execute_query, execute_write
from models.state import OrchestratorState


def change_detector_node(state: OrchestratorState) -> dict:
    changed, high, medium, low = [], [], [], []

    for customer in state.get("customer_results", []):
        if customer.get("error") or not customer.get("health_score"):
            continue

        prev = execute_query(
            "SELECT score, risk_level, reason, checked_at FROM health_scores "
            "WHERE customer_id = ? ORDER BY checked_at DESC LIMIT 1",
            (customer["customer_id"],)
        )

        score_delta = 0
        risk_escalated = False
        needs_action = True  # always act on first run

        if prev:
            old_score = prev[0]["score"]
            old_risk = prev[0]["risk_level"]
            score_delta = customer["health_score"] - old_score
            risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
            risk_escalated = (
                risk_order.get(customer["risk_level"], 0) >
                risk_order.get(old_risk, 0)
            )
            needs_action = abs(score_delta) > 10 or risk_escalated

        # Always write new score to DB
        execute_write(
            "INSERT INTO health_scores (customer_id, score, risk_level, reason, checked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (customer["customer_id"], customer["health_score"],
             customer["risk_level"], customer["churn_reason"],
             datetime.utcnow().isoformat())
        )

        updated = {
            **customer,
            "previous_record": prev[0] if prev else None,
            "score_delta": score_delta,
            "risk_escalated": risk_escalated,
            "needs_action": needs_action,
        }

        if needs_action:
            changed.append(updated)
            if customer["risk_level"] == "HIGH":
                high.append(updated)
            elif customer["risk_level"] == "MEDIUM":
                medium.append(updated)
            else:
                low.append(updated)

    # IMPORTANT: do NOT include customer_results here — it has an operator.add reducer
    # returning it from a sequential node would append it to itself
    return {
        "changed_customers": changed,
        "high_risk_customers": high,
        "medium_risk_customers": medium,
        "low_risk_customers": low,
    }


def action_router_node(state: OrchestratorState) -> dict:
    """Pass-through — fan-out to process_outreach is handled by conditional edge."""
    return {}


def merge_outreach_node(state: OrchestratorState) -> dict:
    """Log outreach drafts to DB. customer_results already merged via reducer."""
    for customer in state.get("customer_results", []):
        if customer.get("outreach_draft"):
            execute_write(
                "INSERT INTO outreach_log (customer_id, subject, draft, created_at) VALUES (?, ?, ?, ?)",
                (customer["customer_id"], customer.get("outreach_subject", ""),
                 customer["outreach_draft"], datetime.utcnow().isoformat())
            )
    return {}


def notifier_node(state: OrchestratorState) -> dict:
    """Log run summary. In production: send email/Slack."""
    high = len(state.get("high_risk_customers", []) or [])
    medium = len(state.get("medium_risk_customers", []) or [])
    total = len(state.get("customer_results", []))
    print(f"\n{'='*50}")
    print(f"Churn Detection Run Complete — {state['run_id']}")
    print(f"Customers processed: {total}")
    print(f"HIGH risk: {high} | MEDIUM risk: {medium}")
    print(f"Total cost: ${state.get('total_cost_usd', 0):.4f}")
    print(f"{'='*50}\n")
    return {"status": "complete", "completed_at": datetime.utcnow().isoformat()}
