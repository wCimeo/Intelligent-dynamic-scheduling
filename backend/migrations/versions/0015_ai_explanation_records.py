"""Add role-filtered AI schedule explanation records."""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_explanation_records',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('requested_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=True),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('candidate_id', sa.BigInteger(), sa.ForeignKey('adjustment_candidates.id'), nullable=True),
        sa.Column('scope', sa.String(length=32), nullable=False),
        sa.Column('question', sa.String(length=500), nullable=False),
        sa.Column('facts_json', sa.JSON(), nullable=False),
        sa.Column('output_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='IN_PROGRESS'),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('usage_json', sa.JSON(), nullable=False),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('IN_PROGRESS','COMPLETED','FALLBACK','FAILED')"),
        sa.CheckConstraint("scope IN ('PUBLISHED_SCHEDULE','ADJUSTMENT_CANDIDATE','PERSONAL_SCHEDULE')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_ai_explanation_records_requested_by', 'ai_explanation_records', ['requested_by'])
    op.create_index('ix_ai_explanation_records_employee_id', 'ai_explanation_records', ['employee_id'])
    op.create_index('ix_ai_explanation_records_period_id', 'ai_explanation_records', ['period_id'])
    op.create_index('ix_ai_explanation_records_created_at', 'ai_explanation_records', ['created_at'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
