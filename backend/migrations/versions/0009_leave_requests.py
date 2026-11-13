"""Add employee leave requests and derived adjustment events."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'leave_requests',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='PENDING'),
        sa.Column('reviewed_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=500), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','WITHDRAWN')"),
        sa.CheckConstraint('start_date <= end_date'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_leave_requests_employee_id', 'leave_requests', ['employee_id'])
    op.create_index('ix_leave_requests_status_dates', 'leave_requests', ['status', 'start_date', 'end_date'])
    op.create_table(
        'adjustment_events',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('source_type', sa.String(length=16), nullable=False, server_default='LEAVE'),
        sa.Column('source_id', sa.BigInteger(), nullable=False),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('version_shift_id', sa.BigInteger(), sa.ForeignKey('version_shifts.id'), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='OPEN'),
        sa.Column('resolved_version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('source_type', 'source_id', 'version_shift_id', 'position_id', name='uq_adjustment_source_shift_position'),
        sa.CheckConstraint("source_type IN ('LEAVE','SWAP')"),
        sa.CheckConstraint("status IN ('OPEN','RESOLVED','SUPERSEDED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_adjustment_events_source_id', 'adjustment_events', ['source_type', 'source_id'])
    op.create_index('ix_adjustment_events_period_id', 'adjustment_events', ['period_id'])
    op.create_index('ix_adjustment_events_version_id', 'adjustment_events', ['version_id'])
    op.create_index('ix_adjustment_events_employee_id', 'adjustment_events', ['employee_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
