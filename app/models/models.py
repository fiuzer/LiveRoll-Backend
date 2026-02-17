from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OAuthProvider(StrEnum):
    TWITCH = 'twitch'
    GOOGLE = 'google'


class Platform(StrEnum):
    TWITCH = 'twitch'
    YOUTUBE = 'youtube'


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    oauth_accounts: Mapped[list['OAuthAccount']] = relationship(back_populates='user', cascade='all,delete-orphan')
    auth_identities: Mapped[list['AuthIdentity']] = relationship(back_populates='user', cascade='all,delete-orphan')
    giveaways: Mapped[list['Giveaway']] = relationship(back_populates='user', cascade='all,delete-orphan')


class AuthIdentity(Base):
    __tablename__ = 'auth_identities'
    __table_args__ = (
        UniqueConstraint('provider', 'provider_user_id', name='uq_auth_identity_provider_user'),
        UniqueConstraint('user_id', 'provider', name='uq_auth_identity_user_provider'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates='auth_identities')


class OAuthAccount(Base):
    __tablename__ = 'oauth_accounts'
    __table_args__ = (UniqueConstraint('user_id', 'provider', name='uq_oauth_user_provider'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    provider: Mapped[OAuthProvider] = mapped_column(Enum(OAuthProvider, name='oauth_provider'))
    access_token_enc: Mapped[str] = mapped_column(String(1024))
    refresh_token_enc: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(String(1024), default='')
    provider_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates='oauth_accounts')


class Giveaway(Base):
    __tablename__ = 'giveaways'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    command: Mapped[str] = mapped_column(String(50), default='!participar')
    ticker_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    youtube_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    youtube_live_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates='giveaways')
    participants: Mapped[list['Participant']] = relationship(back_populates='giveaway', cascade='all,delete-orphan')
    winners: Mapped[list['Winner']] = relationship(back_populates='giveaway', cascade='all,delete-orphan')


class Participant(Base):
    __tablename__ = 'participants'
    __table_args__ = (
        UniqueConstraint('giveaway_id', 'platform', 'platform_user_id', name='uq_participant_unique'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey('giveaways.id', ondelete='CASCADE'), index=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, name='platform_kind'))
    platform_user_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    giveaway: Mapped[Giveaway] = relationship(back_populates='participants')


class Winner(Base):
    __tablename__ = 'winners'

    id: Mapped[int] = mapped_column(primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey('giveaways.id', ondelete='CASCADE'), index=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, name='winner_platform_kind'))
    platform_user_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    drawn_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    giveaway: Mapped[Giveaway] = relationship(back_populates='winners')


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    giveaway_id: Mapped[int | None] = mapped_column(ForeignKey('giveaways.id', ondelete='SET NULL'), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
