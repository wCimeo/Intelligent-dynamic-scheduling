"""Add administrator processing metadata to password reset requests."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'password_reset_requests',
        sa.Column('processed_by', sa.BigInteger(), nullable=True),
    )
    op.add_column(
        'password_reset_requests',
        sa.Column('processed_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'password_reset_requests',
        sa.Column('note', sa.String(length=255), nullable=True),
    )
    op.create_foreign_key(
        'fk_password_reset_requests_processed_by_users',
        'password_reset_requests',
        'users',
        ['processed_by'],
        ['id'],
    )
    op.create_index(
        'ix_password_reset_requests_status_created_at',
        'password_reset_requests',
        ['status', 'created_at'],
    )


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
