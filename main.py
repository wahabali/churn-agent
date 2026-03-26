"""Entry point: FastAPI app + HITL review endpoints."""
import uuid
import os
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from db.database import init_db, execute_query
from graph.orchestrator import graph, checkpointer
from models.state import OrchestratorState
from langgraph.types import Command

# In-memory run store (use Redis/DB in production)
_runs: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="Churn Detection Agent",
    description="Multi-agent customer churn detection powered by Claude + LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)


class RunResponse(BaseModel):
    run_id: str
    status: str
    message: str


class ResumeRequest(BaseModel):
    approved_ids: List[str]


def _thread_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def run_analysis(run_id: str, triggered_by: str):
    _runs[run_id] = {"status": "running", "started_at": datetime.utcnow().isoformat()}
    config = _thread_config(run_id)
    try:
        initial_state = OrchestratorState(
            run_id=run_id,
            triggered_by=triggered_by,
            started_at=datetime.utcnow().isoformat(),
            completed_at=None,
            customer_results=[],
            changed_customers=None,
            high_risk_customers=None,
            medium_risk_customers=None,
            low_risk_customers=None,
            approved_outreach=None,
            html_report=None,
            report_path=None,
            total_tokens_used=0,
            total_cost_usd=0.0,
            errors_encountered=0,
            status="running",
            langfuse_trace_id=run_id,
        )
        result = graph.invoke(initial_state, config=config)

        # Check if graph paused at approval_gate interrupt
        snapshot = graph.get_state(config)
        if snapshot.next:
            pending = [
                c for c in result.get("customer_results", [])
                if c.get("outreach_draft")
            ]
            _runs[run_id] = {
                "status": "awaiting_approval",
                "started_at": result["started_at"],
                "total_customers": len(result.get("customer_results", [])),
                "high_risk": len(result.get("high_risk_customers") or []),
                "medium_risk": len(result.get("medium_risk_customers") or []),
                "total_cost_usd": result.get("total_cost_usd", 0),
                "pending_outreach": pending,
                "review_url": f"/review/{run_id}",
            }
        else:
            _finalise_run(run_id, result)

    except Exception as e:
        _runs[run_id] = {"status": "error", "error": str(e)}


def resume_analysis(run_id: str, approved_ids: list[str]):
    config = _thread_config(run_id)
    try:
        result = graph.invoke(
            Command(resume={"approved_ids": approved_ids}),
            config=config,
        )
        _finalise_run(run_id, result)
    except Exception as e:
        _runs[run_id] = {**_runs.get(run_id, {}), "status": "error", "error": str(e)}


def _finalise_run(run_id: str, result: dict):
    approved = result.get("approved_outreach") or []
    _runs[run_id] = {
        "status": "complete",
        "started_at": result["started_at"],
        "completed_at": result.get("completed_at"),
        "total_customers": len(result.get("customer_results", [])),
        "high_risk": len(result.get("high_risk_customers") or []),
        "medium_risk": len(result.get("medium_risk_customers") or []),
        "outreach_approved": len(approved),
        "total_cost_usd": result.get("total_cost_usd", 0),
        "report_path": result.get("report_path"),
        "errors": result.get("errors_encountered", 0),
    }


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.post("/run", response_model=RunResponse, status_code=202)
async def trigger_run(background_tasks: BackgroundTasks, triggered_by: str = "api"):
    run_id = str(uuid.uuid4())[:8]
    background_tasks.add_task(run_analysis, run_id, triggered_by)
    return RunResponse(run_id=run_id, status="queued",
                       message=f"Analysis queued. Poll GET /status/{run_id}")


@app.get("/status/{run_id}")
async def get_status(run_id: str):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/resume/{run_id}", status_code=202)
async def resume_run(run_id: str, body: ResumeRequest, background_tasks: BackgroundTasks):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") != "awaiting_approval":
        raise HTTPException(status_code=400,
                            detail=f"Run is not awaiting approval (status: {run.get('status')})")
    _runs[run_id]["status"] = "resuming"
    background_tasks.add_task(resume_analysis, run_id, body.approved_ids)
    return {"run_id": run_id, "status": "resuming", "approved_ids": body.approved_ids}


@app.get("/review/{run_id}", response_class=HTMLResponse)
async def review_page(run_id: str):
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    status = run.get("status")
    if status == "running":
        return HTMLResponse(_loading_page(run_id))
    if status != "awaiting_approval":
        return HTMLResponse(_status_page(run_id, run))
    return HTMLResponse(_review_page(run_id, run.get("pending_outreach", []), run))


@app.get("/customers")
async def list_customers():
    rows = execute_query("""
        SELECT c.id, c.name, c.company, c.plan, c.mrr, c.csm_name,
               h.score, h.risk_level, h.reason, h.checked_at
        FROM customers c
        LEFT JOIN health_scores h ON h.id = (
            SELECT id FROM health_scores WHERE customer_id = c.id ORDER BY checked_at DESC LIMIT 1
        )
        ORDER BY h.score ASC
    """)
    return rows


@app.get("/customers/{customer_id}/history")
async def customer_history(customer_id: str):
    rows = execute_query(
        "SELECT score, risk_level, reason, checked_at FROM health_scores "
        "WHERE customer_id = ? ORDER BY checked_at DESC LIMIT 30",
        (customer_id,)
    )
    return rows


@app.get("/report/latest", response_class=HTMLResponse)
async def latest_report():
    report_path = Path("data/reports/latest.html")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No report generated yet. Run POST /run first.")
    return HTMLResponse(content=report_path.read_text())


@app.get("/report/latest.md")
async def latest_report_markdown():
    report_path = Path("data/reports/latest.md")
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="No report generated yet. Run POST /run first.")
    return FileResponse(path=str(report_path), media_type="text/markdown", filename="churn-report.md")


# ── HTML templates ─────────────────────────────────────────────────────────────

STYLE = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #FAF9F7;
    color: #1A1A1A;
    padding: 48px 32px;
    max-width: 860px;
    margin: 0 auto;
  }
  h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.4px; }
  .meta { color: #888; font-size: 13px; margin-top: 4px; margin-bottom: 32px; }
  .card {
    background: #fff;
    border: 1px solid #E8E8E4;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 20px;
  }
  .card-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
  .badge {
    font-size: 11px; font-weight: 600; padding: 3px 10px;
    border-radius: 20px; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .badge-high { background: #FDE8E4; color: #C0392B; }
  .badge-medium { background: #FEF3CD; color: #8B6914; }
  .company { font-size: 17px; font-weight: 600; }
  .signals { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
  .signal { background: #F4F4F1; border-radius: 6px; padding: 4px 10px; font-size: 12px; color: #555; }
  .signal.alert { background: #FDE8E4; color: #C0392B; }
  label {
    font-size: 12px; font-weight: 600; color: #888; text-transform: uppercase;
    letter-spacing: 0.5px; display: block; margin-bottom: 6px;
  }
  textarea {
    width: 100%; border: 1px solid #E0E0DC; border-radius: 8px;
    padding: 12px; font-size: 13px; font-family: inherit;
    line-height: 1.6; color: #333; resize: vertical; min-height: 120px; background: #FAFAF8;
  }
  .reason { font-size: 13px; color: #666; margin-bottom: 14px; font-style: italic; }
  .actions { display: flex; gap: 10px; margin-top: 16px; align-items: center; }
  .btn-approve {
    background: #1A1A1A; color: #fff; border: none; border-radius: 8px;
    padding: 10px 20px; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  .btn-approve:hover { background: #333; }
  .btn-skip {
    background: transparent; color: #888; border: 1px solid #DDD;
    border-radius: 8px; padding: 10px 20px; font-size: 13px; cursor: pointer;
  }
  .btn-skip:hover { border-color: #999; color: #555; }
  .submit-bar {
    background: #fff; border: 1px solid #E8E8E4; border-left: 4px solid #E55B3C;
    border-radius: 12px; padding: 20px 24px;
    display: flex; align-items: center; justify-content: space-between; margin-top: 8px;
  }
  .submit-info { font-size: 14px; color: #333; }
  .submit-info span { font-weight: 700; color: #E55B3C; }
  .btn-submit {
    background: #E55B3C; color: #fff; border: none; border-radius: 8px;
    padding: 12px 28px; font-size: 14px; font-weight: 700; cursor: pointer;
  }
  .btn-submit:hover { background: #C94A2E; }
"""


def _signal_chips(customer: dict) -> str:
    signals = customer.get("signals") or {}
    chips = []
    days = signals.get("days_since_last_login", 0)
    if days:
        cls = "alert" if days > 14 else ""
        chips.append(f'<span class="signal {cls}">No login {days}d</span>')
    failed = signals.get("payment_failed_30d", 0)
    if failed:
        chips.append(f'<span class="signal alert">Payment failed {failed}×</span>')
    tickets = signals.get("support_tickets_30d", 0)
    if tickets:
        chips.append(f'<span class="signal">Tickets {tickets}</span>')
    logins = signals.get("login_count_30d", 0)
    chips.append(f'<span class="signal">Logins 30d: {logins}</span>')
    score = customer.get("health_score", "?")
    delta = customer.get("score_delta")
    delta_str = f" (▼{abs(delta)})" if delta and delta < 0 else ""
    chips.append(f'<span class="signal">Score: {score}{delta_str}</span>')
    return "".join(chips)


def _review_page(run_id: str, pending: list, run: dict) -> str:
    cards_html = ""
    for c in pending:
        cid = c["customer_id"]
        risk = c.get("risk_level", "HIGH")
        badge_cls = "badge-high" if risk == "HIGH" else "badge-medium"
        draft = c.get("outreach_draft", "").replace("<", "&lt;").replace(">", "&gt;")
        subject = c.get("outreach_subject", "")
        reason = c.get("churn_reason", "")

        cards_html += f"""
<div class="card" id="card-{cid}">
  <div class="card-header">
    <span class="badge {badge_cls}">{risk}</span>
    <span class="company">{c.get('company', '')} — {c.get('customer_name', '')}</span>
  </div>
  <div class="signals">{_signal_chips(c)}</div>
  <p class="reason">{reason}</p>
  <label>Draft — {subject}</label>
  <textarea id="draft-{cid}">{draft}</textarea>
  <div class="actions">
    <button class="btn-approve" id="btn-approve-{cid}" onclick="approve('{cid}')">Approve</button>
    <button class="btn-skip" id="btn-skip-{cid}" onclick="skip('{cid}')">Skip</button>
  </div>
</div>"""

    cost = run.get("total_cost_usd", 0)
    n = run.get("total_customers", 0)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Review Outreach — {run_id}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>Outreach Review</h1>
<p class="meta">Run {run_id} &nbsp;·&nbsp; {n} customers processed &nbsp;·&nbsp; Cost: ${cost:.4f} &nbsp;·&nbsp; {len(pending)} draft(s) awaiting approval</p>

{cards_html}

<div class="submit-bar">
  <div class="submit-info"><span id="approved-count">0</span> of {len(pending)} approved</div>
  <button class="btn-submit" onclick="submitApprovals()">Submit &amp; Resume Agent</button>
</div>

<script>
const approved = new Set();
const skipped = new Set();

function approve(id) {{
  approved.add(id);
  skipped.delete(id);
  document.getElementById('btn-approve-' + id).textContent = '✓ Approved';
  document.getElementById('btn-approve-' + id).style.background = '#27AE60';
  document.getElementById('btn-skip-' + id).textContent = 'Skip';
  document.getElementById('btn-skip-' + id).style.background = 'transparent';
  document.getElementById('btn-skip-' + id).style.color = '#888';
  document.getElementById('approved-count').textContent = approved.size;
}}

function skip(id) {{
  skipped.add(id);
  approved.delete(id);
  document.getElementById('btn-skip-' + id).textContent = '✗ Skipped';
  document.getElementById('btn-skip-' + id).style.background = '#F4F4F1';
  document.getElementById('btn-skip-' + id).style.color = '#999';
  document.getElementById('btn-approve-' + id).textContent = 'Approve';
  document.getElementById('btn-approve-' + id).style.background = '#1A1A1A';
  document.getElementById('approved-count').textContent = approved.size;
}}

async function submitApprovals() {{
  const btn = document.querySelector('.btn-submit');
  btn.textContent = 'Resuming agent...';
  btn.disabled = true;
  const res = await fetch('/resume/{run_id}', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ approved_ids: Array.from(approved) }})
  }});
  if (res.ok) {{
    btn.textContent = 'Agent resumed ✓';
    btn.style.background = '#27AE60';
    document.querySelector('.submit-info').innerHTML =
      'Agent completing run — check <a href="/status/{run_id}">/status/{run_id}</a>';
  }} else {{
    btn.textContent = 'Error — try again';
    btn.disabled = false;
    btn.style.background = '#C94A2E';
  }}
}}
</script>
</body>
</html>"""


def _loading_page(run_id: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="3">
<title>Running — {run_id}</title><style>{STYLE}</style></head>
<body>
<h1>Agent Running</h1>
<p class="meta">Run {run_id} — page refreshes every 3s</p>
<div class="card"><p style="color:#888">Processing customers in parallel...</p></div>
</body></html>"""


def _status_page(run_id: str, run: dict) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Run {run_id}</title><style>{STYLE}</style></head>
<body>
<h1>Run {run_id}</h1>
<p class="meta">Status: {run.get('status', 'unknown')}</p>
<div class="card"><pre style="font-size:13px;color:#555;white-space:pre-wrap">{run}</pre></div>
</body></html>"""
