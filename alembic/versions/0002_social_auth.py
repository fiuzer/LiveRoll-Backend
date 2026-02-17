"""social auth identities

Revision ID: 0002_social_auth
Revises: 0001_initial
Create Date: 2026-02-17 01:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002_social_auth'
down_revision: Union[str, Sequence[str], None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)

    op.create_table(
        'auth_identities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_user_id', name='uq_auth_identity_provider_user'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_auth_identity_user_provider'),
    )
    op.create_index(op.f('ix_auth_identities_provider'), 'auth_identities', ['provider'], unique=False)
    op.create_index(op.f('ix_auth_identities_user_id'), 'auth_identities', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_identities_user_id'), table_name='auth_identities')
    op.drop_index(op.f('ix_auth_identities_provider'), table_name='auth_identities')
    op.drop_table('auth_identities')

    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)
