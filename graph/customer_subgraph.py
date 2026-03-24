"""Per-customer subgraph: signal_collector → health_scorer."""
from langgraph.graph import StateGraph, END
from models.state import CustomerState
from agents.signal_collector import signal_collector_node
from agents.health_scorer import health_scorer_node


def build_customer_subgraph():
    builder = StateGraph(CustomerState)
    builder.add_node("signal_collector", signal_collector_node)
    builder.add_node("health_scorer", health_scorer_node)
    builder.set_entry_point("signal_collector")
    builder.add_edge("signal_collector", "health_scorer")
    builder.add_edge("health_scorer", END)
    return builder.compile()


customer_subgraph = build_customer_subgraph()
