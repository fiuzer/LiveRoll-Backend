import pytest
from fastapi import HTTPException

from app.models import Giveaway, User
from app.services.dependencies import get_owned_giveaway


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_giveaway(db_session):
    owner = User(email='owner@example.com', password_hash='hash')
    other = User(email='other@example.com', password_hash='hash')
    db_session.add_all([owner, other])
    await db_session.flush()

    giveaway = Giveaway(user_id=owner.id, name='Privado', command='!participar', is_open=False)
    db_session.add(giveaway)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await get_owned_giveaway(giveaway.id, other, db_session)

    assert exc.value.status_code == 404
