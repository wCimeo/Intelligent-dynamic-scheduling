"""Add transfer and exchange requests."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'swap_requests',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('initiator_employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('target_employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('base_version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('source_shift_id', sa.BigInteger(), sa.ForeignKey('version_shifts.id'), nullable=False),
        sa.Column('source_position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=False),
        sa.Column('target_shift_id', sa.BigInteger(), sa.ForeignKey('version_shifts.id'), nullable=True),
        sa.Column('target_position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='PENDING_TARGET'),
        sa.Column('initiator_note', sa.String(length=500), nullable=True),
        sa.Column('target_note', sa.String(length=500), nullable=True),
        sa.Column('target_responded_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.String(length=500), nullable=True),
        sa.Column('result_version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("mode IN ('TRANSFER','EXCHANGE')"),
        sa.CheckConstraint("status IN ('PENDING_TARGET','PENDING_MANAGER','APPROVED','REJECTED','WITHDRAWN','TARGET_REJECTED','INVALID')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_swap_requests_initiator', 'swap_requests', ['initiator_employee_id'])
    op.create_index('ix_swap_requests_target', 'swap_requests', ['target_employee_id'])
    op.create_index('ix_swap_requests_status', 'swap_requests', ['status', 'created_at'])
    op.create_index('ix_swap_requests_base_version', 'swap_requests', ['base_version_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
