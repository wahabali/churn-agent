import os
import anthropic
from dotenv import load_dotenv
from models.state import CustomerState

load_dotenv()

SYSTEM = """You are a customer success manager writing a personalised outreach email.
The email should:
- Be warm and helpful, not salesy or alarming
- Reference the specific issue (payment failure, inactivity, etc.)
- Offer concrete help (call, resources, discount if relevant)
- Be concise — 3-4 short paragraphs max
- Sound human, not like a template

Return ONLY the email body (no subject line, no headers). Start with the greeting."""


def outreach_drafter_node(state: CustomerState) -> dict:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = (
        f"Write an outreach email for {state['customer_name']} at {state['company']}.\n"
        f"Plan: {state['plan']} | MRR: ${state['mrr']}/month\n"
        f"Churn reason: {state['churn_reason']}\n"
        f"CSM name (sender): {state['csm_name']}\n"
        f"Score delta: {state.get('score_delta', 'N/A')} points\n\n"
        "Write a personalised email to re-engage this customer."
    )

    subject_prompt = (
        f"Write a short, friendly email subject line (max 10 words) for a customer success outreach to "
        f"{state['customer_name']} at {state['company']} regarding: {state['churn_reason']}. "
        "Return ONLY the subject line, nothing else."
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    subject_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=50,
        messages=[{"role": "user", "content": subject_prompt}],
    )

    draft = response.content[0].text.strip()
    subject = subject_response.content[0].text.strip().strip('"')

    cost = (response.usage.input_tokens * 3 + response.usage.output_tokens * 15) / 1_000_000

    return {
        **state,
        "outreach_draft": draft,
        "outreach_subject": subject,
        "cost_usd": state.get("cost_usd", 0.0) + cost,
        "processing_status": "outreach_drafted",
    }
