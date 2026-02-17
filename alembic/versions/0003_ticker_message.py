"""add ticker message to giveaway

Revision ID: 0003_ticker_message
Revises: 0002_social_auth
Create Date: 2026-02-17 04:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003_ticker_message'
down_revision: Union[str, Sequence[str], None] = '0002_social_auth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('giveaways', sa.Column('ticker_message', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('giveaways', 'ticker_message')
