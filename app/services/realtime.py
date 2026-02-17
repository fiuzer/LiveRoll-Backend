import json
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Giveaway, Participant, Winner

EVENT_CHANNEL = 'giveaway:events'
CONTROL_CHANNEL = 'giveaway:control'


async def build_giveaway_state(db: AsyncSession, giveaway_id: int) -> dict:
    giveaway_result = await db.execute(select(Giveaway).where(Giveaway.id == giveaway_id))
    giveaway = giveaway_result.scalar_one_or_none()
    if not giveaway:
        return {}

    participants_count = await db.scalar(
        select(func.count(Participant.id)).where(Participant.giveaway_id == giveaway_id)
    )
    participants_result = await db.execute(
        select(Participant.display_name)
        .where(Participant.giveaway_id == giveaway_id)
        .order_by(Participant.first_seen.asc())
    )
    participant_names = [row[0] for row in participants_result.all()]
    latest_participant = (
        await db.execute(
            select(Participant.display_name)
            .where(Participant.giveaway_id == giveaway_id)
            .order_by(Participant.last_seen.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    winner_result = await db.execute(
        select(Winner).where(Winner.giveaway_id == giveaway_id).order_by(Winner.drawn_at.desc()).limit(1)
    )
    last_winner = winner_result.scalar_one_or_none()

    return {
        'giveaway_id': giveaway.id,
        'name': giveaway.name,
        'command': giveaway.command,
        'is_open': giveaway.is_open,
        'participants_count': int(participants_count or 0),
        'participant_names': participant_names,
        'latest_participant': latest_participant,
        'ticker_message': giveaway.ticker_message,
        'last_winner': (
            {
                'display_name': last_winner.display_name,
                'platform': last_winner.platform.value,
                'drawn_at': last_winner.drawn_at.isoformat(),
            }
            if last_winner
            else None
        ),
        'ts': datetime.utcnow().isoformat(),
    }


async def publish_state(redis: Redis, state: dict) -> None:
    await redis.publish(EVENT_CHANNEL, json.dumps({'type': 'state', 'state': state}))


async def publish_draw_started(redis: Redis, giveaway_id: int, winner_name: str, duration_ms: int) -> None:
    await redis.publish(
        EVENT_CHANNEL,
        json.dumps(
            {
                'type': 'draw_started',
                'giveaway_id': giveaway_id,
                'winner_name': winner_name,
                'duration_ms': duration_ms,
            }
        ),
    )


async def publish_control(redis: Redis, action: str, giveaway_id: int, user_id: int) -> None:
    await redis.publish(
        CONTROL_CHANNEL,
        json.dumps({'type': action, 'giveaway_id': giveaway_id, 'user_id': user_id}),
    )
