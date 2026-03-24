from typing import TypedDict, Optional, Annotated
import operator


class CustomerSignals(TypedDict):
    login_count_30d: int
    feature_use_count_30d: int
    api_call_count_30d: int
    support_tickets_30d: int
    payment_failed_30d: int
    days_since_last_login: int
    days_since_last_feature_use: int
    unique_features_used: int
    avg_logins_per_week: float


class PreviousHealthRecord(TypedDict):
    score: int
    risk_level: str
    reason: str
    checked_at: str


class CustomerState(TypedDict):
    # Identity
    customer_id: str
    customer_name: str
    company: str
    plan: str
    mrr: float
    csm_name: str
    signup_date: str
    # Signal collection
    signals: Optional[CustomerSignals]
    # Scoring
    health_score: Optional[int]
    risk_level: Optional[str]
    churn_reason: Optional[str]
    # Change detection
    previous_record: Optional[PreviousHealthRecord]
    score_delta: Optional[int]
    risk_escalated: Optional[bool]
    needs_action: Optional[bool]
    # Outreach
    outreach_draft: Optional[str]
    outreach_subject: Optional[str]
    # Tracking
    tool_calls_made: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    error: Optional[str]
    processing_status: str


class OrchestratorState(TypedDict):
    run_id: str
    triggered_by: str
    started_at: str
    completed_at: Optional[str]
    customer_results: Annotated[list, operator.add]
    changed_customers: Optional[list]
    high_risk_customers: Optional[list]
    medium_risk_customers: Optional[list]
    low_risk_customers: Optional[list]
    html_report: Optional[str]
    report_path: Optional[str]
    total_tokens_used: int
    total_cost_usd: float
    errors_encountered: int
    status: str
    langfuse_trace_id: Optional[str]
