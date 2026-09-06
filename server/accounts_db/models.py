"""SQLAlchemy models for the accounts/tiers/billing pivot's Postgres tables
(the `public` schema only -- GoTrue owns `auth.users` and its own schema
entirely; these models never touch it, and reference it only via a plain
`user_id` UUID column with no hard cross-schema foreign key, so this
package's Alembic migrations stay independent of GoTrue's own schema
versioning). See accounts_db/README.md and PLAN.md's "Future: accounts,
tiers & billing pivot" section -- this package is not imported by app_api
yet, purely scaffolding."""

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Subscription(Base):
    """1:1 with a GoTrue user. Every user gets a row at first login
    (tier='free', Stripe fields null) so "no row" is never an ambiguous
    state to branch on elsewhere."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False)
    tier: Mapped[str] = mapped_column(default="free", nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(unique=True)
    status: Mapped[str | None]
    current_period_end: Mapped[datetime | None] = mapped_column(nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Postgres CHECK constraints aren't expressed via a Python enum here
        # on purpose -- keeping this a plain string column means adding a
        # tier later (Phase 3+) is a data change, not a migration touching a
        # type.
        {"comment": "tier is application-enforced ('free'/'premium'), not a DB CHECK constraint"},
    )


class ConversationIndex(Base):
    """Sidecar seam into LangGraph's SQLite checkpointer: `thread_id` here
    matches the checkpointer's `thread_id` exactly. Needed because
    thread_id is the *only* identity dimension the checkpointer knows about
    (it's baked into that database's own primary keys) -- per-user
    ownership, history listing, and the 2-month retention sweep all read
    this table instead, without touching the checkpointer's schema."""

    __tablename__ = "conversation_index"

    thread_id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False, index=True
    )
    title: Mapped[str | None]
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class UserHourlyUsage(Base):
    """Flat rolling-hour quota counter -- one row per user per hour bucket,
    incremented on every chat message regardless of whether it starts or
    continues a conversation (no new-vs-follow-up distinction). Mirrors the
    existing SQLite usage_counters(bucket_key, day, count) shape/spirit in
    app_api/main.py, just per-user-per-hour instead of per-key-per-day."""

    __tablename__ = "user_hourly_usage"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    hour_bucket: Mapped[datetime] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(default=0, nullable=False)


class StripeWebhookEvent(Base):
    """Idempotency guard for Stripe webhook delivery -- Stripe redelivers
    events, so `id` (Stripe's own event id, e.g. 'evt_...') is the primary
    key: a duplicate delivery is a no-op insert-conflict, not a double
    apply."""

    __tablename__ = "stripe_webhook_events"

    id: Mapped[str] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(nullable=False)
    received_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
