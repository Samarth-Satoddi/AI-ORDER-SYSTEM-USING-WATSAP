"""Initial shared ordering schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hotels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("telegram_label", sa.String(length=180), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_hotels_id"), "hotels", ["id"], unique=False)
    op.create_index(op.f("ix_hotels_slug"), "hotels", ["slug"], unique=True)

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index(op.f("ix_customers_id"), "customers", ["id"], unique=False)
    op.create_index(op.f("ix_customers_telegram_chat_id"), "customers", ["telegram_chat_id"], unique=False)
    op.create_index(op.f("ix_customers_telegram_user_id"), "customers", ["telegram_user_id"], unique=True)

    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_items_hotel_id"), "menu_items", ["hotel_id"], unique=False)
    op.create_index(op.f("ix_menu_items_id"), "menu_items", ["id"], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index(op.f("ix_user_sessions_id"), "user_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_user_sessions_telegram_user_id"), "user_sessions", ["telegram_user_id"], unique=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hotel_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["hotel_id"], ["hotels.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False)
    op.create_index(op.f("ix_orders_hotel_id"), "orders", ["hotel_id"], unique=False)
    op.create_index(op.f("ix_orders_id"), "orders", ["id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("menu_item_id", sa.Integer(), nullable=False),
        sa.Column("item_name_snapshot", sa.String(length=180), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_items_id"), "order_items", ["id"], unique=False)
    op.create_index(op.f("ix_order_items_menu_item_id"), "order_items", ["menu_item_id"], unique=False)
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_order_items_order_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_menu_item_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_id"), table_name="order_items")
    op.drop_table("order_items")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_hotel_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_table("orders")
    op.drop_index(op.f("ix_user_sessions_telegram_user_id"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_id"), table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index(op.f("ix_menu_items_id"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_hotel_id"), table_name="menu_items")
    op.drop_table("menu_items")
    op.drop_index(op.f("ix_customers_telegram_user_id"), table_name="customers")
    op.drop_index(op.f("ix_customers_telegram_chat_id"), table_name="customers")
    op.drop_index(op.f("ix_customers_id"), table_name="customers")
    op.drop_table("customers")
    op.drop_index(op.f("ix_hotels_slug"), table_name="hotels")
    op.drop_index(op.f("ix_hotels_id"), table_name="hotels")
    op.drop_table("hotels")

