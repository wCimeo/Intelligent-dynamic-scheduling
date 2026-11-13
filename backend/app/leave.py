import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AdjustmentEvent,
    Assignment,
    AuditEvent,
    Employee,
    IdempotencyRecord,
    LeaveRequest,
    Position,
    SchedulePeriod,
    ScheduleVersion,
    SchedulingGuard,
    VersionShift,
    now,
)
from .schemas import LeaveCreate, LeaveReview, LeaveWindow, LeaveWithdraw
from .security import digest
from .shared import record_outbox_event


class LeaveProblem(Exception):
    def __init__(self, status, code, message, data=None):
        self.status = status
        self.code = code
        self.message = message
        self.data = data


def _datetime(work_date, work_time):
    return datetime.combine(work_date, work_time)


def _request_window(item):
    return _datetime(item.start_date, item.start_time), _datetime(item.end_date, item.end_time)


def _window_from_body(body):
    return _datetime(body.start_date, body.start_time), _datetime(body.end_date, body.end_time)


def _overlapping(session, employee_id, start, end, exclude_id=None):
    candidates = session.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(['PENDING', 'APPROVED']),
            LeaveRequest.start_date <= end.date(),
            LeaveRequest.end_date >= start.date(),
        )
    ).all()
    for item in candidates:
        if exclude_id is not None and item.id == exclude_id:
            continue
        item_start, item_end = _request_window(item)
        if start < item_end and item_start < end:
            return item
    return None


def _current_published_assignments(session, employee_id, start, end):
    rows = session.execute(
        select(Assignment, VersionShift, ScheduleVersion, SchedulePeriod, Position)
        .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
        .join(ScheduleVersion, Assignment.version_id == ScheduleVersion.id)
        .join(SchedulePeriod, ScheduleVersion.period_id == SchedulePeriod.id)
        .join(Position, Assignment.position_id == Position.id)
        .where(
            Assignment.employee_id == employee_id,
            ScheduleVersion.status == 'PUBLISHED',
            SchedulePeriod.current_version_id == ScheduleVersion.id,
            VersionShift.enabled.is_(True),
            VersionShift.work_date >= start.date(),
            VersionShift.work_date <= end.date(),
        )
        .order_by(VersionShift.work_date, VersionShift.start_time)
    ).all()
    result = []
    for assignment, shift, version, period, position in rows:
        shift_start = _datetime(shift.work_date, shift.start_time)
        shift_end = _datetime(shift.work_date, shift.end_time)
        if start < shift_end and shift_start < end:
            result.append({
                'period_id': str(period.id), 'version_id': str(version.id),
                'version_shift_id': str(shift.id), 'shift_key': shift.shift_key,
                'work_date': shift.work_date.isoformat(), 'shift_name': shift.name,
                'start_time': shift.start_time.isoformat(timespec='minutes'),
                'end_time': shift.end_time.isoformat(timespec='minutes'),
                'position_id': str(position.id), 'position_name': assignment.position_name,
                'status': 'PREVIEW',
            })
    return result


def _leave_data(session, request, timestamp):
    employee = session.get(Employee, request.employee_id)
    start, end = _request_window(request)
    impact_rows = session.execute(
        select(AdjustmentEvent, VersionShift, SchedulePeriod)
        .join(VersionShift, AdjustmentEvent.version_shift_id == VersionShift.id)
        .join(SchedulePeriod, AdjustmentEvent.period_id == SchedulePeriod.id)
        .where(AdjustmentEvent.source_type == 'LEAVE', AdjustmentEvent.source_id == request.id)
        .order_by(VersionShift.work_date, VersionShift.start_time)
    ).all()
    if impact_rows:
        affected = [{
            'period_id': str(event.period_id), 'version_id': str(event.version_id),
            'version_shift_id': str(event.version_shift_id), 'shift_key': shift.shift_key,
            'work_date': shift.work_date.isoformat(), 'shift_name': shift.name,
            'start_time': shift.start_time.isoformat(timespec='minutes'),
            'end_time': shift.end_time.isoformat(timespec='minutes'),
            'position_id': str(event.position_id), 'position_name': next(
                (item.position_name for item in session.scalars(select(Assignment).where(Assignment.version_shift_id == shift.id, Assignment.employee_id == request.employee_id, Assignment.position_id == event.position_id))), ''),
            'status': event.status,
        } for event, shift, period in impact_rows]
    else:
        affected = _current_published_assignments(session, request.employee_id, start, end)
    return {
        'id': str(request.id), 'employee_id': str(request.employee_id),
        'employee_no': employee.employee_no if employee else None, 'employee_name': employee.name if employee else None,
        'start_date': request.start_date.isoformat(), 'start_time': request.start_time.isoformat(timespec='minutes'),
        'end_date': request.end_date.isoformat(), 'end_time': request.end_time.isoformat(timespec='minutes'),
        'reason': request.reason, 'status': request.status, 'revision': request.row_version,
        'reviewed_by': str(request.reviewed_by) if request.reviewed_by else None,
        'reviewed_at': timestamp(request.reviewed_at), 'review_note': request.review_note,
        'created_at': timestamp(request.created_at), 'affected_shifts': affected,
        'open_gap_count': sum(1 for item in affected if item.get('status') == 'OPEN'),
    }


def register_leave_routes(app, *, db_dependency, business_user_dependency, manager_dependency,
                          envelope, employee_for_user, timestamp):
    @app.exception_handler(LeaveProblem)
    async def leave_problem(request, exc):
        return JSONResponse(envelope(request, data=exc.data, message=exc.message, code=exc.code), status_code=exc.status)

    def active_employee(session, user):
        employee = employee_for_user(session, user)
        if employee.status != 'ACTIVE':
            raise LeaveProblem(409, 'EMPLOYEE_INACTIVE', '已停用员工不能提交请假')
        return employee

    def validate_create_window(body):
        now_local = datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
        _, end = _window_from_body(body)
        if end <= now_local:
            raise LeaveProblem(422, 'VALIDATION_FAILED', '请假结束时间必须晚于当前时间')

    @app.post('/api/v1/me/leave-requests/preview')
    def preview_leave(body: LeaveWindow, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = active_employee(session, user)
        validate_create_window(body)
        start, end = _window_from_body(body)
        return envelope(request, {'affected_shifts': _current_published_assignments(session, employee.id, start, end)})

    @app.post('/api/v1/me/leave-requests', status_code=201)
    def create_leave(body: LeaveCreate, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        key = request.headers.get('idempotency-key', '')
        if not 8 <= len(key) <= 64:
            raise LeaveProblem(422, 'IDEMPOTENCY_REQUIRED', '请提供有效的操作编号')
        employee = active_employee(session, user)
        record_key = f'{user.id}:leave-create:{key}'
        fingerprint = digest(json.dumps({'employee_id': employee.id, **body.model_dump()}, sort_keys=True, default=str))
        record = session.get(IdempotencyRecord, record_key)
        if record:
            if record.request_hash != fingerprint:
                raise LeaveProblem(409, 'IDEMPOTENCY_CONFLICT', '操作编号已用于其他请求')
            item = session.get(LeaveRequest, int(record.response['request_id']))
            return envelope(request, _leave_data(session, item, timestamp), '已返回原请假申请')
        validate_create_window(body)
        start, end = _window_from_body(body)
        overlap = _overlapping(session, employee.id, start, end)
        if overlap:
            raise LeaveProblem(409, 'LEAVE_OVERLAP', '该时间段已有待审批或已批准的请假')
        leave = LeaveRequest(employee_id=employee.id, start_date=body.start_date, start_time=body.start_time,
            end_date=body.end_date, end_time=body.end_time, reason=body.reason, status='PENDING')
        session.add(leave)
        session.flush()
        data = _leave_data(session, leave, timestamp)
        session.add(IdempotencyRecord(key=record_key, request_hash=fingerprint, response={'request_id': str(leave.id)}))
        session.add(AuditEvent(actor_id=user.id, action='leave.requested', entity_id=leave.id,
            summary={'employee_id': str(employee.id), 'start_date': body.start_date.isoformat(), 'end_date': body.end_date.isoformat()}))
        record_outbox_event(session, 'leave.requested', leave.id,
            {'leave_id': str(leave.id), 'employee_id': str(employee.id), 'status': 'PENDING'})
        session.commit()
        return envelope(request, data, '请假申请已提交')

    @app.get('/api/v1/me/leave-requests')
    def my_leave_requests(request: Request, status: str = Query('', pattern='^(|PENDING|APPROVED|REJECTED|WITHDRAWN)$'),
                          user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = active_employee(session, user)
        query = select(LeaveRequest).where(LeaveRequest.employee_id == employee.id)
        if status:
            query = query.where(LeaveRequest.status == status)
        items = session.scalars(query.order_by(LeaveRequest.id.desc()).limit(200)).all()
        return envelope(request, {'items': [_leave_data(session, item, timestamp) for item in items], 'total': len(items)})

    @app.get('/api/v1/leave-requests')
    def list_leave_requests(request: Request, status: str = Query('', pattern='^(|PENDING|APPROVED|REJECTED|WITHDRAWN)$'),
                            date_from: date | None = None, date_to: date | None = None, search: str = Query('', max_length=64),
                            manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        query = select(LeaveRequest, Employee).join(Employee, LeaveRequest.employee_id == Employee.id)
        if status:
            query = query.where(LeaveRequest.status == status)
        if date_from:
            query = query.where(LeaveRequest.end_date >= date_from)
        if date_to:
            query = query.where(LeaveRequest.start_date <= date_to)
        if search:
            query = query.where(Employee.name.contains(search, autoescape=True) | Employee.employee_no.contains(search, autoescape=True))
        rows = session.execute(query.order_by(LeaveRequest.id.desc()).limit(300)).all()
        return envelope(request, {'items': [_leave_data(session, item, timestamp) for item, employee in rows], 'total': len(rows)})

    @app.get('/api/v1/leave-requests/{leave_id}')
    def leave_detail(leave_id: int, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        leave = session.get(LeaveRequest, leave_id)
        if not leave:
            raise LeaveProblem(404, 'NOT_FOUND', '请假申请不存在')
        if user.role != 'MANAGER':
            employee = employee_for_user(session, user)
            if leave.employee_id != employee.id:
                raise LeaveProblem(404, 'NOT_FOUND', '请假申请不存在')
        return envelope(request, _leave_data(session, leave, timestamp))

    @app.post('/api/v1/me/leave-requests/{leave_id}/withdraw')
    def withdraw_leave(leave_id: int, body: LeaveWithdraw, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = active_employee(session, user)
        leave = session.scalar(select(LeaveRequest).where(LeaveRequest.id == leave_id, LeaveRequest.employee_id == employee.id).with_for_update())
        if not leave:
            raise LeaveProblem(404, 'NOT_FOUND', '请假申请不存在')
        if leave.row_version != body.expected_revision:
            raise LeaveProblem(409, 'VERSION_CONFLICT', '请假申请已变化，请刷新后重试')
        if leave.status != 'PENDING':
            raise LeaveProblem(409, 'LEAVE_NOT_PENDING', '只有待审批请假可以撤回')
        leave.status = 'WITHDRAWN'
        leave.row_version += 1
        leave.updated_at = now()
        session.add(AuditEvent(actor_id=user.id, action='leave.withdrawn', entity_id=leave.id))
        session.commit()
        return envelope(request, _leave_data(session, leave, timestamp), '请假申请已撤回')

    @app.post('/api/v1/leave-requests/{leave_id}/review')
    def review_leave(leave_id: int, body: LeaveReview, request: Request, manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        key = request.headers.get('idempotency-key', '')
        if not 8 <= len(key) <= 64:
            raise LeaveProblem(422, 'IDEMPOTENCY_REQUIRED', '请提供有效的操作编号')
        record_key = f'{manager.id}:leave-review:{key}'
        fingerprint = digest(json.dumps({'leave_id': leave_id, **body.model_dump()}, sort_keys=True))
        record = session.get(IdempotencyRecord, record_key)
        if record:
            if record.request_hash != fingerprint:
                raise LeaveProblem(409, 'IDEMPOTENCY_CONFLICT', '操作编号已用于其他请求')
            item = session.get(LeaveRequest, int(record.response['request_id']))
            return envelope(request, _leave_data(session, item, timestamp), '该审批请求已处理')
        guard = session.scalar(select(SchedulingGuard).where(SchedulingGuard.id == 1).with_for_update())
        if not guard:
            guard = SchedulingGuard(id=1, input_revision=1)
            session.add(guard)
            session.flush()
        leave = session.scalar(select(LeaveRequest).where(LeaveRequest.id == leave_id).with_for_update())
        if not leave:
            raise LeaveProblem(404, 'NOT_FOUND', '请假申请不存在')
        if leave.row_version != body.expected_revision:
            raise LeaveProblem(409, 'VERSION_CONFLICT', '请假申请已变化，请刷新后重试')
        if leave.status != 'PENDING':
            raise LeaveProblem(409, 'LEAVE_NOT_PENDING', '该请假申请已处理')
        start, end = _request_window(leave)
        overlap = _overlapping(session, leave.employee_id, start, end, exclude_id=leave.id)
        if body.decision == 'APPROVE' and overlap and overlap.status == 'APPROVED':
            raise LeaveProblem(409, 'LEAVE_OVERLAP', '该员工已有重叠的已批准请假')
        leave.status = 'APPROVED' if body.decision == 'APPROVE' else 'REJECTED'
        leave.reviewed_by = manager.id
        leave.reviewed_at = now()
        leave.review_note = body.note.strip() or None
        leave.row_version += 1
        leave.updated_at = now()
        affected = _current_published_assignments(session, leave.employee_id, start, end) if body.decision == 'APPROVE' else []
        if body.decision == 'APPROVE':
            for item in affected:
                if not session.scalar(select(AdjustmentEvent.id).where(
                    AdjustmentEvent.source_type == 'LEAVE', AdjustmentEvent.source_id == leave.id,
                    AdjustmentEvent.version_shift_id == int(item['version_shift_id']),
                    AdjustmentEvent.position_id == int(item['position_id']))):
                    session.add(AdjustmentEvent(source_type='LEAVE', source_id=leave.id,
                        period_id=int(item['period_id']), version_id=int(item['version_id']),
                        version_shift_id=int(item['version_shift_id']), employee_id=leave.employee_id,
                        position_id=int(item['position_id']), status='OPEN'))
            guard.input_revision += 1
            record_outbox_event(session, 'leave.approved', leave.id,
                {'leave_id': str(leave.id), 'employee_id': str(leave.employee_id),
                 'affected_shift_ids': [item['version_shift_id'] for item in affected]})
        session.add(AuditEvent(actor_id=manager.id, action=f'leave.{leave.status.lower()}', entity_id=leave.id,
            summary={'decision': body.decision, 'affected_shift_count': len(affected)}))
        data = _leave_data(session, leave, timestamp)
        session.add(IdempotencyRecord(key=record_key, request_hash=fingerprint, response={'request_id': str(leave.id)}))
        session.commit()
        return envelope(request, data, '请假申请已批准' if body.decision == 'APPROVE' else '请假申请已拒绝')
