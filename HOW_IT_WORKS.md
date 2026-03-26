# How the Churn Agent Works

A complete guide to understanding, running, and modifying this system.

---

## Table of Contents

1. [What it does in plain English](#1-what-it-does-in-plain-english)
2. [Tools and libraries used](#2-tools-and-libraries-used)
3. [File structure explained](#3-file-structure-explained)
4. [The database](#4-the-database)
5. [How the graph flows](#5-how-the-graph-flows)
6. [Each agent explained](#6-each-agent-explained)
7. [State — how data flows between agents](#7-state--how-data-flows-between-agents)
8. [Parallel processing — how it works](#8-parallel-processing--how-it-works)
9. [Cost — where the money goes](#9-cost--where-the-money-goes)
10. [How to modify common things](#10-how-to-modify-common-things)

---

## 1. What it does in plain English

Every time you trigger a run (via API or on a schedule):

1. It loads all customers from the database (3 in dev mode, all 20 in production)
2. For each customer **in parallel**, Claude queries the database to collect behaviour signals (logins, feature use, payment failures, etc.)
3. Claude scores each customer's health 0–100 and assigns HIGH / MEDIUM / LOW risk
4. It compares the new score against the last stored score — if nothing changed meaningfully, it does nothing
5. For customers whose score changed or risk escalated, it takes action
6. HIGH risk customers get a personalised outreach email drafted by Claude
7. **The agent pauses** — it presents a review UI where a human can approve, edit, or skip each draft
8. After the human submits their decisions, the agent resumes and logs only the approved outreach
9. A report is generated and a run summary is printed

The key point: it **remembers** history and **includes humans in the loop**. AI handles the detection and drafting. Humans retain control over what actually gets sent.

---

## 2. Tools and Libraries Used

### Core AI

| Library | What it does in this project |
|---|---|
| `anthropic` | The Claude API client. Used to send prompts and receive responses. All 3 agents use this. |
| `langgraph` | Orchestrates the agents as a graph. Controls which agent runs when, handles parallel execution. |

### API & Server

| Library | What it does |
|---|---|
| `fastapi` | The REST API framework. Provides POST /run, GET /status, GET /review, POST /resume, GET /customers, GET /report/latest |
| `uvicorn` | The server that runs FastAPI. Think of it as the engine that powers the API. |
| `pydantic` | Data validation. FastAPI uses it to validate request/response shapes. |

### Database

| Library | What it does |
|---|---|
| `sqlite3` | Built into Python. Stores customers, events, health scores, outreach logs. No external DB needed. |

### Templating & Reports

| Library | What it does |
|---|---|
| `jinja2` | HTML template engine. Fills in the report template with real data from the run. |

### Utilities

| Library | What it does |
|---|---|
| `python-dotenv` | Loads your `.env` file so the code can read `ANTHROPIC_API_KEY` etc. |
| `apscheduler` | Can schedule the agent to run automatically (e.g. daily at 9am). Not active by default. |
| `langfuse` | Observability — tracks every Claude call, token usage, and cost. Optional. |
| `langsmith` | Live graph visualisation — shows waterfall of every node executing in real time, parallel branches, full prompt/response per span. Free tier: 5,000 traces/month. Dashboard at smith.langchain.com |

---

## 3. File Structure Explained

```
churn-agent/
│
├── main.py                  ← Entry point. FastAPI app + endpoints.
│
├── .env                     ← Your API keys and config (never commit this)
├── .env.example             ← Template showing what keys are needed
├── requirements.txt         ← All Python packages to install
│
├── db/
│   ├── schema.sql           ← Defines the 4 database tables
│   ├── seed.py              ← Creates 20 demo customers with realistic data
│   └── database.py          ← Thread-safe SQLite connection pool
│
├── models/
│   └── state.py             ← Defines CustomerState and OrchestratorState (the data shapes)
│
├── tools/
│   ├── sql_tool.py          ← Gives Claude the ability to run SQL queries
│   └── rate_limiter.py      ← Prevents too many parallel API calls (avoids 429 errors)
│
├── agents/
│   ├── signal_collector.py  ← Agent 1: collects behaviour signals via SQL tool loop
│   ├── health_scorer.py     ← Agent 2: scores health 0–100 and assigns risk level
│   ├── outreach_drafter.py  ← Agent 3: writes personalised email for HIGH risk customers
│   └── report_agent.py      ← Generates HTML and Markdown reports
│
├── graph/
│   ├── orchestrator.py      ← Builds the LangGraph graph + MemorySaver checkpointer
│   └── nodes.py             ← Non-AI nodes: change_detector, action_router, approval_gate, notifier
│
├── reports/
│   └── templates/
│       └── digest.html.jinja2   ← HTML report template
│
└── data/
    ├── churn.db             ← The SQLite database (created when you run seed.py)
    └── reports/             ← Generated HTML and Markdown reports saved here
```

---

## 4. The Database

Four tables:

```sql
-- The customers you monitor
customers (id, name, company, plan, mrr, signup_date, csm_name)

-- Raw events (logins, feature use, payments, support tickets)
events (id, customer_id, event_type, timestamp)

-- Health scores written after every run — this is the agent's memory
health_scores (id, customer_id, score, risk_level, reason, checked_at)

-- Outreach emails drafted by Claude
outreach_log (id, customer_id, subject, draft, created_at, sent_at)
```

The `health_scores` table is the most important. Every run writes a new row per customer. The change detector reads the most recent row to compare against the new score. This is how the agent has memory across runs.

---

## 5. How the Graph Flows

LangGraph builds a directed graph of nodes. Each node is a function. Edges define which node runs next.

```
START
  │
  ▼
[orchestrator_node]         ← Loads customers from DB (3 in dev, 20 in prod)
  │
  │  Send API (parallel)
  ├──────────────────────────────────────────────────┐
  ▼                                                  ▼
[process_customer] × N     ← Each customer runs simultaneously
  │                          signal_collector → health_scorer → returns result
  └──────────────────────────────────────────────────┘
  │  (all results merge into one list)
  ▼
[aggregate_results]        ← Totals up tokens and cost
  │
  ▼
[change_detector]          ← Compares each score vs last stored score in DB
  │                          Writes new scores to DB
  │                          Categorises into high / medium / low lists
  ▼
[action_router]            ← Pass-through. Routing happens in the edge below.
  │
  │  Send API (parallel, HIGH risk only)
  ├──────────────────────────────────────────────────┐
  ▼                                                  ▼
[process_outreach] × M     ← Each HIGH risk customer gets an email drafted
  └──────────────────────────────────────────────────┘
  │  (outreach results merge back in)
  ▼
[approval_gate] ⏸          ← INTERRUPT — graph pauses here
  │                          Human reviews drafts at GET /review/{run_id}
  │                          Human submits decisions via POST /resume/{run_id}
  │                          Graph resumes with approved_ids
  ▼
[merge_outreach]           ← Logs only human-approved drafts to outreach_log
  │
  ▼
[report_agent]             ← Generates HTML + Markdown report files
  │
  ▼
[notifier]                 ← Prints run summary to console
  │
  ▼
END
```

**Key concept — two levels of parallelism + one human checkpoint:**
- Level 1: all customers processed at the same time (Send API)
- Level 2: all HIGH risk outreach emails drafted at the same time (Send API)
- Checkpoint: graph suspends at `approval_gate`, resumes only after human approval

All three use LangGraph primitives — `Send` API for fan-out, `interrupt()` for HITL, `MemorySaver` checkpointer to persist state across the pause.

---

## 6. Each Agent Explained

### Agent 1 — Signal Collector (`agents/signal_collector.py`)

**Model:** Claude Haiku (cheap — just tool calling, no reasoning needed)

This agent uses a **tool-use loop**. Claude is given one tool: `execute_sql`. It decides which SQL queries to run, runs them, reads the results, then decides if it needs more data. It keeps going until it has all 9 signals.

```
Claude → "I need login count" → runs SQL → gets result
Claude → "I need payment failures" → runs SQL → gets result
Claude → "I have everything" → returns final JSON
```

The loop runs up to 8 iterations per customer. The final output is a JSON object like:
```json
{
  "login_count_30d": 0,
  "feature_use_count_30d": 0,
  "payment_failed_30d": 2,
  "days_since_last_login": 45,
  ...
}
```

**To modify:** Change `MAX_ITERATIONS` (line 11) to allow more/fewer SQL queries. Change the `SYSTEM` prompt to collect different signals.

---

### Agent 2 — Health Scorer (`agents/health_scorer.py`)

**Model:** Claude Sonnet (needs reasoning to classify risk correctly)

Single Claude call. Receives the customer info + all 9 signals. Returns a structured JSON:
```json
{
  "health_score": 4,
  "risk_level": "HIGH",
  "churn_reason": "No logins for 45 days and 2 payment failures",
  "score_confidence": "HIGH"
}
```

The scoring guide in the system prompt:
- **80–100** = LOW risk (healthy)
- **50–79** = MEDIUM risk (declining)
- **0–49** = HIGH risk (critical)

**To modify:** Edit the `SYSTEM` prompt in the file to change scoring thresholds or add new risk factors.

---

### Agent 3 — Outreach Drafter (`agents/outreach_drafter.py`)

**Model:** Claude Sonnet for the email body, Claude Haiku for the subject line

Only runs for HIGH risk customers. Makes two API calls:
1. Sonnet writes a warm, personalised 3–4 paragraph email referencing the specific churn reason
2. Haiku writes a short subject line (max 10 words)

Output is stored in `outreach_log` table and attached to the customer result.

**To modify:** Edit the `SYSTEM` prompt to change the email tone or structure. Change `max_tokens=600` to allow longer emails.

---

### Report Agent (`agents/report_agent.py`)

Not a Claude agent — pure Python. Reads the final state and:
1. Fills in the Jinja2 HTML template → saves `data/reports/latest.html`
2. Builds a Markdown string directly in Python → saves `data/reports/latest.md`

**To modify:** Edit `reports/templates/digest.html.jinja2` for the HTML report. Edit `_build_markdown()` in `report_agent.py` for the Markdown format.

---

### Approval Gate — Human-in-the-Loop (`graph/nodes.py`)

Not a Claude agent — a LangGraph interrupt point. After all outreach emails are drafted, this node calls `interrupt()` to suspend the graph mid-execution.

```python
decisions = interrupt({"pending_outreach": pending})
approved_ids = set(decisions.get("approved_ids", []))
```

The graph state is persisted to `MemorySaver` (the checkpointer). The FastAPI layer then:
- Returns status `awaiting_approval` with the pending drafts
- Serves a review UI at `GET /review/{run_id}`
- Accepts `POST /resume/{run_id}` with `{"approved_ids": [...]}` to resume

When resumed, the graph picks up exactly where it left off — no data is re-processed. Only approved customers are passed to `merge_outreach_node`.

If there are no HIGH risk customers, the gate passes through immediately with no interrupt.

---

### Change Detector (`graph/nodes.py`)

Not a Claude agent — pure Python logic. For each customer:
1. Queries `health_scores` table for the last stored score
2. Calculates `score_delta = new_score - old_score`
3. Checks if risk level went up (e.g. MEDIUM → HIGH)
4. Sets `needs_action = True` only if `abs(score_delta) > 10` OR `risk_escalated`

This is what prevents the agent from spamming outreach every single run.

**To modify:** Change the `> 10` threshold on line 34 of `nodes.py` to be more or less sensitive.

---

## 7. State — How Data Flows Between Agents

Every agent receives **state** and returns a **dict of updates**.

There are two state types:

### CustomerState
Used inside each customer's processing branch. Contains everything about one customer:
- Identity: `customer_id`, `company`, `plan`, `mrr`
- Signals: the 9 metrics collected by signal_collector
- Scores: `health_score`, `risk_level`, `churn_reason`
- Change: `score_delta`, `risk_escalated`, `needs_action`
- Outreach: `outreach_draft`, `outreach_subject`
- Tracking: `input_tokens`, `output_tokens`, `cost_usd`

### OrchestratorState
The top-level state shared across the whole run:
- `customer_results` — list of all CustomerState results (has a special reducer, see below)
- `high_risk_customers`, `medium_risk_customers`, `low_risk_customers` — categorised lists
- `total_cost_usd`, `total_tokens_used` — run totals
- `run_id`, `status`, `started_at`, `completed_at`

**Critical rule:** Sequential nodes must only return the keys they actually change. If a node returns `{**state, "foo": "bar"}`, it spreads the entire state including `customer_results`, and the reducer will append it to itself, duplicating the list. Always return only what changed:

```python
# WRONG — doubles customer_results on every run
return {**state, "status": "complete"}

# CORRECT — only return what you changed
return {"status": "complete"}
```

### The `customer_results` Reducer

```python
customer_results: Annotated[list, operator.add]
```

This tells LangGraph: "when multiple parallel branches all write to `customer_results`, **add** the lists together instead of overwriting." Without this, 20 parallel branches would fight over who writes last and you'd only get 1 result.

---

## 8. Parallel Processing — How It Works

LangGraph's `Send` API lets you spawn multiple branches that run at the same time.

### How orchestrator_node fans out

```python
def orchestrator_node(state: OrchestratorState) -> list[Send]:
    rows = execute_query("SELECT * FROM customers")
    return [Send("process_customer", build_customer_state(row)) for row in rows]
```

This returns 20 `Send` objects. LangGraph spawns 20 parallel threads, one per customer. Each runs `process_customer` independently.

### How they merge back

All 20 threads write `{"customer_results": [their_result]}`. The `operator.add` reducer concatenates all 20 lists into one. By the time `aggregate_results` runs, `state["customer_results"]` has all 20 results.

### Rate limiting

20 parallel threads × each making multiple Claude API calls = too many requests. The rate limiter in `tools/rate_limiter.py` uses a semaphore to allow only `MAX_PARALLEL_CUSTOMERS` (default: 2) threads to call the API at the same time:

```python
_api_semaphore = threading.Semaphore(2)

def with_rate_limit(fn, *args, **kwargs):
    with _api_semaphore:      # only 2 threads can be here at once
        return fn(*args, **kwargs)
```

If you increase your Claude API quota, raise `MAX_PARALLEL_CUSTOMERS` in `.env` to go faster.

---

## 9. Cost — Where the Money Goes

For a run of 20 customers:

| Agent | Model | Cost driver | ~Cost |
|---|---|---|---|
| signal_collector × 20 | Haiku | Agentic loop (up to 8 calls, history grows each iteration) | ~$0.08 |
| health_scorer × 20 | Sonnet | Single call per customer | ~$0.05 |
| outreach_drafter × 6 | Sonnet + Haiku | One email per HIGH risk customer | ~$0.03 |
| **Total** | | | **~$0.10–0.16** |

**Why signal_collector was expensive before:** It was using Sonnet ($3/$15 per M tokens). Switching to Haiku ($0.80/$4 per M tokens) cut the cost 3–4×. The task is pure tool-calling — no reasoning needed — so Haiku handles it perfectly.

**Pricing reference:**
- Haiku 4.5: $0.80 input / $4.00 output per million tokens
- Sonnet 4.6: $3.00 input / $15.00 output per million tokens

---

## 10. How to Modify Common Things

### Add a new signal (e.g. NPS score)
1. Add the column/data to your `events` table
2. Update the `SYSTEM` prompt in `signal_collector.py` to ask Claude to collect it
3. Add the field to `CustomerSignals` in `models/state.py`
4. Update the health scorer prompt to consider it

### Change the risk thresholds
Edit the `SYSTEM` prompt in `agents/health_scorer.py`:
```
- 80-100: LOW risk
- 50-79: MEDIUM risk   ← change these numbers
- 0-49: HIGH risk
```

### Make change detection more sensitive
In `graph/nodes.py` line 34, lower the threshold:
```python
needs_action = abs(score_delta) > 5  # was 10
```

### Add more customers
Edit `db/seed.py` — add rows to the `customers` list and add events for them.

### Change the outreach email style
Edit the `SYSTEM` prompt in `agents/outreach_drafter.py`. Current instructions: warm, 3–4 paragraphs, human tone. You could change it to be more urgent, add a discount offer, etc.

### Run it on a schedule (daily)
Uncomment or configure `scheduler/jobs.py` — it uses APScheduler to call `POST /run` at a set time. Example for daily at 9am:
```python
scheduler.add_job(daily_churn_check, 'cron', hour=9, minute=0)
```

### Connect to a real database
Replace SQLite with PostgreSQL. Update `db/database.py` to use `psycopg2` instead of `sqlite3`. The rest of the code doesn't change — only the connection layer.

### Add real email sending
In `graph/nodes.py`, update `notifier_node` to send via SMTP or SendGrid using the `outreach_draft` and `outreach_subject` from each HIGH risk customer in `state["customer_results"]`.
