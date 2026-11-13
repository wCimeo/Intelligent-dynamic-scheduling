import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AdjustmentEvent,
    Assignment,
    AuditEvent,
    Employee,
    IdempotencyRecord,
    Position,
    RuleVersion,
    SchedulePeriod,
    ScheduleVersion,
    SchedulingGuard,
    SwapRequest,
    VersionDemand,
    VersionShift,
    now,
)
from .schemas import PublishRequest, SwapCreate, SwapRespond, SwapReview, SwapWithdraw
from .security import digest
from .shared import current_published_version, record_outbox_event
from .validation import eligible_employees, validate_assignments


class SwapProblem(Exception):
    def __init__(self, status, code, message, data=None):
        self.status, self.code, self.message, self.data = status, code, message, data


def register_swap_routes(app, *, db_dependency, business_user_dependency, manager_dependency,
                         envelope, employee_for_user, timestamp, effective_rule_version,
                         build_snapshot, version_data, publish_in_transaction,
                         scheduling_input_revision, shift_started):
    @app.exception_handler(SwapProblem)
    async def swap_problem(request, exc):
        return JSONResponse(envelope(request, data=exc.data, message=exc.message, code=exc.code), status_code=exc.status)

    def active_employee(session, user):
        employee = employee_for_user(session, user)
        if employee.status != 'ACTIVE':
            raise SwapProblem(409, 'EMPLOYEE_INACTIVE', '已停用员工不能发起或处理换班')
        return employee

    def current_period_for_employee(session, employee_id, shift_key):
        versions = session.scalars(select(ScheduleVersion).where(ScheduleVersion.status == 'PUBLISHED')).all()
        for version in versions:
            period = session.get(SchedulePeriod, version.period_id)
            if period and period.current_version_id == version.id and session.scalar(
                select(Assignment.id).join(VersionShift, Assignment.version_shift_id == VersionShift.id).where(
                    Assignment.version_id == version.id, Assignment.employee_id == employee_id,
                    VersionShift.shift_key == shift_key)):
                return period, version
        return None, None

    def swap_data(session, swap):
        initiator = session.get(Employee, swap.initiator_employee_id)
        target = session.get(Employee, swap.target_employee_id)
        source = session.get(VersionShift, swap.source_shift_id)
        target_shift = session.get(VersionShift, swap.target_shift_id) if swap.target_shift_id else None
        source_position = session.get(Position, swap.source_position_id)
        target_position = session.get(Position, swap.target_position_id) if swap.target_position_id else None
        return {
            'id': str(swap.id), 'status': swap.status, 'mode': swap.mode, 'revision': swap.row_version,
            'initiator_employee_id': str(swap.initiator_employee_id),
            'initiator_name': initiator.name if initiator else None,
            'initiator_employee_no': initiator.employee_no if initiator else None,
            'target_employee_id': str(swap.target_employee_id), 'target_name': target.name if target else None,
            'target_employee_no': target.employee_no if target else None,
            'base_version_id': str(swap.base_version_id),
            'source': {'shift_key': source.shift_key, 'work_date': source.work_date.isoformat(), 'shift_name': source.name,
                'start_time': source.start_time.isoformat(timespec='minutes'), 'end_time': source.end_time.isoformat(timespec='minutes'),
                'position_id': str(swap.source_position_id), 'position_name': source_position.name if source_position else None} if source else None,
            'target': {'shift_key': target_shift.shift_key, 'work_date': target_shift.work_date.isoformat(), 'shift_name': target_shift.name,
                'start_time': target_shift.start_time.isoformat(timespec='minutes'), 'end_time': target_shift.end_time.isoformat(timespec='minutes'),
                'position_id': str(swap.target_position_id), 'position_name': target_position.name if target_position else None} if target_shift else None,
            'initiator_note': swap.initiator_note, 'target_note': swap.target_note,
            'target_responded_at': timestamp(swap.target_responded_at),
            'reviewed_by': str(swap.reviewed_by) if swap.reviewed_by else None,
            'reviewed_at': timestamp(swap.reviewed_at), 'review_note': swap.review_note,
            'result_version_id': str(swap.result_version_id) if swap.result_version_id else None,
            'created_at': timestamp(swap.created_at),
        }

    def proposal(session, current, initiator_id, target_id, source_key, source_position_id, target_key=None, target_position_id=None):
        current_data = version_data(session, current)
        assignments = [{
            'shift_key': item['shift_key'], 'employee_id': item['employee_id'], 'position_id': item['position_id'], 'locked': item['locked']
        } for item in current_data['assignments']]
        source_assignment = next((item for item in assignments if item['shift_key'] == source_key and item['employee_id'] == str(initiator_id) and item['position_id'] == str(source_position_id)), None)
        if not source_assignment:
            raise SwapProblem(409, 'SOURCE_ASSIGNMENT_CHANGED', '发起人的班次已不在当前发布版本中')
        target_assignment = None
        if target_key:
            target_assignment = next((item for item in assignments if item['shift_key'] == target_key and item['employee_id'] == str(target_id) and item['position_id'] == str(target_position_id)), None)
            if not target_assignment:
                raise SwapProblem(409, 'TARGET_ASSIGNMENT_CHANGED', '接收人的交换班次已不在当前发布版本中')
        assignments = [item for item in assignments if item is not source_assignment and item is not target_assignment]
        assignments.append({'shift_key': source_key, 'employee_id': str(target_id), 'position_id': str(source_position_id), 'locked': False})
        if target_assignment:
            assignments.append({'shift_key': target_key, 'employee_id': str(initiator_id), 'position_id': str(target_position_id), 'locked': False})
        period = session.get(SchedulePeriod, current.period_id)
        rule = effective_rule_version(session, period.week_start)
        snapshot = build_snapshot(session, current, period, rule, require_draft=False)
        validation = validate_assignments(snapshot, assignments)
        return assignments, validation, period, rule

    @app.get('/api/v1/me/swap-candidates')
    def swap_candidates(request: Request, source_shift_key: str = Query(..., min_length=1, max_length=36),
                        source_position_id: int = Query(..., ge=1), user=Depends(business_user_dependency),
                        session: Session = Depends(db_dependency)):
        employee = active_employee(session, user)
        period, current = current_period_for_employee(session, employee.id, source_shift_key)
        if not current:
            raise SwapProblem(404, 'SCHEDULE_NOT_FOUND', '当前没有可交换的已发布班次')
        rule = effective_rule_version(session, period.week_start)
        snapshot = build_snapshot(session, current, period, rule, require_draft=False)
        assignments = version_data(session, current)['assignments']
        candidates = eligible_employees(snapshot, source_shift_key, source_position_id, assignments)
        result = []
        for candidate in candidates:
            if candidate['employee_id'] == str(employee.id):
                continue
            exchange_assignments = session.execute(
                select(Assignment, VersionShift)
                .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
                .where(Assignment.version_id == current.id, Assignment.employee_id == int(candidate['employee_id']))
                .order_by(VersionShift.work_date, VersionShift.start_time)
            ).all()
            result.append({**candidate, 'exchange_assignments': [{
                'shift_key': shift.shift_key, 'work_date': shift.work_date.isoformat(), 'shift_name': shift.name,
                'start_time': shift.start_time.isoformat(timespec='minutes'), 'end_time': shift.end_time.isoformat(timespec='minutes'),
                'position_id': str(assignment.position_id), 'position_name': assignment.position_name
            } for assignment, shift in exchange_assignments if candidate['eligible'] and not shift_started({'work_date': shift.work_date.isoformat(), 'start_time': shift.start_time.isoformat(timespec='minutes')})]})
        return envelope(request, {'items': result})

    @app.post('/api/v1/me/swap-requests', status_code=201)
    def create_swap(body: SwapCreate, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        key = request.headers.get('idempotency-key', '')
        if not 8 <= len(key) <= 64:
            raise SwapProblem(422, 'IDEMPOTENCY_REQUIRED', '请提供有效的操作编号')
        employee = active_employee(session, user)
        if body.target_employee_id == employee.id:
            raise SwapProblem(422, 'VALIDATION_FAILED', '不能与自己换班')
        record_key = f'{user.id}:swap-create:{key}'
        fingerprint = digest(json.dumps({'employee_id': employee.id, **body.model_dump()}, sort_keys=True))
        record = session.get(IdempotencyRecord, record_key)
        if record:
            if record.request_hash != fingerprint:
                raise SwapProblem(409, 'IDEMPOTENCY_CONFLICT', '操作编号已用于其他请求')
            swap = session.get(SwapRequest, int(record.response['swap_id']))
            return envelope(request, swap_data(session, swap), '已返回原换班申请')
        period, current = current_period_for_employee(session, employee.id, body.source_shift_key)
        if not current:
            raise SwapProblem(409, 'SCHEDULE_NOT_FOUND', '当前没有可交换的已发布班次')
        _, validation, _, _ = proposal(session, current, employee.id, body.target_employee_id,
            body.source_shift_key, body.source_position_id, body.target_shift_key, body.target_position_id)
        if not validation['valid']:
            raise SwapProblem(409, 'SWAP_INELIGIBLE', '拟议换班存在硬冲突', {'hard_conflicts': validation['hard_conflicts']})
        active_duplicate = session.scalar(select(SwapRequest.id).where(
            SwapRequest.initiator_employee_id == employee.id, SwapRequest.target_employee_id == body.target_employee_id,
            SwapRequest.source_shift_id.in_(select(VersionShift.id).where(VersionShift.version_id == current.id, VersionShift.shift_key == body.source_shift_key)),
            SwapRequest.status.in_(['PENDING_TARGET', 'PENDING_MANAGER'])))
        if active_duplicate:
            raise SwapProblem(409, 'SWAP_DUPLICATE', '该班次已经有一条待处理的换班申请')
        source_shift = session.scalar(select(VersionShift).where(VersionShift.version_id == current.id, VersionShift.shift_key == body.source_shift_key))
        target_shift = session.scalar(select(VersionShift).where(VersionShift.version_id == current.id, VersionShift.shift_key == body.target_shift_key)) if body.target_shift_key else None
        swap = SwapRequest(initiator_employee_id=employee.id, target_employee_id=body.target_employee_id, mode=body.mode,
            base_version_id=current.id, source_shift_id=source_shift.id, source_position_id=body.source_position_id,
            target_shift_id=target_shift.id if target_shift else None, target_position_id=body.target_position_id,
            status='PENDING_TARGET', initiator_note=body.note.strip() or None)
        session.add(swap)
        session.flush()
        session.add(AuditEvent(actor_id=user.id, action='swap.requested', entity_id=swap.id))
        record_outbox_event(session, 'swap.requested', swap.id, {'swap_id': str(swap.id), 'initiator_employee_id': str(employee.id), 'target_employee_id': str(body.target_employee_id)})
        session.add(IdempotencyRecord(key=record_key, request_hash=fingerprint, response={'swap_id': str(swap.id)}))
        session.commit()
        return envelope(request, swap_data(session, swap), '换班申请已发送给接收人')

    @app.get('/api/v1/me/swap-requests')
    def my_swaps(request: Request, status: str = Query('', pattern='^(|PENDING_TARGET|PENDING_MANAGER|APPROVED|REJECTED|WITHDRAWN|TARGET_REJECTED|INVALID)$'),
                 user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        query = select(SwapRequest).where((SwapRequest.initiator_employee_id == employee.id) | (SwapRequest.target_employee_id == employee.id))
        if status:
            query = query.where(SwapRequest.status == status)
        items = session.scalars(query.order_by(SwapRequest.id.desc()).limit(200)).all()
        return envelope(request, {'items': [swap_data(session, item) for item in items], 'total': len(items)})

    @app.get('/api/v1/swap-requests')
    def list_swaps(request: Request, status: str = Query('', pattern='^(|PENDING_TARGET|PENDING_MANAGER|APPROVED|REJECTED|WITHDRAWN|TARGET_REJECTED|INVALID)$'),
                   search: str = Query('', max_length=64), manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        query = select(SwapRequest, Employee).join(Employee, SwapRequest.initiator_employee_id == Employee.id)
        if status:
            query = query.where(SwapRequest.status == status)
        if search:
            query = query.where(Employee.name.contains(search, autoescape=True) | Employee.employee_no.contains(search, autoescape=True))
        rows = session.execute(query.order_by(SwapRequest.id.desc()).limit(300)).all()
        return envelope(request, {'items': [swap_data(session, swap) for swap, employee in rows], 'total': len(rows)})

    @app.get('/api/v1/swap-requests/{swap_id}')
    def swap_detail(swap_id: int, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        swap = session.get(SwapRequest, swap_id)
        if not swap:
            raise SwapProblem(404, 'NOT_FOUND', '换班申请不存在')
        if user.role != 'MANAGER':
            employee = employee_for_user(session, user)
            if employee.id not in (swap.initiator_employee_id, swap.target_employee_id):
                raise SwapProblem(404, 'NOT_FOUND', '换班申请不存在')
        return envelope(request, swap_data(session, swap))

    @app.post('/api/v1/me/swap-requests/{swap_id}/respond')
    def respond_swap(swap_id: int, body: SwapRespond, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        swap = session.scalar(select(SwapRequest).where(SwapRequest.id == swap_id).with_for_update())
        if not swap or swap.target_employee_id != employee.id:
            raise SwapProblem(404, 'NOT_FOUND', '换班邀请不存在')
        if swap.row_version != body.expected_revision:
            raise SwapProblem(409, 'VERSION_CONFLICT', '换班申请已变化，请刷新后重试')
        if swap.status != 'PENDING_TARGET':
            raise SwapProblem(409, 'SWAP_NOT_PENDING_TARGET', '该换班申请当前不能由接收人处理')
        swap.status = 'PENDING_MANAGER' if body.decision == 'ACCEPT' else 'TARGET_REJECTED'
        swap.target_note = body.note.strip() or None
        swap.target_responded_at = now()
        swap.row_version += 1
        swap.updated_at = now()
        session.add(AuditEvent(actor_id=user.id, action='swap.target_accepted' if body.decision == 'ACCEPT' else 'swap.target_rejected', entity_id=swap.id))
        record_outbox_event(session, 'swap.target_accepted' if body.decision == 'ACCEPT' else 'swap.target_rejected', swap.id,
            {'swap_id': str(swap.id), 'target_employee_id': str(employee.id)})
        session.commit()
        return envelope(request, swap_data(session, swap), '已接受换班邀请' if body.decision == 'ACCEPT' else '已拒绝换班邀请')

    @app.post('/api/v1/me/swap-requests/{swap_id}/withdraw')
    def withdraw_swap(swap_id: int, body: SwapWithdraw, request: Request, user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        swap = session.scalar(select(SwapRequest).where(SwapRequest.id == swap_id).with_for_update())
        if not swap or swap.initiator_employee_id != employee.id:
            raise SwapProblem(404, 'NOT_FOUND', '换班申请不存在')
        if swap.row_version != body.expected_revision:
            raise SwapProblem(409, 'VERSION_CONFLICT', '换班申请已变化，请刷新后重试')
        if swap.status not in {'PENDING_TARGET', 'PENDING_MANAGER'}:
            raise SwapProblem(409, 'SWAP_NOT_PENDING', '该换班申请当前不能撤回')
        swap.status = 'WITHDRAWN'; swap.row_version += 1; swap.updated_at = now()
        session.add(AuditEvent(actor_id=user.id, action='swap.withdrawn', entity_id=swap.id))
        session.commit()
        return envelope(request, swap_data(session, swap), '换班申请已撤回')

    @app.post('/api/v1/swap-requests/{swap_id}/review')
    def review_swap(swap_id: int, body: SwapReview, request: Request, manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        key = request.headers.get('idempotency-key', '')
        if not 8 <= len(key) <= 64:
            raise SwapProblem(422, 'IDEMPOTENCY_REQUIRED', '请提供有效的操作编号')
        record_key = f'{manager.id}:swap-review:{key}'
        fingerprint = digest(json.dumps({'swap_id': swap_id, **body.model_dump()}, sort_keys=True))
        record = session.get(IdempotencyRecord, record_key)
        if record:
            if record.request_hash != fingerprint:
                raise SwapProblem(409, 'IDEMPOTENCY_CONFLICT', '操作编号已用于其他请求')
            swap = session.get(SwapRequest, int(record.response['swap_id']))
            return envelope(request, swap_data(session, swap), '该审批请求已处理')
        guard = session.get(SchedulingGuard, 1)
        if not guard:
            guard = SchedulingGuard(id=1, input_revision=1); session.add(guard); session.flush()
        session.scalar(select(SchedulingGuard).where(SchedulingGuard.id == 1).with_for_update())
        swap = session.scalar(select(SwapRequest).where(SwapRequest.id == swap_id).with_for_update())
        if not swap:
            raise SwapProblem(404, 'NOT_FOUND', '换班申请不存在')
        if swap.row_version != body.expected_revision:
            raise SwapProblem(409, 'VERSION_CONFLICT', '换班申请已变化，请刷新后重试')
        if swap.status != 'PENDING_MANAGER':
            raise SwapProblem(409, 'SWAP_NOT_PENDING_MANAGER', '换班申请尚未完成接收人确认或已处理')
        current = session.get(ScheduleVersion, swap.base_version_id)
        period = session.get(SchedulePeriod, current.period_id) if current else None
        if not current or current.status != 'PUBLISHED' or not period or period.current_version_id != current.id:
            swap.status = 'INVALID'; swap.row_version += 1; swap.updated_at = now(); session.commit()
            raise SwapProblem(409, 'SWAP_INVALID', '基准发布版本已变化，换班申请失效')
        if body.decision == 'REJECT':
            swap.status = 'REJECTED'; swap.reviewed_by = manager.id; swap.reviewed_at = now()
            swap.review_note = body.note.strip(); swap.row_version += 1; swap.updated_at = now()
            session.add(AuditEvent(actor_id=manager.id, action='swap.rejected', entity_id=swap.id))
            record_outbox_event(session, 'swap.rejected', swap.id, {'swap_id': str(swap.id)})
            session.add(IdempotencyRecord(key=record_key, request_hash=fingerprint, response={'swap_id': str(swap.id)}))
            session.commit()
            return envelope(request, swap_data(session, swap), '换班申请已拒绝')
        source_shift = session.get(VersionShift, swap.source_shift_id)
        target_shift = session.get(VersionShift, swap.target_shift_id) if swap.target_shift_id else None
        if shift_started(source_shift) or (target_shift and shift_started(target_shift)):
            swap.status = 'INVALID'; swap.row_version += 1; swap.updated_at = now(); session.commit()
            raise SwapProblem(409, 'SWAP_STARTED', '涉及班次已经开始，换班申请失效')
        assignments, validation, period, rule = proposal(session, current, swap.initiator_employee_id, swap.target_employee_id,
            source_shift.shift_key, swap.source_position_id, target_shift.shift_key if target_shift else None, swap.target_position_id)
        if not validation['valid']:
            swap.status = 'INVALID'; swap.row_version += 1; swap.updated_at = now(); session.commit()
            raise SwapProblem(409, 'SWAP_INVALID', '当前资格或时间条件已变化，换班申请失效', {'hard_conflicts': validation['hard_conflicts']})
        latest_no = session.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.period_id == period.id)) or 0
        draft = ScheduleVersion(period_id=period.id, version_no=latest_no+1, parent_id=current.id, status='DRAFT',
            rule_version_id=rule.id, base_published_id=current.id, created_by=manager.id,
            input_snapshot={'swap_request_id': str(swap.id), 'base_version_id': str(current.id)},
            input_revision=scheduling_input_revision(session, period), metrics_json={})
        session.add(draft); session.flush()
        draft_shift_by_key = {}
        for source in session.scalars(select(VersionShift).where(VersionShift.version_id == current.id).order_by(VersionShift.work_date, VersionShift.start_time)).all():
            shift = VersionShift(version_id=draft.id, shift_key=source.shift_key, template_id=source.template_id,
                work_date=source.work_date, name=source.name, start_time=source.start_time, end_time=source.end_time, enabled=source.enabled)
            session.add(shift); session.flush(); draft_shift_by_key[shift.shift_key] = shift
            for demand in session.scalars(select(VersionDemand).where(VersionDemand.version_shift_id == source.id)).all():
                session.add(VersionDemand(version_shift_id=shift.id, position_id=demand.position_id,
                    position_name=demand.position_name, required_count=demand.required_count))
        employee_by_id={employee.id: employee for employee in session.scalars(select(Employee)).all()}
        position_by_id={position.id: position for position in session.scalars(select(Position)).all()}
        for item in assignments:
            shift=draft_shift_by_key[item['shift_key']]
            employee=employee_by_id[int(item['employee_id'])]; position=position_by_id[int(item['position_id'])]
            session.add(Assignment(version_id=draft.id, version_shift_id=shift.id, employee_id=employee.id,
                position_id=position.id, employee_name=employee.name, position_name=position.name, locked=item['locked']))
        expected_input=scheduling_input_revision(session,period)
        publish_body=PublishRequest(expected_draft_revision=draft.row_version,expected_period_revision=period.row_version,
            base_published_version_id=current.id,expected_input_revision=expected_input)
        publish_result=publish_in_transaction(session,draft.id,publish_body,manager)
        swap.status='APPROVED'; swap.reviewed_by=manager.id; swap.reviewed_at=now(); swap.review_note=body.note.strip() or None
        swap.result_version_id=int(publish_result['version_id']); swap.row_version+=1; swap.updated_at=now()
        for event in session.scalars(select(AdjustmentEvent).where(
            AdjustmentEvent.source_type=='LEAVE',AdjustmentEvent.status=='OPEN',
            AdjustmentEvent.version_shift_id==source_shift.id,AdjustmentEvent.employee_id==swap.initiator_employee_id)).all():
            event.status='RESOLVED'; event.resolved_version_id=int(publish_result['version_id']); event.resolved_at=now()
        for other in session.scalars(select(SwapRequest).where(
            SwapRequest.id!=swap.id,SwapRequest.base_version_id==current.id,
            SwapRequest.status.in_(['PENDING_TARGET','PENDING_MANAGER']))).all():
            other.status='INVALID'; other.row_version+=1; other.updated_at=now()
        session.add(AuditEvent(actor_id=manager.id, action='swap.approved', entity_id=swap.id,
            summary={'result_version_id':publish_result['version_id']}))
        record_outbox_event(session,'swap.approved',swap.id,{'swap_id':str(swap.id),'result_version_id':publish_result['version_id']})
        session.add(IdempotencyRecord(key=record_key,request_hash=fingerprint,response={'swap_id':str(swap.id)}))
        session.commit()
        return envelope(request,{**swap_data(session,swap),'publish':publish_result},'换班审批通过并已发布新版本')
