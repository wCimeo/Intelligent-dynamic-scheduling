from datetime import date, time, datetime, timezone
from sqlalchemy import BigInteger, Integer, SmallInteger, String, Date, Time, DateTime, Boolean, ForeignKey, ForeignKeyConstraint, CheckConstraint, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

ID = BigInteger().with_variant(Integer, 'sqlite')
class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint("role IN ('MANAGER','EMPLOYEE')"),
                     CheckConstraint("status IN ('PENDING','ACTIVE','REJECTED','DISABLED')"))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default='EMPLOYEE')
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(String(255))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[str] = mapped_column(String(24))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

class Employee(Base):
    __tablename__ = 'employees'
    __table_args__ = (CheckConstraint('weekly_limit_minutes > 0'),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), unique=True)
    employee_no: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')
    employment_type: Mapped[str] = mapped_column(String(16), default='FULL_TIME')
    weekly_limit_minutes: Mapped[int] = mapped_column(default=2400)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Skill(Base):
    __tablename__ = 'skills'
    __table_args__ = (CheckConstraint("active IN (0, 1)"),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Position(Base):
    __tablename__ = 'positions'
    __table_args__ = (CheckConstraint("active IN (0, 1)"),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class EmployeeSkill(Base):
    __tablename__ = 'employee_skills'
    __table_args__ = (UniqueConstraint('employee_id','skill_id',name='uq_employee_skills_employee_skill'),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey('skills.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class PositionSkill(Base):
    __tablename__ = 'position_skills'
    __table_args__ = (UniqueConstraint('position_id','skill_id',name='uq_position_skills_position_skill'),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey('positions.id'), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey('skills.id'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class ShiftTemplate(Base):
    __tablename__ = 'shift_templates'
    __table_args__ = (CheckConstraint("active IN (0, 1)"),CheckConstraint('start_time < end_time'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class TemplateDemand(Base):
    __tablename__ = 'template_demands'
    __table_args__ = (UniqueConstraint('template_id','position_id',name='uq_template_demands_template_position'),CheckConstraint('required_count >= 0'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey('shift_templates.id'), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey('positions.id'), index=True)
    required_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class SchedulePeriod(Base):
    __tablename__ = 'schedule_periods'
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, unique=True)
    current_version_id: Mapped[int | None] = mapped_column(ID)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class RuleVersion(Base):
    __tablename__ = 'rule_versions'
    __table_args__ = (CheckConstraint('daily_shift_limit BETWEEN 1 AND 10'),CheckConstraint('weekly_minutes_limit BETWEEN 1 AND 10080'),
        CheckConstraint('consecutive_days_limit BETWEEN 1 AND 14'),CheckConstraint('min_rest_minutes BETWEEN 0 AND 1440'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    version_no: Mapped[int] = mapped_column(unique=True)
    effective_week: Mapped[date] = mapped_column(Date, index=True)
    daily_shift_limit: Mapped[int] = mapped_column()
    weekly_minutes_limit: Mapped[int] = mapped_column()
    consecutive_days_limit: Mapped[int] = mapped_column()
    min_rest_minutes: Mapped[int] = mapped_column()
    weights_json: Mapped[dict] = mapped_column(JSON, default=dict)
    schema_version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class ScheduleVersion(Base):
    __tablename__ = 'schedule_versions'
    __table_args__ = (UniqueConstraint('period_id','version_no',name='uq_schedule_versions_period_version'),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    version_no: Mapped[int] = mapped_column()
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('schedule_versions.id'))
    status: Mapped[str] = mapped_column(String(16), default='DRAFT')
    rule_version_id: Mapped[int | None] = mapped_column(ForeignKey('rule_versions.id'))
    source_task_id: Mapped[int | None] = mapped_column(ID)
    base_published_id: Mapped[int | None] = mapped_column(ID)
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    input_revision: Mapped[int] = mapped_column(default=1)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    row_version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))

class VersionShift(Base):
    __tablename__ = 'version_shifts'
    __table_args__ = (UniqueConstraint('version_id','shift_key',name='uq_version_shifts_version_key'),UniqueConstraint('id','version_id',name='uq_version_shifts_id_version'),CheckConstraint('start_time < end_time'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    shift_key: Mapped[str] = mapped_column(String(36))
    template_id: Mapped[int | None] = mapped_column(ForeignKey('shift_templates.id'))
    work_date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class VersionDemand(Base):
    __tablename__ = 'version_demands'
    __table_args__ = (UniqueConstraint('version_shift_id','position_id',name='uq_version_demands_shift_position'),CheckConstraint('required_count >= 0'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    version_shift_id: Mapped[int] = mapped_column(index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey('positions.id'), index=True)
    position_name: Mapped[str] = mapped_column(String(64))
    required_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class SolverTask(Base):
    __tablename__ = 'solver_tasks'
    __table_args__ = (CheckConstraint("mode IN ('INITIAL','REPAIR')"),CheckConstraint("state IN ('QUEUED','RUNNING','OPTIMAL','FEASIBLE','INFEASIBLE','UNKNOWN','FAILED')"))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    draft_version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey('schedule_versions.id'))
    mode: Mapped[str] = mapped_column(String(16), default='INITIAL')
    state: Mapped[str] = mapped_column(String(24), default='QUEUED')
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    input_revision: Mapped[int] = mapped_column()
    draft_revision: Mapped[int] = mapped_column()
    time_limit_seconds: Mapped[int] = mapped_column(default=30)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    attempt: Mapped[int] = mapped_column(default=0)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    row_version: Mapped[int] = mapped_column(default=1)

class Assignment(Base):
    __tablename__ = 'assignments'
    __table_args__ = (
        UniqueConstraint('version_id','version_shift_id','employee_id',name='uq_assignments_version_shift_employee'),
        ForeignKeyConstraint(['version_shift_id','version_id'],['version_shifts.id','version_shifts.version_id'],name='fk_assignments_shift_version'),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    version_shift_id: Mapped[int] = mapped_column(ForeignKey('version_shifts.id'), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey('positions.id'), index=True)
    employee_name: Mapped[str] = mapped_column(String(64))
    position_name: Mapped[str] = mapped_column(String(64))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class SchedulingGuard(Base):
    __tablename__ = 'scheduling_guard'
    id: Mapped[int] = mapped_column(primary_key=True)
    input_revision: Mapped[int] = mapped_column(default=1)

class OutboxEvent(Base):
    __tablename__ = 'outbox_events'
    __table_args__ = (CheckConstraint("state IN ('PENDING','PROCESSED','FAILED')"),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[int] = mapped_column(ID)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16), default='PENDING')
    attempt: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Notification(Base):
    __tablename__ = 'notifications'
    __table_args__ = (
        UniqueConstraint('source_event_id','recipient_user_id',name='uq_notifications_event_recipient'),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    source_event_id: Mapped[int] = mapped_column(ForeignKey('outbox_events.id'), index=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey('employees.id'))
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(500))
    target_url: Mapped[str | None] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class PublicationReceipt(Base):
    __tablename__ = 'publication_receipts'
    __table_args__ = (
        UniqueConstraint('version_id','employee_id',name='uq_publication_receipt_version_employee'),
        CheckConstraint("status IN ('PENDING','CONFIRMED')"),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    notification_id: Mapped[int | None] = mapped_column(ForeignKey('notifications.id'))
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class StoreSetting(Base):
    __tablename__ = 'store_settings'
    id: Mapped[int] = mapped_column(primary_key=True)
    store_name: Mapped[str] = mapped_column(String(100), default='校园咖啡门店')
    timezone: Mapped[str] = mapped_column(String(64), default='Asia/Shanghai')
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    solver_time_limit_seconds: Mapped[int] = mapped_column(default=30)
    row_version: Mapped[int] = mapped_column(default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AIParseRecord(Base):
    __tablename__ = 'ai_parse_records'
    __table_args__ = (
        CheckConstraint("status IN ('PENDING_CONFIRMATION','CONFIRMED','REJECTED','FAILED')"),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    raw_text: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(24), default='PENDING_CONFIRMATION')
    parsed_json: Mapped[dict] = mapped_column(JSON, default=dict)
    base_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(64))
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(255))
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)

class AIExplanationRecord(Base):
    __tablename__ = 'ai_explanation_records'
    __table_args__ = (
        CheckConstraint("status IN ('IN_PROGRESS','COMPLETED','FALLBACK','FAILED')"),
        CheckConstraint("scope IN ('PUBLISHED_SCHEDULE','ADJUSTMENT_CANDIDATE','PERSONAL_SCHEDULE')"),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey('employees.id'), index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey('adjustment_candidates.id'))
    scope: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(String(500))
    facts_json: Mapped[dict] = mapped_column(JSON)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default='IN_PROGRESS')
    model: Mapped[str] = mapped_column(String(64))
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

class AvailabilityProfile(Base):
    __tablename__ = 'availability_profiles'
    __table_args__ = (UniqueConstraint('employee_id','effective_from',name='uq_availability_profiles_employee_from'),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AvailabilityWindow(Base):
    __tablename__ = 'availability_windows'
    __table_args__ = (CheckConstraint('weekday BETWEEN 1 AND 7'),CheckConstraint('start_time < end_time'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey('availability_profiles.id'), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

class AvailabilityOverride(Base):
    __tablename__ = 'availability_overrides'
    __table_args__ = (UniqueConstraint('employee_id','work_date',name='uq_availability_overrides_employee_date'),CheckConstraint("mode IN ('REPLACE','BLOCK')"))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(16))
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class OverrideWindow(Base):
    __tablename__ = 'override_windows'
    __table_args__ = (CheckConstraint('start_time < end_time'),)
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    override_id: Mapped[int] = mapped_column(ForeignKey('availability_overrides.id'), index=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

class PreferenceSubmission(Base):
    __tablename__ = 'preference_submissions'
    __table_args__ = (UniqueConstraint('employee_id','period_id',name='uq_preference_submissions_employee_period'),CheckConstraint("status IN ('DRAFT','SUBMITTED')"))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='DRAFT')
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Preference(Base):
    __tablename__ = 'preferences'
    __table_args__ = (UniqueConstraint('submission_id','work_date','shift_template_id',name='uq_preferences_submission_date_template'),CheckConstraint("kind IN ('PREFER','AVOID')"),CheckConstraint('weight BETWEEN 1 AND 5'))
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey('preference_submissions.id'), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    shift_template_id: Mapped[int] = mapped_column(ForeignKey('shift_templates.id'))
    kind: Mapped[str] = mapped_column(String(16))
    weight: Mapped[int] = mapped_column(default=3)

class LeaveRequest(Base):
    __tablename__ = 'leave_requests'
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','WITHDRAWN')"),
        CheckConstraint('start_date <= end_date'),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_date: Mapped[date] = mapped_column(Date)
    end_time: Mapped[time] = mapped_column(Time)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(String(500))
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class SwapRequest(Base):
    __tablename__ = 'swap_requests'
    __table_args__ = (
        CheckConstraint("mode IN ('TRANSFER','EXCHANGE')"),
        CheckConstraint("status IN ('PENDING_TARGET','PENDING_MANAGER','APPROVED','REJECTED','WITHDRAWN','TARGET_REJECTED','INVALID')"),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    initiator_employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    target_employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    base_version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    source_shift_id: Mapped[int] = mapped_column(ForeignKey('version_shifts.id'))
    source_position_id: Mapped[int] = mapped_column(ForeignKey('positions.id'))
    target_shift_id: Mapped[int | None] = mapped_column(ForeignKey('version_shifts.id'))
    target_position_id: Mapped[int | None] = mapped_column(ForeignKey('positions.id'))
    status: Mapped[str] = mapped_column(String(24), default='PENDING_TARGET')
    initiator_note: Mapped[str | None] = mapped_column(String(500))
    target_note: Mapped[str | None] = mapped_column(String(500))
    target_responded_at: Mapped[datetime | None] = mapped_column(DateTime)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(String(500))
    result_version_id: Mapped[int | None] = mapped_column(ForeignKey('schedule_versions.id'))
    row_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AdjustmentCandidate(Base):
    __tablename__ = 'adjustment_candidates'
    __table_args__ = (
        UniqueConstraint('task_id','sequence',name='uq_adjustment_candidates_task_sequence'),
        CheckConstraint("status IN ('PROPOSED','APPLIED','DISCARDED','EXPIRED')"),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('solver_tasks.id'), index=True)
    event_ids: Mapped[list] = mapped_column(JSON)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    base_version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    input_revision: Mapped[int] = mapped_column()
    sequence: Mapped[int] = mapped_column()
    assignments: Mapped[list] = mapped_column(JSON)
    metrics_json: Mapped[dict] = mapped_column(JSON)
    change_summary: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default='PROPOSED')
    row_version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AdjustmentEvent(Base):
    __tablename__ = 'adjustment_events'
    __table_args__ = (
        UniqueConstraint('source_type', 'source_id', 'version_shift_id', 'position_id', name='uq_adjustment_source_shift_position'),
        CheckConstraint("source_type IN ('LEAVE','SWAP')"),
        CheckConstraint("status IN ('OPEN','RESOLVED','SUPERSEDED')"),
    )
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), default='LEAVE')
    source_id: Mapped[int] = mapped_column(ID, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey('schedule_periods.id'), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey('schedule_versions.id'), index=True)
    version_shift_id: Mapped[int] = mapped_column(ForeignKey('version_shifts.id'), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id'), index=True)
    position_id: Mapped[int] = mapped_column(ForeignKey('positions.id'))
    status: Mapped[str] = mapped_column(String(16), default='OPEN')
    resolved_version_id: Mapped[int | None] = mapped_column(ForeignKey('schedule_versions.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

class ResetRequest(Base):
    __tablename__ = 'password_reset_requests'
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    processed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(ID, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(ID)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class IdempotencyRecord(Base):
    __tablename__ = 'idempotency_records'
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
