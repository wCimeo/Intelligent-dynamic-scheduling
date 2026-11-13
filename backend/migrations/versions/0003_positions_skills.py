"""Add positions, skills, and qualification relations."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'skills',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('code', sa.String(length=32), nullable=False, unique=True),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('active IN (0, 1)'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'positions',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('code', sa.String(length=32), nullable=False, unique=True),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('row_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('active IN (0, 1)'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_table(
        'employee_skills',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('employee_id', sa.BigInteger(), sa.ForeignKey('employees.id'), nullable=False),
        sa.Column('skill_id', sa.BigInteger(), sa.ForeignKey('skills.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('employee_id', 'skill_id', name='uq_employee_skills_employee_skill'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_employee_skills_employee_id', 'employee_skills', ['employee_id'])
    op.create_index('ix_employee_skills_skill_id', 'employee_skills', ['skill_id'])
    op.create_table(
        'position_skills',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('position_id', sa.BigInteger(), sa.ForeignKey('positions.id'), nullable=False),
        sa.Column('skill_id', sa.BigInteger(), sa.ForeignKey('skills.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('position_id', 'skill_id', name='uq_position_skills_position_skill'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
    )
    op.create_index('ix_position_skills_position_id', 'position_skills', ['position_id'])
    op.create_index('ix_position_skills_skill_id', 'position_skills', ['skill_id'])


def downgrade():
    raise RuntimeError(
        '本项目不提供自动删除业务数据的降级操作，请先备份并人工审查。'
    )
