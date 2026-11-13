"""Add singleton store settings."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'store_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('store_name', sa.String(length=100), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=False),
        sa.Column('demo_mode', sa.Boolean(), nullable=False),
        sa.Column('solver_time_limit_seconds', sa.Integer(), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('solver_time_limit_seconds BETWEEN 1 AND 120'),
        sa.CheckConstraint("timezone = 'Asia/Shanghai'"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.bulk_insert(
        sa.table(
            'store_settings',
            sa.column('id', sa.Integer()),
            sa.column('store_name', sa.String()),
            sa.column('timezone', sa.String()),
            sa.column('demo_mode', sa.Boolean()),
            sa.column('solver_time_limit_seconds', sa.Integer()),
            sa.column('row_version', sa.Integer()),
            sa.column('updated_at', sa.DateTime()),
        ),
        [{'id': 1, 'store_name': '校园咖啡门店', 'timezone': 'Asia/Shanghai', 'demo_mode': True,
          'solver_time_limit_seconds': 30, 'row_version': 1,
          'updated_at': datetime.now(timezone.utc).replace(tzinfo=None)}],
    )


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
