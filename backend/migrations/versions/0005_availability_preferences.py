"""Add employee availability profiles, date overrides, and preferences."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'availability_profiles',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('employee_id', 'effective_from', name='uq_availability_profiles_employee_from'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_availability_profiles_employee_id', 'availability_profiles', ['employee_id'])
    op.create_table(
        'availability_windows',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('profile_id', sa.BigInteger(), sa.ForeignKey('availability_profiles.id'), nullable=False),
        sa.Column('weekday', sa.SmallInteger(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.CheckConstraint('weekday BETWEEN 1 AND 7'),
        sa.CheckConstraint('start_time < end_time'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_availability_windows_profile_id', 'availability_windows', ['profile_id'])
    op.create_table(
        'availability_overrides',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('employee_id', 'work_date', name='uq_availability_overrides_employee_date'),
        sa.CheckConstraint("mode IN ('REPLACE','BLOCK')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_availability_overrides_employee_id', 'availability_overrides', ['employee_id'])
    op.create_index('ix_availability_overrides_employee_date', 'availability_overrides', ['employee_id', 'work_date'])
    op.create_table(
        'override_windows',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('override_id', sa.BigInteger(), sa.ForeignKey('availability_overrides.id'), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.CheckConstraint('start_time < end_time'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_override_windows_override_id', 'override_windows', ['override_id'])
    op.create_table(
        'preference_submissions',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('period_id', sa.BigInteger(), sa.ForeignKey('schedule_periods.id'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='DRAFT'),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('employee_id', 'period_id', name='uq_preference_submissions_employee_period'),
        sa.CheckConstraint("status IN ('DRAFT','SUBMITTED')"),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_preference_submissions_employee_id', 'preference_submissions', ['employee_id'])
    op.create_index('ix_preference_submissions_period_id', 'preference_submissions', ['period_id'])
    op.create_table(
        'preferences',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('submission_id', sa.BigInteger(), sa.ForeignKey('preference_submissions.id'), nullable=False),
        sa.Column('work_date', sa.Date(), nullable=False),
        sa.Column('shift_template_id', sa.BigInteger(), sa.ForeignKey('shift_templates.id'), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.UniqueConstraint('submission_id', 'work_date', 'shift_template_id', name='uq_preferences_submission_date_template'),
        sa.CheckConstraint("kind IN ('PREFER','AVOID')"),
        sa.CheckConstraint('weight BETWEEN 1 AND 5'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_preferences_submission_id', 'preferences', ['submission_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
