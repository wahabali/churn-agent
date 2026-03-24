"""Generate HTML digest report from run results."""
import os
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from models.state import OrchestratorState

TEMPLATE_DIR = Path(__file__).parent.parent / "reports" / "templates"


def report_agent_node(state: OrchestratorState) -> dict:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("digest.html.jinja2")

    html = template.render(
        run_id=state["run_id"],
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        high_risk=state.get("high_risk_customers", []),
        medium_risk=state.get("medium_risk_customers", []),
        low_risk=state.get("low_risk_customers", []),
        total_customers=len(state.get("customer_results", [])),
        total_cost=state.get("total_cost_usd", 0),
        errors=state.get("errors_encountered", 0),
    )

    report_dir = Path(__file__).parent.parent / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"digest_{state['run_id']}.html"
    report_path.write_text(html)

    # Also write as latest
    latest_path = report_dir / "latest.html"
    latest_path.write_text(html)

    return {"html_report": html, "report_path": str(report_path)}
