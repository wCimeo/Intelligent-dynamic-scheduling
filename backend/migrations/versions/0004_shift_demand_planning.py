"""Add shift templates, schedule periods, and draft demand snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'shift_templates',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('code', sa.String(length=32), nullable=False, unique=True),
        sa.Column('name', sa.String(length=32), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('active IN (0, 1)'),
        sa.CheckConstraint('start_time < end_time'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'template_demands',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('template_id', sa.BigInteger(), sa.ForeignKey('shift_templates.id'), nullable=False),
        sa.Column('position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=False),
        sa.Column('required_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('template_id', 'position_id', name='uq_template_demands_template_position'),
        sa.CheckConstraint('required_count >= 0'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_template_demands_template_id', 'template_demands', ['template_id'])
    op.create_index('ix_template_demands_position_id', 'template_demands', ['position_id'])
    op.create_table(
        'schedule_periods',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('week_start', sa.Date(), nullable=False, unique=True),
        sa.Column('current_version_id', sa.BigInteger(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'schedule_versions',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='DRAFT'),
        sa.Column('rule_version_id', sa.BigInteger(), nullable=True),
        sa.Column('source_task_id', sa.BigInteger(), nullable=True),
        sa.Column('base_published_id', sa.BigInteger(), nullable=True),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('input_revision', sa.BigInteger(), nullable=False, server_default='1'),
        sa.Column('metrics_json', sa.JSON(), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('published_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED','SUPERSEDED','DISCARDED')"),
        sa.UniqueConstraint('period_id', 'version_no', name='uq_schedule_versions_period_version'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_schedule_versions_period_id', 'schedule_versions', ['period_id'])
    op.create_table(
        'version_shifts',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('shift_key', sa.String(length=36), nullable=False),
        sa.Column('template_id', sa.BigInteger(), sa.ForeignKey('shift_templates.id'), nullable=True),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('name', sa.String(length=32), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('version_id', 'shift_key', name='uq_version_shifts_version_key'),
        sa.UniqueConstraint('id', 'version_id', name='uq_version_shifts_id_version'),
        sa.CheckConstraint('start_time < end_time'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_version_shifts_version_id', 'version_shifts', ['version_id'])
    op.create_index('ix_version_shifts_version_date', 'version_shifts', ['version_id', 'work_date'])
    op.create_table(
        'version_demands',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('version_shift_id', sa.BigInteger(), sa.ForeignKey('version_shifts.id'), nullable=False),
        sa.Column('position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=False),
        sa.Column('position_name', sa.String(length=64), nullable=False),
        sa.Column('required_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('version_shift_id', 'position_id', name='uq_version_demands_shift_position'),
        sa.CheckConstraint('required_count >= 0'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_version_demands_shift_id', 'version_demands', ['version_shift_id'])
    op.create_index('ix_version_demands_position_id', 'version_demands', ['position_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
