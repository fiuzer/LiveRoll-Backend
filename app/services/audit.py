from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def add_audit_log(
    db: AsyncSession,
    user_id: int,
    action: str,
    giveaway_id: int | None = None,
    payload: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            giveaway_id=giveaway_id,
            action=action,
            payload_json=payload or {},
        )
    )
