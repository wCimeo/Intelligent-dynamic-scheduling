"""Add asynchronous solver tasks and schedule assignments."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'solver_tasks',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('draft_version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('base_version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=True),
        sa.Column('mode', sa.String(length=16), nullable=False, server_default='INITIAL'),
        sa.Column('state', sa.String(length=24), nullable=False, server_default='QUEUED'),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('input_revision', sa.BigInteger(), nullable=False),
        sa.Column('draft_revision', sa.Integer(), nullable=False),
        sa.Column('time_limit_seconds', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('worker_id', sa.String(length=64), nullable=True),
        sa.Column('lease_until', sa.DateTime(), nullable=True),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.String(length=255), nullable=True),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.CheckConstraint("mode IN ('INITIAL','REPAIR')"),
        sa.CheckConstraint("state IN ('QUEUED','RUNNING','OPTIMAL','FEASIBLE','INFEASIBLE','UNKNOWN','FAILED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_solver_tasks_period_id', 'solver_tasks', ['period_id'])
    op.create_index('ix_solver_tasks_draft_version_id', 'solver_tasks', ['draft_version_id'])
    op.create_index('ix_solver_tasks_state', 'solver_tasks', ['state', 'created_at'])
    op.create_foreign_key(
        'fk_schedule_versions_source_task',
        'schedule_versions',
        'solver_tasks',
        ['source_task_id'],
        ['id'],
    )
    op.create_table(
        'assignments',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('version_shift_id', sa.BigInteger(), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=False),
        sa.Column('employee_name', sa.String(length=64), nullable=False),
        sa.Column('position_name', sa.String(length=64), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('version_id', 'version_shift_id', 'employee_id', name='uq_assignments_version_shift_employee'),
        sa.ForeignKeyConstraint(['version_shift_id', 'version_id'], ['version_shifts.id', 'version_shifts.version_id'], name='fk_assignments_shift_version'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_assignments_version_id', 'assignments', ['version_id'])
    op.create_index('ix_assignments_version_shift_id', 'assignments', ['version_shift_id'])
    op.create_index('ix_assignments_employee_id', 'assignments', ['employee_id'])
    op.create_index('ix_assignments_position_id', 'assignments', ['position_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
