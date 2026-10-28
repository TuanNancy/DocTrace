"""Append-only, content-free audit events in the caller's SQL transaction."""
import json
from uuid import UUID

from sqlalchemy import text

from app.core.observability import current_request_id, valid_request_id

ACTIONS = {
    "workspace.created": ("workspace", {"kind"}),
    "workspace.member_added": ("member", set()),
    "workspace.member_removed": ("member", set()),
    "workspace.archived": ("workspace", set()),
    "workspace.restored": ("workspace", set()),
    "workspace.plan_changed": ("workspace", {"from_plan", "to_plan"}),
    "workspace.purge_started": ("workspace", {"documents"}),
    "workspace.purge_completed": ("workspace", set()),
    "document.retry_requested": ("document", {"kind"}),
    "document.retry_accepted": ("document", {"kind", "job_id"}),
}


def write_audit(session, actor: str, workspace_id: str, action: str, target_id: str,
                **metadata) -> str:
    target_type, fields = ACTIONS[action]
    if set(metadata) - fields:
        raise ValueError("Unregistered audit metadata")
    request_id = current_request_id()
    return session.execute(text("""
        INSERT INTO doctrace.audit_events
            (actor_user_id, workspace_id, action, target_type, target_id, metadata, request_id)
        VALUES (CAST(:actor AS uuid), CAST(:workspace AS uuid), :action, :type, :target,
                CAST(:metadata AS jsonb), :request_id)
        RETURNING id::text
    """), {
        "actor": str(UUID(str(actor))), "workspace": str(UUID(str(workspace_id))),
        "action": action, "type": target_type, "target": str(UUID(str(target_id))),
        "metadata": json.dumps(metadata), "request_id": request_id if valid_request_id(request_id) else None,
    }).scalar_one()
