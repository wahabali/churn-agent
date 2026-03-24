"""Entry point: FastAPI app + APScheduler."""
import uuid
import os
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from db.database import init_db, execute_query
from graph.orchestrator import graph
from models.state import OrchestratorState

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


def run_analysis(run_id: str, triggered_by: str):
    _runs[run_id] = {"status": "running", "started_at": datetime.utcnow().isoformat()}
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
            html_report=None,
            report_path=None,
            total_tokens_used=0,
            total_cost_usd=0.0,
            errors_encountered=0,
            status="running",
            langfuse_trace_id=run_id,
        )
        result = graph.invoke(initial_state)
        _runs[run_id] = {
            "status": "complete",
            "started_at": result["started_at"],
            "completed_at": result.get("completed_at"),
            "total_customers": len(result.get("customer_results", [])),
            "high_risk": len(result.get("high_risk_customers") or []),
            "medium_risk": len(result.get("medium_risk_customers") or []),
            "total_cost_usd": result.get("total_cost_usd", 0),
            "report_path": result.get("report_path"),
            "errors": result.get("errors_encountered", 0),
        }
    except Exception as e:
        _runs[run_id] = {"status": "error", "error": str(e)}


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
