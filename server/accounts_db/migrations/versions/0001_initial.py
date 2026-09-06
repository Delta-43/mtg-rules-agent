"""Initial accounts/tiers/billing schema (public schema only -- never
touches GoTrue's auth.* schema).

Revision ID: 0001
Revises:
Create Date: 2026-09-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("tier", sa.String(), nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(), unique=True),
        sa.Column("stripe_subscription_id", sa.String(), unique=True),
        sa.Column("status", sa.String()),
        sa.Column("current_period_end", sa.TIMESTAMP(timezone=True)),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        comment="tier is application-enforced ('free'/'premium'), not a DB CHECK constraint",
    )

    op.create_table(
        "conversation_index",
        sa.Column("thread_id", sa.String(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_active_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("title", sa.String()),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_conversation_index_user_id", "conversation_index", ["user_id"])
    op.create_index("ix_conversation_index_last_active_at", "conversation_index", ["last_active_at"])

    op.create_table(
        "user_hourly_usage",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hour_bucket", sa.TIMESTAMP(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_events")
    op.drop_table("user_hourly_usage")
    op.drop_index("ix_conversation_index_last_active_at", table_name="conversation_index")
    op.drop_index("ix_conversation_index_user_id", table_name="conversation_index")
    op.drop_table("conversation_index")
    op.drop_table("subscriptions")
