"""Add pending AI availability parse records."""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_parse_records',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('raw_text', sa.String(length=2000), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='PENDING_CONFIRMATION'),
        sa.Column('parsed_json', sa.JSON(), nullable=False),
        sa.Column('base_snapshot', sa.JSON(), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('usage_json', sa.JSON(), nullable=False),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_message', sa.String(length=255), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('PENDING_CONFIRMATION','CONFIRMED','REJECTED','FAILED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_ai_parse_records_employee_id', 'ai_parse_records', ['employee_id'])
    op.create_index('ix_ai_parse_records_created_at', 'ai_parse_records', ['created_at'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
