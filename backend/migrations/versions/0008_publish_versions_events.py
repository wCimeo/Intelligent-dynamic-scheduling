"""Add publication guard, period pointer FK, and domain outbox."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'scheduling_guard',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('input_revision', sa.BigInteger(), nullable=False, server_default='1'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.bulk_insert(
        sa.table('scheduling_guard', sa.column('id', sa.Integer()), sa.column('input_revision', sa.BigInteger())),
        [{'id': 1, 'input_revision': 1}],
    )
    op.create_foreign_key(
        'fk_schedule_periods_current_version',
        'schedule_periods',
        'schedule_versions',
        ['current_version_id'],
        ['id'],
    )
    op.create_table(
        'outbox_events',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('event_key', sa.String(length=36), nullable=False, unique=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('aggregate_id', sa.BigInteger(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False, server_default='PENDING'),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("state IN ('PENDING','PROCESSED','FAILED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_outbox_events_state_available', 'outbox_events', ['state', 'available_at'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
