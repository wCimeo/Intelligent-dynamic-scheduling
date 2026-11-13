"""Add notifications and publication read receipts."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('source_event_id', sa.BigInteger(), sa.ForeignKey('outbox_events.id'), nullable=False),
        sa.Column('recipient_user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=True),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('body', sa.String(length=500), nullable=False),
        sa.Column('target_url', sa.String(length=255), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('source_event_id', 'recipient_user_id', name='uq_notifications_event_recipient'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_notifications_source_event_id', 'notifications', ['source_event_id'])
    op.create_index('ix_notifications_recipient_read', 'notifications', ['recipient_user_id', 'is_read', 'created_at'])
    op.create_table(
        'publication_receipts',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('version_id', sa.BigInteger(), sa.ForeignKey('schedule_versions.id'), nullable=False),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('notification_id', sa.BigInteger(), sa.ForeignKey('notifications.id'), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='PENDING'),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('version_id', 'employee_id', name='uq_publication_receipt_version_employee'),
        sa.CheckConstraint("status IN ('PENDING','CONFIRMED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_publication_receipts_period_id', 'publication_receipts', ['period_id'])
    op.create_index('ix_publication_receipts_version_id', 'publication_receipts', ['version_id'])
    op.create_index('ix_publication_receipts_employee_id', 'publication_receipts', ['employee_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
