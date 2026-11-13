"""Add candidate repair plans for open schedule gaps."""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'adjustment_candidates',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('task_id', sa.BigInteger(), sa.ForeignKey('solver_tasks.id'), nullable=False),
        sa.Column('event_ids', sa.JSON(), nullable=False),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('base_version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('input_revision', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('assignments', sa.JSON(), nullable=False),
        sa.Column('metrics_json', sa.JSON(), nullable=False),
        sa.Column('change_summary', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='PROPOSED'),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('task_id', 'sequence', name='uq_adjustment_candidates_task_sequence'),
        sa.CheckConstraint("status IN ('PROPOSED','APPLIED','DISCARDED','EXPIRED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_adjustment_candidates_task_id', 'adjustment_candidates', ['task_id'])
    op.create_index('ix_adjustment_candidates_period_id', 'adjustment_candidates', ['period_id'])
    op.create_index('ix_adjustment_candidates_base_version_id', 'adjustment_candidates', ['base_version_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
