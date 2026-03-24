"""
Seed 20 realistic SaaS customers with varying churn risk signals.
- 3 HIGH risk: payment failed, no login 30+ days, dropped usage
- 5 MEDIUM risk: declining usage, support tickets
- 12 LOW risk: healthy engagement
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import random
import uuid
from db.database import init_db, execute_write, execute_query

random.seed(42)

CUSTOMERS = [
    # HIGH RISK — 3 customers
    {"id": "c001", "name": "Sarah Chen",    "company": "Nexus Analytics",    "plan": "enterprise", "mrr": 2400, "csm": "Marco Weber"},
    {"id": "c002", "name": "James Miller",  "company": "FinEdge GmbH",       "plan": "growth",     "mrr": 890,  "csm": "Anna Schmidt"},
    {"id": "c003", "name": "Priya Sharma",  "company": "CloudBridge AG",     "plan": "growth",     "mrr": 650,  "csm": "Marco Weber"},
    # MEDIUM RISK — 5 customers
    {"id": "c004", "name": "Tom Fischer",   "company": "DataPulse SE",       "plan": "growth",     "mrr": 450,  "csm": "Anna Schmidt"},
    {"id": "c005", "name": "Lisa Wagner",   "company": "InsightFlow GmbH",   "plan": "starter",    "mrr": 190,  "csm": "Marco Weber"},
    {"id": "c006", "name": "Carlos Ruiz",   "company": "Alphatech SRL",      "plan": "growth",     "mrr": 720,  "csm": "Anna Schmidt"},
    {"id": "c007", "name": "Nina Keller",   "company": "Orbify Labs",        "plan": "starter",    "mrr": 150,  "csm": "Marco Weber"},
    {"id": "c008", "name": "David Park",    "company": "StreamVault KG",     "plan": "growth",     "mrr": 540,  "csm": "Anna Schmidt"},
    # LOW RISK — 12 customers
    {"id": "c009", "name": "Emma Bauer",    "company": "Velox Systems",      "plan": "enterprise", "mrr": 3100, "csm": "Marco Weber"},
    {"id": "c010", "name": "Felix Braun",   "company": "Quantico GmbH",      "plan": "growth",     "mrr": 780,  "csm": "Anna Schmidt"},
    {"id": "c011", "name": "Mia Hoffmann",  "company": "Strato Digital",     "plan": "growth",     "mrr": 620,  "csm": "Marco Weber"},
    {"id": "c012", "name": "Luca Ricci",    "company": "NovaMesh SpA",       "plan": "enterprise", "mrr": 2800, "csm": "Anna Schmidt"},
    {"id": "c013", "name": "Sophie Martin", "company": "Axiom Cloud",        "plan": "starter",    "mrr": 200,  "csm": "Marco Weber"},
    {"id": "c014", "name": "Omar Hassan",   "company": "DataForge Ltd",      "plan": "growth",     "mrr": 910,  "csm": "Anna Schmidt"},
    {"id": "c015", "name": "Julia Neumann", "company": "Brightbase GmbH",    "plan": "growth",     "mrr": 560,  "csm": "Marco Weber"},
    {"id": "c016", "name": "Kai Müller",    "company": "Syncronix AG",       "plan": "enterprise", "mrr": 1950, "csm": "Anna Schmidt"},
    {"id": "c017", "name": "Hana Sato",     "company": "Luminos K.K.",       "plan": "growth",     "mrr": 680,  "csm": "Marco Weber"},
    {"id": "c018", "name": "Ben Schulz",    "company": "Corelink GmbH",      "plan": "starter",    "mrr": 180,  "csm": "Anna Schmidt"},
    {"id": "c019", "name": "Ana Costa",     "company": "Nexio Lda",          "plan": "growth",     "mrr": 490,  "csm": "Marco Weber"},
    {"id": "c020", "name": "Max Weber",     "company": "Stackwise GmbH",     "plan": "enterprise", "mrr": 2200, "csm": "Anna Schmidt"},
]

now = datetime.utcnow()

def signup_date(days_ago):
    return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")

def ts(days_ago, hours=0):
    return (now - timedelta(days=days_ago, hours=hours)).isoformat()

def seed_events(customer_id, profile):
    events = []
    if profile == "high_no_login":
        # Last login was 45 days ago, no feature use, payment failed
        events += [("login", ts(45)), ("login", ts(60)), ("feature_use", ts(50))]
        events += [("payment_failed", ts(5)), ("payment_failed", ts(2))]
        events += [("support_ticket", ts(10)), ("support_ticket", ts(7))]
    elif profile == "high_dropped":
        # Was active, completely dropped off 35 days ago
        for d in range(35, 90, 3):
            events.append(("login", ts(d)))
            events.append(("feature_use", ts(d, 1)))
            events.append(("api_call", ts(d, 2)))
        events += [("support_ticket", ts(38)), ("support_ticket", ts(36))]
    elif profile == "high_payment":
        # Active but multiple payment failures
        for d in range(0, 30, 5):
            events.append(("login", ts(d)))
        events += [("payment_failed", ts(1)), ("payment_failed", ts(8)), ("payment_failed", ts(15))]
        events += [("support_ticket", ts(3)), ("support_ticket", ts(10))]
    elif profile == "medium_declining":
        # Was active, now declining — half the logins vs 60 days ago
        for d in range(30, 60, 4):
            events.append(("login", ts(d)))
            events.append(("feature_use", ts(d)))
            events.append(("api_call", ts(d)))
        for d in range(0, 30, 8):
            events.append(("login", ts(d)))
        events += [("support_ticket", ts(5))]
    elif profile == "medium_support":
        # Regular logins but many support tickets
        for d in range(0, 30, 3):
            events.append(("login", ts(d)))
        events += [("support_ticket", ts(d)) for d in [2, 5, 9, 14, 20]]
        for d in range(0, 30, 7):
            events.append(("feature_use", ts(d)))
    elif profile == "low":
        # Healthy — regular logins, feature use, API calls
        for d in range(0, 30, 2):
            events.append(("login", ts(d)))
            events.append(("feature_use", ts(d, 1)))
        for d in range(0, 30, 1):
            events.append(("api_call", ts(d, random.randint(0, 5))))
        for d in range(0, 30, 6):
            events.append(("login", ts(d, 12)))

    for event_type, timestamp in events:
        execute_write(
            "INSERT INTO events (customer_id, event_type, timestamp) VALUES (?, ?, ?)",
            (customer_id, event_type, timestamp)
        )

PROFILES = {
    "c001": ("high_no_login",   signup_date(400)),
    "c002": ("high_dropped",    signup_date(300)),
    "c003": ("high_payment",    signup_date(200)),
    "c004": ("medium_declining",signup_date(250)),
    "c005": ("medium_support",  signup_date(180)),
    "c006": ("medium_declining",signup_date(220)),
    "c007": ("medium_support",  signup_date(150)),
    "c008": ("medium_declining",signup_date(190)),
}

def main():
    init_db()
    print("Seeding customers...")
    for c in CUSTOMERS:
        execute_write(
            "INSERT OR REPLACE INTO customers (id, name, company, plan, mrr, signup_date, csm_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (c["id"], c["name"], c["company"], c["plan"], c["mrr"],
             PROFILES.get(c["id"], ("low", signup_date(random.randint(100, 500))))[1],
             c["csm"])
        )
        profile = PROFILES.get(c["id"], ("low", None))[0]
        seed_events(c["id"], profile)
        print(f"  {c['id']} — {c['company']} [{profile}]")
    print(f"\nSeeded {len(CUSTOMERS)} customers into churn.db")

if __name__ == "__main__":
    main()
