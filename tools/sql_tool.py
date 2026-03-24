import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.database import execute_query

SQL_TOOL = {
    "name": "execute_sql",
    "description": (
        "Execute a read-only SELECT query against the customer database. "
        "Tables available: "
        "customers(id, name, company, plan, mrr, signup_date, csm_name), "
        "events(id, customer_id, event_type, timestamp), "
        "health_scores(id, customer_id, score, risk_level, reason, checked_at), "
        "outreach_log(id, customer_id, subject, draft, created_at, sent_at). "
        "Only SELECT statements are permitted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A valid SQLite SELECT statement."
            }
        },
        "required": ["query"]
    }
}


def safe_execute_sql(query: str) -> str:
    """Execute a SELECT-only query and return results as JSON string."""
    stripped = query.strip().upper()
    if not stripped.startswith("SELECT"):
        return json.dumps({"error": "Only SELECT statements are allowed."})
    try:
        rows = execute_query(query)
        return json.dumps(rows[:100])  # cap at 100 rows
    except Exception as e:
        return json.dumps({"error": str(e)})
