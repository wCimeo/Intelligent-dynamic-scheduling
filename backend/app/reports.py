import csv
import io
from collections import defaultdict
from datetime import timedelta
from urllib.parse import quote

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AdjustmentEvent,
    Assignment,
    Employee,
    Position,
    Preference,
    PreferenceSubmission,
    PublicationReceipt,
    SchedulePeriod,
    ScheduleVersion,
    SwapRequest,
    VersionShift,
)


class ReportProblem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def _minutes(value):
    return value.hour * 60 + value.minute


def _duration(shift):
    return _minutes(shift.end_time) - _minutes(shift.start_time)


def _published_version(session, period_id):
    period = session.get(SchedulePeriod, period_id)
    if not period or not period.current_version_id:
        raise ReportProblem(404, 'NOT_FOUND', '该周期尚无当前发布版本')
    version = session.get(ScheduleVersion, period.current_version_id)
    if not version or version.status != 'PUBLISHED':
        raise ReportProblem(404, 'NOT_FOUND', '当前发布版本不可用')
    return period, version


def _assignment_rows(session, version_id, employee_id=None, position_id=None):
    query = (
        select(Assignment, VersionShift, Employee, Position)
        .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
        .join(Employee, Assignment.employee_id == Employee.id)
        .join(Position, Assignment.position_id == Position.id)
        .where(Assignment.version_id == version_id)
    )
    if employee_id is not None:
        query = query.where(Assignment.employee_id == employee_id)
    if position_id is not None:
        query = query.where(Assignment.position_id == position_id)
    return session.execute(query.order_by(VersionShift.work_date, VersionShift.start_time, Position.name, Employee.name)).all()


def _preference_stats(session, period_id, employee_ids):
    submissions = session.scalars(select(PreferenceSubmission).where(
        PreferenceSubmission.period_id == period_id,
        PreferenceSubmission.employee_id.in_(employee_ids),
        PreferenceSubmission.status == 'SUBMITTED',
    )).all() if employee_ids else []
    items = defaultdict(list)
    for submission in submissions:
        items[submission.employee_id] = session.scalars(select(Preference).where(Preference.submission_id == submission.id)).all()
    return items


def build_statistics(session, period, version, employee_id=None, position_id=None):
    rows = _assignment_rows(session, version.id, employee_id, position_id)
    assignments_by_employee = defaultdict(list)
    assignments_by_position = defaultdict(list)
    for assignment, shift, employee, position in rows:
        assignments_by_employee[employee.id].append((assignment, shift, employee, position))
        assignments_by_position[position.id].append((assignment, shift, employee, position))
    employee_ids = set(assignments_by_employee)
    preference_map = _preference_stats(session, period.id, employee_ids)
    open_gaps = session.scalars(select(AdjustmentEvent).where(
        AdjustmentEvent.version_id == version.id, AdjustmentEvent.status == 'OPEN')).all()
    gaps_by_employee = defaultdict(int)
    for gap in open_gaps:
        gaps_by_employee[gap.employee_id] += 1
    receipts = {receipt.employee_id: receipt for receipt in session.scalars(
        select(PublicationReceipt).where(PublicationReceipt.version_id == version.id)).all()}
    employees = []
    total_minutes = total_evening = total_shifts = satisfied_total = preference_total = 0
    for employee_id_value, employee_rows in assignments_by_employee.items():
        employee = employee_rows[0][2]
        minutes = sum(_duration(shift) for assignment, shift, employee, position in employee_rows)
        evening = sum(1 for assignment, shift, employee, position in employee_rows if shift.end_time.hour >= 22)
        assigned_slots = {(shift.work_date, assignment.position_id, shift.template_id) for assignment, shift, employee, position in employee_rows}
        preferences = preference_map.get(employee_id_value, [])
        satisfied = 0
        for preference in preferences:
            matching = any(shift_date == preference.work_date and template_id == preference.shift_template_id
                for shift_date, position_key, template_id in assigned_slots)
            if preference.kind == 'PREFER': satisfied += 1 if matching else 0
            else: satisfied += 1 if not matching else 0
        total_minutes += minutes; total_evening += evening; total_shifts += len(employee_rows)
        satisfied_total += satisfied; preference_total += len(preferences)
        employees.append({
            'employee_id': str(employee.id), 'employee_no': employee.employee_no, 'employee_name': employee.name,
            'shift_count': len(employee_rows), 'planned_minutes': minutes, 'planned_hours': round(minutes / 60, 1),
            'evening_count': evening, 'position_count': len({position.id for assignment, shift, employee, position in employee_rows}),
            'preference_total': len(preferences), 'preference_satisfied': satisfied,
            'preference_rate': round(satisfied / len(preferences) * 100, 1) if preferences else None,
            'open_gap_count': gaps_by_employee.get(employee_id_value, 0),
            'confirmation_status': receipts.get(employee_id_value).status if employee_id_value in receipts else None,
        })
    positions = []
    for position_id_value, position_rows in assignments_by_position.items():
        position = position_rows[0][3]
        positions.append({'position_id': str(position.id), 'position_code': position.code, 'position_name': position.name,
            'shift_count': len(position_rows),
            'planned_minutes': sum(_duration(shift) for assignment, shift, employee, position in position_rows),
            'employee_count': len({employee.id for assignment, shift, employee, position in position_rows})})
    swap_count = session.scalar(select(func.count()).select_from(SwapRequest).where(
        SwapRequest.result_version_id == version.id, SwapRequest.status == 'APPROVED'))
    adjustment_count = session.scalar(select(func.count()).select_from(AdjustmentEvent).where(
        AdjustmentEvent.resolved_version_id == version.id, AdjustmentEvent.status == 'RESOLVED'))
    confirmation_confirmed = sum(1 for receipt in receipts.values() if receipt.status == 'CONFIRMED')
    return {
        'period': {'id': str(period.id), 'week_start': period.week_start.isoformat(), 'week_end': (period.week_start + timedelta(days=6)).isoformat()},
        'version': {'id': str(version.id), 'version_no': version.version_no, 'published_at': version.published_at.isoformat() + 'Z' if version.published_at else None},
        'filters': {'employee_id': str(employee_id) if employee_id else None, 'position_id': str(position_id) if position_id else None},
        'summary': {'employee_count': len(employees), 'position_count': len(positions), 'shift_count': total_shifts,
            'planned_minutes': total_minutes, 'planned_hours': round(total_minutes / 60, 1), 'evening_count': total_evening,
            'open_gap_count': len(open_gaps), 'preference_total': preference_total, 'preference_satisfied': satisfied_total,
            'preference_rate': round(satisfied_total / preference_total * 100, 1) if preference_total else None,
            'swap_count': swap_count or 0, 'adjustment_count': adjustment_count or 0,
            'confirmation_total': len(receipts), 'confirmation_confirmed': confirmation_confirmed,
            'confirmation_rate': round(confirmation_confirmed / len(receipts) * 100, 1) if receipts else None},
        'employees': employees, 'positions': positions,
        'note': '计划工时，不代表实际出勤、考勤或薪资。'
    }


def safe_csv(value):
    text = '' if value is None else str(value)
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r')):
        return "'" + text
    return text


def csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='\r\n')
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_csv(value) for value in row])
    body = '\ufeff' + output.getvalue()
    encoded = quote(filename)
    return Response(content=body.encode('utf-8'), media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded}"})


def register_report_routes(app, *, db_dependency, business_user_dependency, manager_dependency,
                           envelope, employee_for_user):
    @app.exception_handler(ReportProblem)
    async def report_problem(request, exc):
        return JSONResponse(envelope(request, message=exc.message, code=exc.code), status_code=exc.status)

    @app.get('/api/v1/statistics')
    def statistics(request: Request, period_id: int = Query(..., ge=1), employee_id: int | None = Query(None, ge=1),
                   position_id: int | None = Query(None, ge=1), manager=Depends(manager_dependency),
                   session: Session = Depends(db_dependency)):
        period, version = _published_version(session, period_id)
        return envelope(request, build_statistics(session, period, version, employee_id, position_id))

    @app.get('/api/v1/me/statistics')
    def my_statistics(request: Request, period_id: int = Query(..., ge=1),
                      user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        period, version = _published_version(session, period_id)
        return envelope(request, build_statistics(session, period, version, employee.id, None))

    @app.get('/api/v1/exports/schedule.csv')
    def export_schedule(period_id: int = Query(..., ge=1), employee_id: int | None = Query(None, ge=1),
                        position_id: int | None = Query(None, ge=1), manager=Depends(manager_dependency),
                        session: Session = Depends(db_dependency)):
        period, version = _published_version(session, period_id)
        rows = _assignment_rows(session, version.id, employee_id, position_id)
        csv_rows = [(shift.work_date.isoformat(), shift.name, shift.start_time.strftime('%H:%M'), shift.end_time.strftime('%H:%M'),
            position.name, employee.employee_no, employee.name, '是' if assignment.locked else '否')
            for assignment, shift, employee, position in rows]
        return csv_response(f'班表-{period.week_start.isoformat()}.csv',
            ['日期', '班次', '开始时间', '结束时间', '岗位', '员工编号', '员工姓名', '锁定'], csv_rows)

    @app.get('/api/v1/me/exports/schedule.csv')
    def export_my_schedule(period_id: int = Query(..., ge=1), user=Depends(business_user_dependency),
                           session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        period, version = _published_version(session, period_id)
        rows = _assignment_rows(session, version.id, employee.id, None)
        csv_rows = [(shift.work_date.isoformat(), shift.name, shift.start_time.strftime('%H:%M'), shift.end_time.strftime('%H:%M'),
            position.name, shift.position_name if hasattr(shift, 'position_name') else position.name)
            for assignment, shift, employee_value, position in rows]
        return csv_response(f'我的班表-{period.week_start.isoformat()}.csv',
            ['日期', '班次', '开始时间', '结束时间', '岗位'], csv_rows)

    @app.get('/api/v1/exports/statistics.csv')
    def export_statistics(period_id: int = Query(..., ge=1), employee_id: int | None = Query(None, ge=1),
                          position_id: int | None = Query(None, ge=1), manager=Depends(manager_dependency),
                          session: Session = Depends(db_dependency)):
        period, version = _published_version(session, period_id)
        data = build_statistics(session, period, version, employee_id, position_id)
        rows = [(item['employee_no'], item['employee_name'], item['shift_count'], item['planned_hours'],
            item['evening_count'], item['position_count'], item['preference_satisfied'], item['preference_total'],
            item['preference_rate'], item['open_gap_count'], item['confirmation_status']) for item in data['employees']]
        return csv_response(f'统计-{period.week_start.isoformat()}.csv',
            ['员工编号', '员工姓名', '计划班次数', '计划工时(小时)', '晚班次数', '岗位数', '偏好满足数', '偏好总数', '偏好满足率(%)', '当前缺岗数', '确认状态'],
            rows)
