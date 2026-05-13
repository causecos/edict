"""agent_configs and morning_brief_configs tables

Revision ID: 002_configs
Revises: 001_initial
Create Date: 2026-04-23 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_configs"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── agent_configs 表 ──
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.String(50), primary_key=True),  # agent_id as PK
        sa.Column("label", sa.String(50), server_default=""),
        sa.Column("role", sa.String(50), server_default=""),
        sa.Column("duty", sa.Text(), server_default=""),
        sa.Column("emoji", sa.String(10), server_default=""),
        sa.Column("model", sa.String(100), server_default=""),
        sa.Column("default_model", sa.String(100), server_default=""),
        sa.Column("workspace", sa.String(200), server_default=""),
        sa.Column("skills", postgresql.JSONB(), server_default="[]"),
        sa.Column("allow_agents", postgresql.JSONB(), server_default="[]"),
        sa.Column("is_default_model", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_configs_model", "agent_configs", ["model"])

    # ── system_config 表（用於 defaultModel, dispatchChannel 等全局配置）──
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── known_models 表 ──
    op.create_table(
        "known_models",
        sa.Column("id", sa.String(100), primary_key=True),  # e.g. "anthropic/claude-sonnet-4-6"
        sa.Column("label", sa.String(100), server_default=""),
        sa.Column("provider", sa.String(50), server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── morning_brief_configs 表 ──
    op.create_table(
        "morning_brief_configs",
        sa.Column("id", sa.Integer(), primary_key=True, server_default=sa.text("1")),  # singleton
        sa.Column("categories", postgresql.JSONB(), server_default="[]"),
        sa.Column("keywords", postgresql.JSONB(), server_default="[]"),
        sa.Column("custom_feeds", postgresql.JSONB(), server_default="[]"),
        sa.Column("notification_enabled", sa.Boolean(), server_default="true"),
        sa.Column("notification_channel", sa.String(20), server_default="telegram"),
        sa.Column("notification_webhook", sa.Text(), server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── morning_brief_categories 表（正規化 categories）──
    op.create_table(
        "morning_brief_categories",
        sa.Column("id", sa.Integer(), primary_key=True, server_default=sa.text("nextval('morning_brief_cat_seq'::regclass)")),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true"),
        sa.Column("config_id", sa.Integer(), server_default="1"),
    )
    op.create_index("ix_mbc_config", "morning_brief_categories", ["config_id"])


def downgrade() -> None:
    op.drop_table("morning_brief_categories")
    op.drop_table("morning_brief_configs")
    op.drop_table("known_models")
    op.drop_table("system_config")
    op.drop_table("agent_configs")
