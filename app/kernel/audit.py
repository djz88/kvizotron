from app.kernel.models import AuditEvent


def record(
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
) -> None:
    """Store an audited operation. Details must not contain personal data beyond the minimum."""
    AuditEvent.objects.create(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=details or {},
    )
