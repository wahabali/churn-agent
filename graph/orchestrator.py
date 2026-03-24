"""Full orchestration graph."""
from datetime import datetime
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from models.state import OrchestratorState, CustomerState
from db.database import execute_query
from graph.nodes import change_detector_node, action_router_node, merge_outreach_node, notifier_node
from agents.signal_collector import signal_collector_node
from agents.health_scorer import health_scorer_node
from agents.outreach_drafter import outreach_drafter_node
from agents.report_agent import report_agent_node


def process_customer(state: CustomerState) -> dict:
    """Run signal collection + health scoring for one customer.
    Returns {"customer_results": [result]} so the reducer merges results from all parallel branches.
    """
    result = signal_collector_node(state)
    result = health_scorer_node(result)
    return {"customer_results": [result]}


def orchestrator_node(state: OrchestratorState) -> list[Send]:
    """Load all customers and fan out to process_customer in parallel."""
    rows = execute_query(
        "SELECT id, name, company, plan, mrr, signup_date, csm_name FROM customers"
    )
    sends = []
    for row in rows:
        customer_state = CustomerState(
            customer_id=row["id"],
            customer_name=row["name"],
            company=row["company"],
            plan=row["plan"],
            mrr=row["mrr"],
            csm_name=row["csm_name"],
            signup_date=row["signup_date"],
            signals=None,
            health_score=None,
            risk_level=None,
            churn_reason=None,
            previous_record=None,
            score_delta=None,
            risk_escalated=None,
            needs_action=None,
            outreach_draft=None,
            outreach_subject=None,
            tool_calls_made=0,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            error=None,
            processing_status="pending",
        )
        sends.append(Send("process_customer", customer_state))
    return sends


def aggregate_results_node(state: OrchestratorState) -> dict:
    results = state.get("customer_results", [])
    total_tokens = sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in results)
    total_cost = sum(r.get("cost_usd", 0.0) for r in results)
    errors = sum(1 for r in results if r.get("error"))
    # IMPORTANT: do NOT include customer_results — operator.add reducer would append it to itself
    return {
        "total_tokens_used": total_tokens,
        "total_cost_usd": total_cost,
        "errors_encountered": errors,
        "status": "processing",
    }


def process_outreach(state: CustomerState) -> dict:
    """Draft outreach for one HIGH risk customer. Returns customer_results update."""
    result = outreach_drafter_node(state)
    return {"customer_results": [result]}


def build_graph():
    builder = StateGraph(OrchestratorState)

    builder.add_node("process_customer", process_customer)
    builder.add_node("aggregate_results", aggregate_results_node)
    builder.add_node("change_detector", change_detector_node)
    builder.add_node("action_router", action_router_node)
    builder.add_node("process_outreach", process_outreach)
    builder.add_node("merge_outreach", merge_outreach_node)
    builder.add_node("report_agent", report_agent_node)
    builder.add_node("notifier", notifier_node)

    # Fan-out: one process_customer per customer
    builder.add_conditional_edges(START, orchestrator_node)
    # Fan-in: all process_customer results merge via operator.add
    builder.add_edge("process_customer", "aggregate_results")
    builder.add_edge("aggregate_results", "change_detector")
    builder.add_edge("change_detector", "action_router")

    # Fan-out: outreach per HIGH risk customer, or skip to merge
    builder.add_conditional_edges(
        "action_router",
        lambda state: [Send("process_outreach", c) for c in state.get("high_risk_customers", [])]
        if state.get("high_risk_customers") else "merge_outreach"
    )
    builder.add_edge("process_outreach", "merge_outreach")
    builder.add_edge("merge_outreach", "report_agent")
    builder.add_edge("report_agent", "notifier")
    builder.add_edge("notifier", END)

    return builder.compile()


graph = build_graph()
