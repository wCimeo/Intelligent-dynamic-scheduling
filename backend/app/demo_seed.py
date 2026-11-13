"""Idempotent local demo data for F01-F08 UI review."""
import json
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    Assignment,
    AdjustmentEvent,
    AuditEvent,
    AuthSession,
    AvailabilityOverride,
    AvailabilityProfile,
    AvailabilityWindow,
    Employee,
    EmployeeSkill,
    OverrideWindow,
    OutboxEvent,
    LeaveRequest,
    Position,
    PositionSkill,
    Preference,
    PreferenceSubmission,
    ResetRequest,
    RuleVersion,
    SchedulePeriod,
    ScheduleVersion,
    ShiftTemplate,
    Skill,
    SolverTask,
    SwapRequest,
    TemplateDemand,
    User,
    VersionDemand,
    VersionShift,
    now,
)
from .security import DUMMY_HASH
from .solver import solve_snapshot


DEMO_WEEK = date(2026, 11, 9)
DEMO_NAMES = [
    ('E003', '陈悦'), ('E004', '周宁'), ('E005', '许晨'), ('E006', '苏禾'),
    ('E007', '林晓'), ('E008', '赵一'), ('E009', '王可'), ('E010', '李然'), ('E011', '顾言'),
]
SKILLS = [
    ('coffee', '咖啡制作'), ('cashier', '收银'), ('service', '顾客服务'),
    ('opening', '开店准备'), ('closing', '闭店清洁'),
]
POSITIONS = [
    ('barista', '咖啡师', ['coffee']),
    ('cashier', '收银员', ['cashier']),
    ('service', '服务员', ['service']),
    ('shift_lead', '值班主管', ['opening', 'closing']),
]
TEMPLATES = [
    ('morning', '早班', time(8, 0), time(14, 0)),
    ('middle', '中班', time(14, 0), time(20, 0)),
    ('evening', '晚班', time(18, 0), time(23, 0)),
]


def _minutes(value):
    return value.hour * 60 + value.minute


def _subtract(windows, blocks):
    intervals = [(_minutes(start), _minutes(end)) for start, end in windows]
    for block_start, block_end in blocks:
        start_min, end_min = _minutes(block_start), _minutes(block_end)
        remaining = []
        for start, end in intervals:
            if end <= start_min or start >= end_min:
                remaining.append((start, end))
            else:
                if start < start_min:
                    remaining.append((start, start_min))
                if end > end_min:
                    remaining.append((end_min, end))
        intervals = remaining
    return [(f'{start // 60:02d}:{start % 60:02d}', f'{end // 60:02d}:{end % 60:02d}') for start, end in intervals]


def _remove_xiaozhang(session):
    user = session.scalar(select(User).where(User.username == 'worker', User.display_name == '小张'))
    if not user:
        return '小张账号不存在，无需删除'
    blockers = [
        session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_id == user.id)),
        session.scalar(select(func.count()).select_from(RuleVersion).where(RuleVersion.created_by == user.id)),
        session.scalar(select(func.count()).select_from(ScheduleVersion).where(ScheduleVersion.created_by == user.id)),
        session.scalar(select(func.count()).select_from(SolverTask).where(SolverTask.created_by == user.id)),
    ]
    if any(blockers):
        user.status = 'DISABLED'
        session.execute(update(Employee).where(Employee.user_id == user.id).values(status='INACTIVE'))
        return '小张存在历史业务引用，已保留历史并继续停用'
    employee = session.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee:
        if session.scalar(select(func.count()).select_from(Assignment).where(Assignment.employee_id == employee.id)):
            user.status = 'DISABLED'
            employee.status = 'INACTIVE'
            return '小张已有人员安排，已保留历史并继续停用'
        profile_ids = session.scalars(select(AvailabilityProfile.id).where(AvailabilityProfile.employee_id == employee.id)).all()
        override_ids = session.scalars(select(AvailabilityOverride.id).where(AvailabilityOverride.employee_id == employee.id)).all()
        submission_ids = session.scalars(select(PreferenceSubmission.id).where(PreferenceSubmission.employee_id == employee.id)).all()
        if profile_ids:
            session.execute(delete(AvailabilityWindow).where(AvailabilityWindow.profile_id.in_(profile_ids)))
        if override_ids:
            session.execute(delete(OverrideWindow).where(OverrideWindow.override_id.in_(override_ids)))
        if submission_ids:
            session.execute(delete(Preference).where(Preference.submission_id.in_(submission_ids)))
        session.execute(delete(AvailabilityProfile).where(AvailabilityProfile.employee_id == employee.id))
        session.execute(delete(AvailabilityOverride).where(AvailabilityOverride.employee_id == employee.id))
        session.execute(delete(PreferenceSubmission).where(PreferenceSubmission.employee_id == employee.id))
        session.execute(delete(EmployeeSkill).where(EmployeeSkill.employee_id == employee.id))
        session.delete(employee)
    session.execute(delete(ResetRequest).where(ResetRequest.user_id == user.id))
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    session.execute(update(User).where(User.reviewed_by == user.id).values(reviewed_by=None))
    session.delete(user)
    return '已删除小张账号及其无历史引用的员工数据'


def _ensure_dictionary(session, model, records):
    result = {}
    for code, name in records:
        item = session.scalar(select(model).where(model.code == code))
        if not item:
            item = model(code=code, name=name, active=True)
            session.add(item)
            session.flush()
        elif not item.active:
            item.active = True
        result[code] = item
    return result


def _ensure_employee_account(session, employee_no, name, username):
    user = session.scalar(select(User).where(User.username == username))
    if not user:
        user = User(username=username, display_name=name, password_hash=DUMMY_HASH,
                    role='EMPLOYEE', status='ACTIVE', must_change_password=False, row_version=1)
        session.add(user)
        session.flush()
    employee = session.scalar(select(Employee).where(Employee.employee_no == employee_no))
    if not employee:
        employee = Employee(employee_no=employee_no, name=name, status='ACTIVE',
                            employment_type='FULL_TIME', weekly_limit_minutes=2700, user_id=user.id)
        session.add(employee)
        session.flush()
    else:
        employee.name = name
        employee.status = 'ACTIVE'
        employee.employment_type = 'FULL_TIME'
        employee.weekly_limit_minutes = 2700
        employee.user_id = user.id
    if user.status != 'ACTIVE':
        user.status = 'ACTIVE'
        user.row_version += 1
    return user, employee


def _seed_leave_data(session, admin, xiaolin, seed_employees, period):
    if not period.current_version_id:
        return 0
    current_version = session.get(ScheduleVersion, period.current_version_id)
    if not current_version or current_version.status != 'PUBLISHED':
        return 0
    created = 0
    xiaolin_shift = session.execute(
        select(Assignment, VersionShift)
        .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
        .where(Assignment.version_id == current_version.id, Assignment.employee_id == xiaolin.id)
        .order_by(VersionShift.work_date, VersionShift.start_time)
    ).first()
    if xiaolin_shift and not session.scalar(select(LeaveRequest.id).where(
        LeaveRequest.employee_id == xiaolin.id, LeaveRequest.status.in_(['PENDING', 'APPROVED']))):
        assignment, shift = xiaolin_shift
        leave = LeaveRequest(employee_id=xiaolin.id, start_date=shift.work_date, start_time=shift.start_time,
            end_date=shift.work_date, end_time=shift.end_time, reason='学校课程临时调整',
            status='APPROVED', reviewed_by=admin.id, reviewed_at=now(), review_note='已电话核实课程安排',
            row_version=2)
        session.add(leave)
        session.flush()
        session.add(AdjustmentEvent(source_type='LEAVE', source_id=leave.id, period_id=period.id,
            version_id=current_version.id, version_shift_id=shift.id, employee_id=xiaolin.id,
            position_id=assignment.position_id, status='OPEN'))
        session.add(OutboxEvent(event_key=str(uuid.uuid4()), event_type='leave.approved', aggregate_id=leave.id,
            payload={'leave_id': str(leave.id), 'employee_id': str(xiaolin.id), 'affected_shift_ids': [str(shift.id)]}))
        created += 1
    pending_employee = next((item for item in seed_employees if item.employee_no == 'E003'), None)
    if pending_employee and not session.scalar(select(LeaveRequest.id).where(
        LeaveRequest.employee_id == pending_employee.id, LeaveRequest.status == 'PENDING')):
        pending_shift = session.execute(
            select(VersionShift)
            .join(Assignment, Assignment.version_shift_id == VersionShift.id)
            .where(Assignment.version_id == current_version.id, Assignment.employee_id == pending_employee.id)
            .order_by(VersionShift.work_date, VersionShift.start_time)
        ).first()
        if pending_shift:
            shift = pending_shift[0]
            pending_leave = LeaveRequest(employee_id=pending_employee.id, start_date=shift.work_date,
                start_time=shift.start_time, end_date=shift.work_date, end_time=shift.end_time,
                reason='家庭事务，申请调休')
            session.add(pending_leave)
            session.flush()
            session.add(OutboxEvent(event_key=str(uuid.uuid4()), event_type='leave.requested',
                aggregate_id=pending_leave.id, payload={'leave_id': str(pending_leave.id), 'employee_id': str(pending_employee.id), 'status': 'PENDING'}))
            created += 1
    return created


def _seed_swap_data(session, admin, xiaolin, seed_employees, period):
    if not period.current_version_id:
        return 0
    current = session.get(ScheduleVersion, period.current_version_id)
    if not current or current.status != 'PUBLISHED':
        return 0
    employees = {item.employee_no: item for item in seed_employees}
    created = 0
    xiaolin_dates = set(session.scalars(
        select(VersionShift.work_date)
        .join(Assignment, Assignment.version_shift_id == VersionShift.id)
        .where(Assignment.version_id == current.id, Assignment.employee_id == xiaolin.id)
    ).all())
    if not session.scalar(select(SwapRequest.id).where(SwapRequest.target_employee_id == xiaolin.id, SwapRequest.status == 'PENDING_TARGET')):
        sources = session.execute(
            select(Assignment, VersionShift)
            .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Assignment.version_id == current.id, Employee.employee_no == 'E003')
            .order_by(VersionShift.work_date, VersionShift.start_time)
        ).all()
        source = next((item for item in sources if item[1].work_date not in xiaolin_dates), None)
        if source:
            assignment, shift = source
            swap = SwapRequest(initiator_employee_id=employees['E003'].id, target_employee_id=xiaolin.id,
                mode='TRANSFER', base_version_id=current.id, source_shift_id=shift.id,
                source_position_id=assignment.position_id, status='PENDING_TARGET',
                initiator_note='当天有课程，希望互换值班')
            session.add(swap)
            session.flush()
            session.add(OutboxEvent(event_key=str(uuid.uuid4()), event_type='swap.requested', aggregate_id=swap.id,
                payload={'swap_id': str(swap.id), 'initiator_employee_id': str(swap.initiator_employee_id),
                    'target_employee_id': str(swap.target_employee_id)}))
            created += 1
    if not session.scalar(select(SwapRequest.id).where(SwapRequest.status == 'PENDING_MANAGER')):
        source_rows = session.execute(
            select(Assignment, VersionShift)
            .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
            .join(Employee, Assignment.employee_id == Employee.id)
            .where(Assignment.version_id == current.id, Employee.employee_no == 'E005')
            .order_by(VersionShift.work_date, VersionShift.start_time)
        ).all()
        if source_rows:
            assignment, shift = source_rows[0]
            swap = SwapRequest(initiator_employee_id=employees['E005'].id, target_employee_id=employees['E006'].id,
                mode='TRANSFER', base_version_id=current.id, source_shift_id=shift.id,
                source_position_id=assignment.position_id, status='PENDING_MANAGER',
                initiator_note='家庭安排冲突', target_note='可以接替', target_responded_at=now(), row_version=2)
            session.add(swap)
            session.flush()
            session.add(OutboxEvent(event_key=str(uuid.uuid4()), event_type='swap.target_accepted', aggregate_id=swap.id,
                payload={'swap_id': str(swap.id), 'target_employee_id': str(swap.target_employee_id)}))
            created += 1
    return created


def seed():
    settings = Settings()
    if not settings.db_password.get_secret_value():
        raise SystemExit('请先配置项目数据库密码')
    engine = create_engine(settings.url)
    with Session(engine) as session:
        admin = session.scalar(select(User).where(User.username == 'admin'))
        xiaolin = session.scalar(select(User).where(User.username == 'xiaolin'))
        if not admin or admin.role != 'MANAGER':
            raise SystemExit('缺少 admin 管理员账号，请先完成账号初始化')
        if not xiaolin:
            raise SystemExit('缺少 xiaolin 账号；为避免覆盖密码，本脚本不会创建未知凭据')
        deletion = _remove_xiaozhang(session)
        session.flush()

        skills = _ensure_dictionary(session, Skill, SKILLS)
        positions = _ensure_dictionary(session, Position, [(code, name) for code, name, _ in POSITIONS])
        for code, name, required in POSITIONS:
            position = positions[code]
            if not session.scalar(select(PositionSkill.id).where(PositionSkill.position_id == position.id)):
                for skill_code in required:
                    session.add(PositionSkill(position_id=position.id, skill_id=skills[skill_code].id))

        xiaolin_employee = session.scalar(select(Employee).where(Employee.employee_no == 'E002'))
        if not xiaolin_employee:
            xiaolin_employee = Employee(employee_no='E002', name='小林', status='ACTIVE',
                                        employment_type='FULL_TIME', weekly_limit_minutes=2700, user_id=xiaolin.id)
            session.add(xiaolin_employee)
            session.flush()
        else:
            xiaolin_employee.name = '小林'
            xiaolin_employee.status = 'ACTIVE'
            xiaolin_employee.employment_type = 'FULL_TIME'
            xiaolin_employee.weekly_limit_minutes = 2700
            xiaolin_employee.user_id = xiaolin.id
        if xiaolin.status != 'ACTIVE':
            xiaolin.status = 'ACTIVE'
            xiaolin.row_version += 1
        seed_employees = [xiaolin_employee]
        for employee_no, name in DEMO_NAMES:
            seed_employees.append(_ensure_employee_account(session, employee_no, name, f'demo_{employee_no.lower()}')[1])

        skill_sets = {
            'E002': ['coffee', 'cashier', 'service'],
            'E003': ['coffee', 'service'], 'E004': ['cashier', 'service'], 'E005': ['coffee', 'cashier'],
            'E006': ['service', 'cashier'], 'E007': ['coffee', 'service'], 'E008': ['cashier', 'service'],
            'E009': ['coffee', 'cashier'], 'E010': ['service'], 'E011': ['coffee', 'cashier', 'service'],
        }
        for employee in seed_employees:
            for skill_code in skill_sets[employee.employee_no]:
                if not session.scalar(select(EmployeeSkill.id).where(EmployeeSkill.employee_id == employee.id, EmployeeSkill.skill_id == skills[skill_code].id)):
                    session.add(EmployeeSkill(employee_id=employee.id, skill_id=skills[skill_code].id))
            if not session.scalar(select(AvailabilityProfile.id).where(AvailabilityProfile.employee_id == employee.id, AvailabilityProfile.effective_from == DEMO_WEEK)):
                profile = AvailabilityProfile(employee_id=employee.id, effective_from=DEMO_WEEK, effective_to=None)
                session.add(profile)
                session.flush()
                for weekday in range(1, 8):
                    session.add(AvailabilityWindow(profile_id=profile.id, weekday=weekday, start_time=time(7, 30), end_time=time(23, 30)))
        session.flush()

        if not session.scalar(select(AvailabilityOverride.id).where(AvailabilityOverride.employee_id == xiaolin_employee.id, AvailabilityOverride.work_date == DEMO_WEEK + timedelta(days=2))):
            override = AvailabilityOverride(employee_id=xiaolin_employee.id, work_date=DEMO_WEEK + timedelta(days=2), mode='BLOCK')
            session.add(override)
            session.flush()
            session.add(OverrideWindow(override_id=override.id, start_time=time(14, 0), end_time=time(18, 0)))

        templates = {}
        for code, name, start, end in TEMPLATES:
            template = session.scalar(select(ShiftTemplate).where(ShiftTemplate.code == code))
            if not template:
                template = ShiftTemplate(code=code, name=name, start_time=start, end_time=end, active=True)
                session.add(template)
                session.flush()
            templates[code] = template
            if not session.scalar(select(TemplateDemand.id).where(TemplateDemand.template_id == template.id)):
                for position_code in ('barista', 'cashier', 'service'):
                    session.add(TemplateDemand(template_id=template.id, position_id=positions[position_code].id, required_count=1))

        rule = session.scalar(select(RuleVersion).where(RuleVersion.effective_week == DEMO_WEEK))
        if not rule:
            version_no = (session.scalar(select(func.max(RuleVersion.version_no))) or 0) + 1
            rule = RuleVersion(version_no=version_no, effective_week=DEMO_WEEK, daily_shift_limit=1,
                weekly_minutes_limit=2700, consecutive_days_limit=7, min_rest_minutes=600,
                weights_json={'preference': 30, 'hours_balance': 20, 'evening_balance': 10},
                schema_version=1, created_by=admin.id)
            session.add(rule)
            session.flush()

        period = session.scalar(select(SchedulePeriod).where(SchedulePeriod.week_start == DEMO_WEEK))
        if not period:
            period = SchedulePeriod(week_start=DEMO_WEEK, row_version=1)
            session.add(period)
            session.flush()
        elif period.current_version_id:
            leave_created = _seed_leave_data(session, admin, xiaolin_employee, seed_employees, period)
            swap_created = _seed_swap_data(session, admin, xiaolin_employee, seed_employees, period)
            session.commit()
            print(deletion)
            print(f'演示周期已存在发布版本，基础资料已补齐，未覆盖现有班表；新增请假 {leave_created} 条、换班 {swap_created} 条')
            return

        preference_specs = {
            'E002': [('PREFER', 0, 5), ('AVOID', 4, 4)],
            'E003': [('PREFER', 1, 3)], 'E004': [('AVOID', 2, 4)],
            'E005': [('PREFER', 3, 3)],
        }
        for employee in seed_employees:
            if employee.employee_no not in preference_specs: continue
            submission = session.scalar(select(PreferenceSubmission).where(PreferenceSubmission.employee_id == employee.id, PreferenceSubmission.period_id == period.id))
            if not submission:
                submission = PreferenceSubmission(employee_id=employee.id, period_id=period.id, status='SUBMITTED', submitted_at=now())
                session.add(submission)
                session.flush()
                for kind, day_offset, weight in preference_specs[employee.employee_no]:
                    template = templates['morning' if day_offset != 4 else 'evening']
                    session.add(Preference(submission_id=submission.id, work_date=DEMO_WEEK + timedelta(days=day_offset),
                        shift_template_id=template.id, kind=kind, weight=weight))
        for employee_no in ('E006', 'E007'):
            employee = next(item for item in seed_employees if item.employee_no == employee_no)
            if not session.scalar(select(PreferenceSubmission.id).where(PreferenceSubmission.employee_id == employee.id, PreferenceSubmission.period_id == period.id)):
                session.add(PreferenceSubmission(employee_id=employee.id, period_id=period.id, status='DRAFT'))

        published = ScheduleVersion(period_id=period.id, version_no=1, status='PUBLISHED', rule_version_id=rule.id,
            input_snapshot={'demo': True, 'source': 'seed'}, input_revision=1, metrics_json={}, row_version=2,
            created_by=admin.id, published_at=now(), published_by=admin.id)
        session.add(published)
        session.flush()
        shift_rows = {}
        for day in range(7):
            work_date = DEMO_WEEK + timedelta(days=day)
            for code, name, start_time, end_time in TEMPLATES:
                template = templates[code]
                shift = VersionShift(version_id=published.id, shift_key=str(uuid.uuid4()), template_id=template.id,
                    work_date=work_date, name=name, start_time=start_time, end_time=end_time, enabled=True)
                session.add(shift)
                session.flush()
                shift_rows[shift.shift_key] = shift
                for demand in session.scalars(select(TemplateDemand).where(TemplateDemand.template_id == template.id)).all():
                    position = session.get(Position, demand.position_id)
                    session.add(VersionDemand(version_shift_id=shift.id, position_id=position.id,
                        position_name=position.name, required_count=demand.required_count))
        session.flush()

        days_by_employee = {}
        for employee in seed_employees:
            preferences = []
            submission = session.scalar(select(PreferenceSubmission).where(PreferenceSubmission.employee_id == employee.id, PreferenceSubmission.period_id == period.id, PreferenceSubmission.status == 'SUBMITTED'))
            if submission:
                preferences = [{'id': str(item.id), 'work_date': item.work_date.isoformat(), 'template_id': str(item.shift_template_id),
                    'kind': item.kind, 'weight': item.weight} for item in session.scalars(select(Preference).where(Preference.submission_id == submission.id)).all()]
            days_by_employee[employee.id] = []
            for offset in range(7):
                work_date = DEMO_WEEK + timedelta(days=offset)
                windows = [{'start_time': '07:30', 'end_time': '23:30'}]
                if employee.id == xiaolin_employee.id and work_date == DEMO_WEEK + timedelta(days=2):
                    windows = _subtract([(time(7, 30), time(23, 30))], [(time(14, 0), time(18, 0))])
                    windows = [{'start_time': start, 'end_time': end} for start, end in windows]
                days_by_employee[employee.id].append({'date': work_date.isoformat(), 'weekday': work_date.isoweekday(),
                    'source': 'REGULAR', 'windows': windows})
        snapshot = {
            'week_start': DEMO_WEEK.isoformat(),
            'week_dates': [(DEMO_WEEK + timedelta(days=i)).isoformat() for i in range(7)],
            'rules': {'daily_shift_limit': 1, 'weekly_minutes_limit': 2700, 'consecutive_days_limit': 7,
                'min_rest_minutes': 600, 'weights': {'preference': 30, 'hours_balance': 20, 'evening_balance': 10}},
            'employees': [{'id': str(employee.id), 'employee_no': employee.employee_no, 'name': employee.name,
                'weekly_limit_minutes': employee.weekly_limit_minutes,
                'skills': [str(item) for item in session.scalars(select(EmployeeSkill.skill_id).where(EmployeeSkill.employee_id == employee.id)).all()],
                'availability': days_by_employee[employee.id],
                'preferences': []}
            for employee in seed_employees],
            'shifts': [], 'locked_assignments': [], 'input_revision': 1,
        }
        for shift in shift_rows.values():
            demands = []
            for demand in session.scalars(select(VersionDemand).where(VersionDemand.version_shift_id == shift.id)).all():
                skill_ids = session.scalars(select(PositionSkill.skill_id).where(PositionSkill.position_id == demand.position_id)).all()
                demands.append({'position_id': str(demand.position_id), 'position_name': demand.position_name,
                    'required_count': demand.required_count, 'skill_ids': [str(item) for item in skill_ids]})
            duration = _minutes(shift.end_time) - _minutes(shift.start_time)
            snapshot['shifts'].append({'id': str(shift.id), 'shift_key': shift.shift_key, 'template_id': str(shift.template_id),
                'work_date': shift.work_date.isoformat(), 'name': shift.name, 'start_time': shift.start_time.isoformat(timespec='minutes'),
                'end_time': shift.end_time.isoformat(timespec='minutes'), 'enabled': True, 'duration_minutes': duration,
                'evening': shift.end_time.hour >= 22, 'demands': demands})
        for employee_data in snapshot['employees']:
            submission = session.scalar(select(PreferenceSubmission).where(PreferenceSubmission.employee_id == int(employee_data['id']), PreferenceSubmission.period_id == period.id, PreferenceSubmission.status == 'SUBMITTED'))
            employee_data['preferences'] = [] if not submission else [
                {'id': str(item.id), 'work_date': item.work_date.isoformat(), 'template_id': str(item.shift_template_id),
                 'kind': item.kind, 'weight': item.weight}
                for item in session.scalars(select(Preference).where(Preference.submission_id == submission.id)).all()]
        result = solve_snapshot(snapshot, 20)
        if result['status'] not in {'OPTIMAL', 'FEASIBLE'}:
            session.rollback()
            raise SystemExit(f"演示排班求解失败: {result['status']} {result['issues']}")
        shift_by_key = {item.shift_key: item for item in shift_rows.values()}
        for item in result['assignments']:
            session.add(Assignment(version_id=published.id, version_shift_id=int(item['version_shift_id']),
                employee_id=int(item['employee_id']), position_id=int(item['position_id']),
                employee_name=item['employee_name'], position_name=item['position_name'], locked=False))
        published.metrics_json = {'solver': result['metrics']}
        task1 = SolverTask(period_id=period.id, draft_version_id=published.id, mode='INITIAL', state=result['status'],
            input_snapshot=snapshot, input_revision=1, draft_revision=1, time_limit_seconds=20,
            result_json=result, created_by=admin.id, started_at=now(), finished_at=now())
        session.add(task1)
        session.flush()
        published.source_task_id = task1.id

        draft = ScheduleVersion(period_id=period.id, version_no=2, parent_id=published.id, status='DRAFT',
            rule_version_id=rule.id, base_published_id=published.id,
            input_snapshot={'demo': True, 'source_version_id': str(published.id)}, input_revision=1,
            metrics_json={'solver': result['metrics']}, created_by=admin.id)
        session.add(draft)
        session.flush()
        draft_shift_by_key = {}
        for source_shift in shift_rows.values():
            shift = VersionShift(version_id=draft.id, shift_key=source_shift.shift_key, template_id=source_shift.template_id,
                work_date=source_shift.work_date, name=source_shift.name, start_time=source_shift.start_time,
                end_time=source_shift.end_time, enabled=source_shift.enabled)
            session.add(shift)
            session.flush()
            draft_shift_by_key[source_shift.shift_key] = shift
            for demand in session.scalars(select(VersionDemand).where(VersionDemand.version_shift_id == source_shift.id)).all():
                session.add(VersionDemand(version_shift_id=shift.id, position_id=demand.position_id,
                    position_name=demand.position_name, required_count=demand.required_count))
        result2 = json.loads(json.dumps(result))
        snapshot2 = json.loads(json.dumps(snapshot))
        for shift in snapshot2['shifts']:
            shift['id'] = str(draft_shift_by_key[shift['shift_key']].id)
        for item in result2['assignments']:
            source_id = item['version_shift_id']
            source_key = next(key for key, value in shift_by_key.items() if str(value.id) == source_id)
            item['version_shift_id'] = str(draft_shift_by_key[source_key].id)
            session.add(Assignment(version_id=draft.id, version_shift_id=int(item['version_shift_id']),
                employee_id=int(item['employee_id']), position_id=int(item['position_id']),
                employee_name=item['employee_name'], position_name=item['position_name'], locked=False))
        task2 = SolverTask(period_id=period.id, draft_version_id=draft.id, mode='INITIAL', state=result2['status'],
            input_snapshot=snapshot2, input_revision=1, draft_revision=1, time_limit_seconds=20,
            result_json=result2, created_by=admin.id, started_at=now(), finished_at=now())
        session.add(task2)
        session.flush()
        draft.source_task_id = task2.id
        period.current_version_id = published.id
        period.row_version = 2
        leave_created = _seed_leave_data(session, admin, xiaolin_employee, seed_employees, period)
        swap_created = _seed_swap_data(session, admin, xiaolin_employee, seed_employees, period)
        session.add(AuditEvent(actor_id=admin.id, action='demo.seed_created', entity_id=period.id,
            summary={'employees': len(seed_employees), 'assignments': len(result['assignments'])}))
        session.add(OutboxEvent(event_key=str(uuid.uuid4()), event_type='schedule.published', aggregate_id=published.id,
            payload={'period_id': str(period.id), 'old_version_id': None, 'new_version_id': str(published.id),
                'affected_employee_ids': sorted({item['employee_id'] for item in result['assignments']}),
                'actor_id': str(admin.id), 'occurred_at': datetime.now(timezone.utc).isoformat()}))
        session.commit()
        print(deletion)
        print(f'演示数据已创建：{len(seed_employees)} 名员工，{len(result["assignments"])} 条安排，请假 {leave_created} 条、换班 {swap_created} 条，published=v{published.version_no}, draft=v{draft.version_no}')


if __name__ == '__main__':
    seed()
