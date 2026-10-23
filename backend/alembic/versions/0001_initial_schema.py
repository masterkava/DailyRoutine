"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-24 00:18:28.563137

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Needed so the EXCLUDE constraint below can mix '=' on uuid with '&&' on ranges.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='UTC', nullable=False),
    sa.Column('day_start_minute', sa.SmallInteger(), server_default=sa.text('240'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('categories',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('color', sa.String(length=7), nullable=False),
    sa.Column('icon', sa.String(length=40), nullable=True),
    sa.Column('kind', sa.Enum('productive', 'maintenance', 'leisure', 'wasted', name='category_kind'), nullable=False),
    sa.Column('is_archived', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name=op.f('ck_categories_color_hex')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_categories_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories')),
    sa.UniqueConstraint('user_id', 'name', name='uq_categories_user_id_name')
    )
    op.create_index(op.f('ix_categories_user_id'), 'categories', ['user_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash'))
    )
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('routine_templates',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('weekdays', sa.SmallInteger(), server_default=sa.text('31'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('weekdays BETWEEN 0 AND 127', name=op.f('ck_routine_templates_weekdays_range')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_routine_templates_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_routine_templates'))
    )
    op.create_index(op.f('ix_routine_templates_user_id'), 'routine_templates', ['user_id'], unique=False)
    op.create_table('daily_logs',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('log_date', sa.Date(), nullable=False),
    sa.Column('template_id', sa.UUID(), nullable=True),
    sa.Column('planned_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('status', sa.Enum('open', 'closed', name='log_status'), server_default='open', nullable=False),
    sa.Column('mood', sa.SmallInteger(), nullable=True),
    sa.Column('energy', sa.SmallInteger(), nullable=True),
    sa.Column('reflection', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('energy IS NULL OR energy BETWEEN 1 AND 5', name=op.f('ck_daily_logs_energy_range')),
    sa.CheckConstraint('mood IS NULL OR mood BETWEEN 1 AND 5', name=op.f('ck_daily_logs_mood_range')),
    sa.ForeignKeyConstraint(['template_id'], ['routine_templates.id'], name=op.f('fk_daily_logs_template_id_routine_templates'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_daily_logs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_logs')),
    sa.UniqueConstraint('user_id', 'log_date', name='uq_daily_logs_user_id_log_date')
    )
    op.create_table('daily_summaries',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('log_date', sa.Date(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('planned_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('actual_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('aligned_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_daily_summaries_category_id_categories'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_daily_summaries_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_summaries')),
    sa.UniqueConstraint('user_id', 'log_date', 'category_id', name='uq_daily_summaries_user_date_category')
    )
    op.create_table('time_blocks',
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('start_minute', sa.SmallInteger(), nullable=False),
    sa.Column('duration_minutes', sa.SmallInteger(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('duration_minutes BETWEEN 1 AND 1440', name=op.f('ck_time_blocks_duration_range')),
    sa.CheckConstraint('start_minute BETWEEN 0 AND 2879', name=op.f('ck_time_blocks_start_minute_range')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_time_blocks_category_id_categories'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['template_id'], ['routine_templates.id'], name=op.f('fk_time_blocks_template_id_routine_templates'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_time_blocks'))
    )
    op.create_index(op.f('ix_time_blocks_template_id'), 'time_blocks', ['template_id'], unique=False)
    op.create_table('log_entries',
    sa.Column('daily_log_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('planned_block_id', sa.UUID(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.Enum('planned', 'adjusted', 'manual', 'timer', name='entry_source'), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('client_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('ended_at > started_at', name=op.f('ck_log_entries_ended_after_started')),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_log_entries_category_id_categories'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['daily_log_id'], ['daily_logs.id'], name=op.f('fk_log_entries_daily_log_id_daily_logs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_log_entries_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_log_entries')),
    sa.UniqueConstraint('client_id', name=op.f('uq_log_entries_client_id'))
    )
    op.create_index(op.f('ix_log_entries_daily_log_id'), 'log_entries', ['daily_log_id'], unique=False)
    op.create_index('ix_log_entries_user_id_started_at', 'log_entries', ['user_id', 'started_at'], unique=False)
    # A user can't be doing two things at once. Deferred so a single transaction can
    # trim/split neighbouring entries in any order before the check runs at commit.
    op.execute(
        "ALTER TABLE log_entries ADD CONSTRAINT ex_log_entries_no_overlap "
        "EXCLUDE USING gist (user_id WITH =, tstzrange(started_at, ended_at) WITH &&) "
        "DEFERRABLE INITIALLY DEFERRED"
    )


def downgrade() -> None:
    op.drop_index('ix_log_entries_user_id_started_at', table_name='log_entries')
    op.drop_index(op.f('ix_log_entries_daily_log_id'), table_name='log_entries')
    op.drop_table('log_entries')
    op.drop_index(op.f('ix_time_blocks_template_id'), table_name='time_blocks')
    op.drop_table('time_blocks')
    op.drop_table('daily_summaries')
    op.drop_table('daily_logs')
    op.drop_index(op.f('ix_routine_templates_user_id'), table_name='routine_templates')
    op.drop_table('routine_templates')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_categories_user_id'), table_name='categories')
    op.drop_table('categories')
    op.drop_table('users')
    for enum_name in ("entry_source", "log_status", "category_kind"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
