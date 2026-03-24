"""Generate HTML and Markdown digest reports from run results."""
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from models.state import OrchestratorState

TEMPLATE_DIR = Path(__file__).parent.parent / "reports" / "templates"


def _build_markdown(state: OrchestratorState, generated_at: str) -> str:
    high = state.get("high_risk_customers") or []
    medium = state.get("medium_risk_customers") or []
    low = state.get("low_risk_customers") or []
    total = len(state.get("customer_results", []))

    lines = [
        f"# Churn Detection Report — {state['run_id']}",
        f"_Generated: {generated_at}_",
        "",
        "## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total customers | {total} |",
        f"| HIGH risk | {len(high)} |",
        f"| MEDIUM risk | {len(medium)} |",
        f"| LOW risk | {len(low)} |",
        f"| Total cost | ${state.get('total_cost_usd', 0):.4f} |",
        f"| Errors | {state.get('errors_encountered', 0)} |",
        "",
    ]

    for label, customers, emoji in [("HIGH", high, "🔴"), ("MEDIUM", medium, "🟡"), ("LOW", low, "🟢")]:
        if not customers:
            continue
        lines.append(f"## {emoji} {label} Risk ({len(customers)})")
        lines.append("")
        for c in customers:
            lines += [
                f"### {c['customer_name']} — {c['company']}",
                f"**Plan:** {c['plan']} | **MRR:** ${c['mrr']}/month | **CSM:** {c['csm_name']}",
                f"**Health score:** {c.get('health_score', 'N/A')} | **Delta:** {c.get('score_delta', 0):+d}",
                f"**Churn reason:** {c.get('churn_reason', 'N/A')}",
            ]
            if c.get("outreach_draft"):
                lines += [
                    "",
                    f"**Outreach subject:** {c.get('outreach_subject', '')}",
                    "",
                    "> " + c["outreach_draft"].replace("\n", "\n> "),
                ]
            lines.append("")

    return "\n".join(lines)


def report_agent_node(state: OrchestratorState) -> dict:
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("digest.html.jinja2")

    html = template.render(
        run_id=state["run_id"],
        generated_at=generated_at,
        high_risk=state.get("high_risk_customers", []),
        medium_risk=state.get("medium_risk_customers", []),
        low_risk=state.get("low_risk_customers", []),
        total_customers=len(state.get("customer_results", [])),
        total_cost=state.get("total_cost_usd", 0),
        errors=state.get("errors_encountered", 0),
    )

    md = _build_markdown(state, generated_at)

    report_dir = Path(__file__).parent.parent / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    run_id = state["run_id"]
    (report_dir / f"digest_{run_id}.html").write_text(html)
    (report_dir / f"digest_{run_id}.md").write_text(md)
    (report_dir / "latest.html").write_text(html)
    (report_dir / "latest.md").write_text(md)

    return {"html_report": html, "report_path": str(report_dir / f"digest_{run_id}.html")}
