"""initial market-data store: candles, funding, coverage

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candles",
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("source", "symbol", "interval", "ts"),
    )
    op.create_index(
        "ix_candles_series_ts",
        "candles",
        ["source", "symbol", "interval", "ts"],
    )

    op.create_table(
        "funding",
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("source", "symbol", "ts"),
    )
    op.create_index("ix_funding_series_ts", "funding", ["source", "symbol", "ts"])

    op.create_table(
        "coverage",
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("seg_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seg_end", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source", "symbol", "interval", "seg_start"),
    )

    # Promote candles/funding to Timescale hypertables when the extension is
    # available. On vanilla Postgres this is skipped and they remain regular
    # tables (the rest of the app works identically, just without partitioning).
    conn = op.get_bind()
    available = conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    ).first()
    if available:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        conn.execute(
            sa.text(
                "SELECT create_hypertable('candles', 'ts', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        )
        conn.execute(
            sa.text(
                "SELECT create_hypertable('funding', 'ts', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        )


def downgrade() -> None:
    op.drop_table("coverage")
    op.drop_index("ix_funding_series_ts", table_name="funding")
    op.drop_table("funding")
    op.drop_index("ix_candles_series_ts", table_name="candles")
    op.drop_table("candles")
