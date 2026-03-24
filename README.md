# Customer Churn Detection & Prevention Agent

A production-grade multi-agent system that autonomously monitors SaaS customer health, detects churn risk, and drafts personalised outreach — powered by Claude + LangGraph.

## What makes this genuinely agentic

| Capability | Implementation |
|---|---|
| **Persistent memory** | `health_scores` table — agent remembers history across runs |
| **Change detection** | Only acts on meaningful score changes (>10pts or risk escalation) |
| **True parallelism** | LangGraph Send API — N customers processed concurrently |
| **Agentic tool use** | Signal collector loop — Claude decides which SQL queries to run |
| **Error isolation** | Per-customer try/except — one failure doesn't stop the run |
| **Cost tracking** | USD cost per customer and per run in state and API response |

This cannot be replaced by "upload a spreadsheet to Claude.ai". The agent:
- Monitors signals over time via a real SQL database
- Takes autonomous actions based on *changes* (not just current state)
- Uses a real tool-use loop where Claude decides which queries to run
- Processes all customers in parallel threads via LangGraph's Send API
- Runs on a schedule without human trigger

## Architecture

```
START
  ↓
[orchestrator_node]           ← loads all customers, fans out via Send API
  ↓ (Send API — N parallel)
[process_customer] × N        ← signal_collector (tool loop) → health_scorer
  ↓ (fan-in → aggregate list)
[aggregate_results]           ← sums tokens + cost
  ↓
[change_detector]             ← diffs vs DB history, writes new scores
  ↓
[action_router]               ← routes HIGH risk customers for outreach
  ↓ (Send API — M parallel)
[process_outreach] × M        ← Claude drafts personalised email
  ↓ (fan-in)
[merge_outreach]              ← logs drafts to DB
  ↓
[report_agent]                ← generates HTML digest
  ↓
[notifier]                    ← prints summary (SMTP optional)
  ↓
END
```

Two levels of parallel fan-out via LangGraph's Send API:
1. All N customers processed in parallel (signal collection + scoring)
2. All M HIGH-risk customers get personalised outreach in parallel

## Stack

- **Claude** (claude-sonnet-4-6) — signal analysis, health scoring, outreach drafting
- **LangGraph** — stateful multi-agent orchestration with parallel fan-out
- **FastAPI** — async REST API with 202 Accepted pattern
- **SQLite** — persistent customer history (swap for PostgreSQL in production)
- **Jinja2** — HTML report generation

## Quick Start

```bash
git clone https://github.com/syedwahabali/churn-agent
cd churn-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

python db/seed.py          # creates 20 demo customers (3 HIGH, 5 MEDIUM, 12 LOW risk)
uvicorn main:app --reload
```

Then trigger a run:
```bash
curl -X POST http://localhost:8000/run
# → {"run_id": "a1b2c3d4", "status": "queued"}

curl http://localhost:8000/status/a1b2c3d4
# → {"status": "complete", "high_risk": 6, "total_cost_usd": 0.59}

open http://localhost:8000/report/latest
```

## API Endpoints

```
POST /run                      → 202 + run_id (triggers graph async)
GET  /status/{run_id}          → status + cost + risk summary
GET  /customers                → all 20 customers with latest health scores
GET  /customers/{id}/history   → score history for one customer
GET  /report/latest            → HTML digest of at-risk accounts
```

## Signal Collection (Agentic Tool Use)

The signal collector uses a real Claude tool-use loop. Claude receives a `execute_sql` tool and autonomously decides which queries to run to gather:

- Login frequency (30-day window)
- Feature adoption metrics
- API call volume
- Support ticket count
- Payment failure history
- Days since last activity

Claude runs up to 8 SQL queries per customer, reasoning about which metrics it needs, until it has enough data to produce a complete signal JSON.

## Change Detection

On every run, each customer's new health score is compared against the last stored score in `health_scores`. Outreach is only triggered if:
- `abs(score_delta) > 10` — meaningful score change
- `risk_escalated = True` — risk level went up (e.g. MEDIUM → HIGH)

This prevents duplicate outreach on every run for stable at-risk customers.

## Environment Variables

```
ANTHROPIC_API_KEY=sk-ant-...
MAX_PARALLEL_CUSTOMERS=2      # semaphore limit — raise if you have higher API quota
```

## Known Limitations

- SQLite: use PostgreSQL for truly concurrent runs in production
- No actual email sending — outreach is drafted and logged only
- No auth on FastAPI endpoints (demo)
- `MAX_PARALLEL_CUSTOMERS=2` is conservative for the default Claude API rate limit (8k output tokens/min)
