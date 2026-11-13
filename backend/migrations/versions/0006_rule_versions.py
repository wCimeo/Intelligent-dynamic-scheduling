"""Add immutable scheduling rule versions."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rule_versions',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('version_no', sa.Integer(), nullable=False, unique=True),
        sa.Column('effective_week', sa.Date(), nullable=False),
        sa.Column('daily_shift_limit', sa.Integer(), nullable=False),
        sa.Column('weekly_minutes_limit', sa.Integer(), nullable=False),
        sa.Column('consecutive_days_limit', sa.Integer(), nullable=False),
        sa.Column('min_rest_minutes', sa.Integer(), nullable=False),
        sa.Column('weights_json', sa.JSON(), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('daily_shift_limit BETWEEN 1 AND 10'),
        sa.CheckConstraint('weekly_minutes_limit BETWEEN 1 AND 10080'),
        sa.CheckConstraint('consecutive_days_limit BETWEEN 1 AND 14'),
        sa.CheckConstraint('min_rest_minutes BETWEEN 0 AND 1440'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_rule_versions_effective_week', 'rule_versions', ['effective_week'])
    op.create_foreign_key(
        'fk_schedule_versions_rule_version',
        'schedule_versions',
        'rule_versions',
        ['rule_version_id'],
        ['id'],
    )


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
