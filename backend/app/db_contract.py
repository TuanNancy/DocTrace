"""Runtime's minimum schema shape and least-privilege table access.

Readiness checks shape as well as an Alembic stamp, rather than requiring exact
head equality: additive migrations must remain compatible with image rollback.
New tables/columns used by runtime code must be added here with their migration.
"""

RUNTIME_ROLE = "doctrace_app"
# Hosted Supabase cannot grant custom roles USAGE on auth. Runtime can only
# invoke this private, migration-owned boolean lookup, never read Auth rows.
AUTH_LOOKUP_FUNCTION = "doctrace.auth_user_exists(uuid)"
TABLE_COLUMNS = {
    "alembic_version": "version_num",
    "workspaces": "id name kind plan status created_by personal_owner_user_id created_at updated_at archived_at archived_by purge_started_at",
    "workspace_members": "workspace_id user_id role status joined_at removed_at",
    "platform_admins": "user_id created_at created_by",
    "profiles": "user_id email display_name created_at updated_at",
    "plan_limits": "plan metric limit_value",
    "audit_events": "id actor_user_id workspace_id action target_type target_id metadata request_id created_at",
    "conversations": "id workspace_id user_id doc_id created_at updated_at document_deleted_at purge_after",
    "messages": "id conversation_id role content sources index_id status created_at updated_at",
    "chat_requests": "id request_id workspace_id user_id conversation_id doc_id status created_at completed_at error_code latency_ms first_token_ms",
    "document_failures": "id workspace_id owner_user_id doc_id job_id attempt kind error_code request_id created_at",
    "workspace_purges": "workspace_id actor_user_id request_id status started_at updated_at completed_at",
    "workspace_purge_documents": "workspace_id doc_id owner_user_id status updated_at",
    "provider_calls": "id request_id workspace_id user_id doc_id job_id kind provider model generation_id prompt_tokens completion_tokens cached_tokens reasoning_tokens cost_micros cost_status latency_ms status error_code raw_usage created_at",
    "usage_counters": "workspace_id period_start metric used updated_at",
}
TABLE_PRIVILEGES = {
    name: ("SELECT",) for name in TABLE_COLUMNS
}
for _table in ("workspaces", "workspace_members", "profiles", "conversations", "messages", "workspace_purge_documents"):
    TABLE_PRIVILEGES[_table] = ("SELECT", "INSERT", "UPDATE", "DELETE")
for _table in ("chat_requests", "provider_calls", "usage_counters", "workspace_purges"):
    TABLE_PRIVILEGES[_table] = ("SELECT", "INSERT", "UPDATE")
TABLE_PRIVILEGES["audit_events"] = ("SELECT", "INSERT")
TABLE_PRIVILEGES["document_failures"] = ("SELECT", "INSERT")
