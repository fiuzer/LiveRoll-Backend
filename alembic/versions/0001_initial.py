"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-16 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    oauth_provider = sa.Enum('TWITCH', 'GOOGLE', name='oauth_provider')
    platform_kind = sa.Enum('TWITCH', 'YOUTUBE', name='platform_kind')
    winner_platform_kind = sa.Enum('TWITCH', 'YOUTUBE', name='winner_platform_kind')

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table(
        'giveaways',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('command', sa.String(length=50), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('youtube_video_id', sa.String(length=255), nullable=True),
        sa.Column('youtube_live_chat_id', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_giveaways_user_id'), 'giveaways', ['user_id'], unique=False)
    op.create_index(op.f('ix_giveaways_is_open'), 'giveaways', ['is_open'], unique=False)

    op.create_table(
        'oauth_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('provider', oauth_provider, nullable=False),
        sa.Column('access_token_enc', sa.String(length=1024), nullable=False),
        sa.Column('refresh_token_enc', sa.String(length=1024), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', sa.String(length=1024), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'provider', name='uq_oauth_user_provider'),
    )
    op.create_index(op.f('ix_oauth_accounts_user_id'), 'oauth_accounts', ['user_id'], unique=False)

    op.create_table(
        'participants',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=False),
        sa.Column('platform', platform_kind, nullable=False),
        sa.Column('platform_user_id', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('giveaway_id', 'platform', 'platform_user_id', name='uq_participant_unique'),
    )
    op.create_index(op.f('ix_participants_giveaway_id'), 'participants', ['giveaway_id'], unique=False)

    op.create_table(
        'winners',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=False),
        sa.Column('platform', winner_platform_kind, nullable=False),
        sa.Column('platform_user_id', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('drawn_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_winners_giveaway_id'), 'winners', ['giveaway_id'], unique=False)

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('giveaway_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['giveaway_id'], ['giveaways.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_giveaway_id'), 'audit_logs', ['giveaway_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_giveaway_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index(op.f('ix_winners_giveaway_id'), table_name='winners')
    op.drop_table('winners')

    op.drop_index(op.f('ix_participants_giveaway_id'), table_name='participants')
    op.drop_table('participants')

    op.drop_index(op.f('ix_oauth_accounts_user_id'), table_name='oauth_accounts')
    op.drop_table('oauth_accounts')

    op.drop_index(op.f('ix_giveaways_is_open'), table_name='giveaways')
    op.drop_index(op.f('ix_giveaways_user_id'), table_name='giveaways')
    op.drop_table('giveaways')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

    op.execute('DROP TYPE winner_platform_kind')
    op.execute('DROP TYPE platform_kind')
    op.execute('DROP TYPE oauth_provider')
