import pytest
from sqlalchemy import select

from app.models import Giveaway, Participant, Platform, User
from app.services.giveaway_service import add_or_refresh_participant, draw_winner


@pytest.mark.asyncio
async def test_participant_dedup(db_session):
    user = User(email='u1@example.com', password_hash='hash')
    db_session.add(user)
    await db_session.flush()
    giveaway = Giveaway(user_id=user.id, name='Teste', command='!participar', is_open=True)
    db_session.add(giveaway)
    await db_session.flush()

    p1, created1 = await add_or_refresh_participant(
        db_session, giveaway.id, Platform.TWITCH, '123', 'StreamerA'
    )
    p2, created2 = await add_or_refresh_participant(
        db_session, giveaway.id, Platform.TWITCH, '123', 'StreamerA2'
    )

    assert created1 is True
    assert created2 is False
    assert p1.id == p2.id

    all_participants = (await db_session.execute(select(Participant).where(Participant.giveaway_id == giveaway.id))).scalars().all()
    assert len(all_participants) == 1


@pytest.mark.asyncio
async def test_draw_uses_secrets_choice(db_session, monkeypatch):
    user = User(email='u2@example.com', password_hash='hash')
    db_session.add(user)
    await db_session.flush()
    giveaway = Giveaway(user_id=user.id, name='Teste2', command='!participar', is_open=True)
    db_session.add(giveaway)
    await db_session.flush()

    p1, _ = await add_or_refresh_participant(db_session, giveaway.id, Platform.TWITCH, '123', 'A')
    p2, _ = await add_or_refresh_participant(db_session, giveaway.id, Platform.YOUTUBE, '999', 'B')

    called = {'ok': False}

    def fake_choice(items):
        called['ok'] = True
        return p2

    monkeypatch.setattr('app.services.giveaway_service.secrets.choice', fake_choice)
    winner = await draw_winner(db_session, giveaway)

    assert called['ok'] is True
    assert winner is not None
    assert winner.display_name == 'B'
