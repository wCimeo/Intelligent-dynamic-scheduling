"""Initial accounts and employee directory. Frozen schema, independent of future ORM edits."""
from alembic import op
import sqlalchemy as sa
revision='0001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('users',
        sa.Column('id',sa.BigInteger(),primary_key=True),sa.Column('username',sa.String(32),nullable=False,unique=True),
        sa.Column('display_name',sa.String(64),nullable=False),sa.Column('password_hash',sa.String(255),nullable=False),
        sa.Column('role',sa.String(16),nullable=False),sa.Column('status',sa.String(16),nullable=False),
        sa.Column('must_change_password',sa.Boolean(),nullable=False),sa.Column('temporary_password_expires_at',sa.DateTime()),
        sa.Column('review_note',sa.String(255)),sa.Column('reviewed_by',sa.BigInteger(),sa.ForeignKey('users.id')),
        sa.Column('reviewed_at',sa.DateTime()),sa.Column('row_version',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.CheckConstraint("role IN ('MANAGER','EMPLOYEE')"),sa.CheckConstraint("status IN ('PENDING','ACTIVE','REJECTED','DISABLED')"),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('auth_sessions',sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('user_id',sa.BigInteger(),sa.ForeignKey('users.id'),nullable=False),sa.Column('token_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('scope',sa.String(24),nullable=False),sa.Column('expires_at',sa.DateTime(),nullable=False),sa.Column('revoked_at',sa.DateTime()),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_auth_sessions_user_id','auth_sessions',['user_id'])
    op.create_index('ix_auth_sessions_expires_at','auth_sessions',['expires_at'])
    op.create_table('employees',sa.Column('id',sa.BigInteger(),primary_key=True),
        sa.Column('user_id',sa.BigInteger(),sa.ForeignKey('users.id'),unique=True),sa.Column('employee_no',sa.String(32),nullable=False,unique=True),
        sa.Column('name',sa.String(64),nullable=False),sa.Column('status',sa.String(16),nullable=False),sa.Column('employment_type',sa.String(16),nullable=False),
        sa.Column('weekly_limit_minutes',sa.Integer(),nullable=False),sa.Column('row_version',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.CheckConstraint('weekly_limit_minutes > 0'),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('password_reset_requests',sa.Column('id',sa.BigInteger(),primary_key=True),sa.Column('user_id',sa.BigInteger(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('status',sa.String(16),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_password_reset_requests_user_id','password_reset_requests',['user_id'])
    op.create_table('audit_events',sa.Column('id',sa.BigInteger(),primary_key=True),sa.Column('actor_id',sa.BigInteger(),sa.ForeignKey('users.id')),
        sa.Column('action',sa.String(64),nullable=False),sa.Column('entity_id',sa.BigInteger()),sa.Column('summary',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('idempotency_records',sa.Column('key',sa.String(160),primary_key=True),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('response',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(),nullable=False),mysql_engine='InnoDB',mysql_charset='utf8mb4')
def downgrade():
    raise RuntimeError('本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。')
