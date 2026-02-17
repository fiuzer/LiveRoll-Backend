import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Giveaway, Participant, Platform, Winner

logger = logging.getLogger(__name__)


async def add_or_refresh_participant(
    db: AsyncSession,
    giveaway_id: int,
    platform: Platform,
    platform_user_id: str,
    display_name: str,
) -> tuple[Participant, bool]:
    result = await db.execute(
        select(Participant).where(
            Participant.giveaway_id == giveaway_id,
            Participant.platform == platform,
            Participant.platform_user_id == platform_user_id,
        )
    )
    participant = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if participant:
        participant.display_name = display_name
        participant.last_seen = now
        return participant, False

    participant = Participant(
        giveaway_id=giveaway_id,
        platform=platform,
        platform_user_id=platform_user_id,
        display_name=display_name,
        first_seen=now,
        last_seen=now,
    )
    db.add(participant)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        result = await db.execute(
            select(Participant).where(
                Participant.giveaway_id == giveaway_id,
                Participant.platform == platform,
                Participant.platform_user_id == platform_user_id,
            )
        )
        participant = result.scalar_one()
        participant.display_name = display_name
        participant.last_seen = now
        return participant, False
    return participant, True


async def draw_winner(db: AsyncSession, giveaway: Giveaway) -> Winner | None:
    result = await db.execute(select(Participant).where(Participant.giveaway_id == giveaway.id))
    participants = result.scalars().all()
    if not participants:
        return None

    picked = secrets.choice(participants)
    winner = Winner(
        giveaway_id=giveaway.id,
        platform=picked.platform,
        platform_user_id=picked.platform_user_id,
        display_name=picked.display_name,
    )
    db.add(winner)
    await db.flush()
    return winner


async def clear_participants(db: AsyncSession, giveaway_id: int) -> int:
    result = await db.execute(select(Participant).where(Participant.giveaway_id == giveaway_id))
    rows = result.scalars().all()
    count = len(rows)
    for row in rows:
        await db.delete(row)
    return count


def normalize_command(command: str) -> str:
    cmd = command.strip().split()[0]
    if not cmd.startswith('!'):
        cmd = f'!{cmd}'
    return cmd.lower()
