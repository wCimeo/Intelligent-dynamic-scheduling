import threading
import time
from datetime import timedelta

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    Employee,
    LeaveRequest,
    Notification,
    OutboxEvent,
    PublicationReceipt,
    SchedulePeriod,
    ScheduleVersion,
    SwapRequest,
    User,
    now,
)
from .schemas import PublicationConfirm


class NotificationProblem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def _notification(session, event, user, employee, category, title, body, target_url):
    existing = session.scalar(select(Notification).where(
        Notification.source_event_id == event.id, Notification.recipient_user_id == user.id))
    if existing:
        return existing
    item = Notification(source_event_id=event.id, recipient_user_id=user.id,
        employee_id=employee.id if employee else None, category=category, title=title,
        body=body, target_url=target_url)
    session.add(item)
    session.flush()
    return item


def dispatch_outbox_event(session, event):
    payload = event.payload or {}
    if event.event_type == 'schedule.published':
        version = session.get(ScheduleVersion, int(payload.get('new_version_id', 0)))
        if not version:
            raise ValueError('schedule version missing')
        period = session.get(SchedulePeriod, version.period_id)
        for employee_id in payload.get('affected_employee_ids', []):
            employee = session.get(Employee, int(employee_id))
            user = session.get(User, employee.user_id) if employee and employee.user_id else None
            if not user or user.status != 'ACTIVE':
                continue
            item = _notification(session, event, user, employee, 'SCHEDULE_PUBLISHED',
                f'班表第 {version.version_no} 版已发布',
                f'{period.week_start.isoformat()} 当周班表已更新，请查看本人安排并确认。',
                '/my-schedule')
            receipt = session.scalar(select(PublicationReceipt).where(
                PublicationReceipt.version_id == version.id, PublicationReceipt.employee_id == employee.id))
            if not receipt:
                session.add(PublicationReceipt(period_id=period.id, version_id=version.id,
                    employee_id=employee.id, notification_id=item.id, status='PENDING'))
    elif event.event_type == 'leave.requested':
        leave = session.get(LeaveRequest, int(payload.get('leave_id', event.aggregate_id)))
        employee = session.get(Employee, leave.employee_id) if leave else None
        if not leave or not employee:
            raise ValueError('leave request missing')
        for manager in session.scalars(select(User).where(User.role == 'MANAGER', User.status == 'ACTIVE')).all():
            _notification(session, event, manager, None, 'LEAVE_REQUEST',
                '收到新的请假申请', f'{employee.name} 提交了 {leave.start_date.isoformat()} 的请假申请，等待核实。',
                '/leave')
    elif event.event_type in {'leave.approved', 'leave.rejected'}:
        leave = session.get(LeaveRequest, int(payload.get('leave_id', event.aggregate_id)))
        employee = session.get(Employee, leave.employee_id) if leave else None
        user = session.get(User, employee.user_id) if employee and employee.user_id else None
        if not leave or not user:
            raise ValueError('leave employee missing')
        approved = event.event_type == 'leave.approved'
        _notification(session, event, user, employee, 'LEAVE_RESULT',
            '请假申请已批准' if approved else '请假申请已拒绝',
            f'{leave.start_date.isoformat()} 的请假申请已{"批准" if approved else "拒绝"}。', '/leave')
    elif event.event_type == 'swap.requested':
        swap = session.get(SwapRequest, int(payload.get('swap_id', event.aggregate_id)))
        target = session.get(Employee, swap.target_employee_id) if swap else None
        user = session.get(User, target.user_id) if target and target.user_id else None
        initiator = session.get(Employee, swap.initiator_employee_id) if swap else None
        if not swap or not user:
            raise ValueError('swap target missing')
        _notification(session, event, user, target, 'SWAP_REQUEST',
            '收到换班邀请', f'{initiator.name} 向你发起换班申请，请确认是否接受。', '/swaps')
    elif event.event_type in {'swap.target_accepted', 'swap.target_rejected'}:
        swap = session.get(SwapRequest, int(payload.get('swap_id', event.aggregate_id)))
        initiator = session.get(Employee, swap.initiator_employee_id) if swap else None
        user = session.get(User, initiator.user_id) if initiator and initiator.user_id else None
        if not swap or not user:
            raise ValueError('swap initiator missing')
        accepted = event.event_type == 'swap.target_accepted'
        _notification(session, event, user, initiator, 'SWAP_RESPONSE',
            '接收人已接受换班' if accepted else '接收人已拒绝换班',
            '换班申请已进入管理员审批。' if accepted else '换班申请已结束。', '/swaps')
    elif event.event_type in {'swap.approved', 'swap.rejected'}:
        swap = session.get(SwapRequest, int(payload.get('swap_id', event.aggregate_id)))
        if not swap:
            raise ValueError('swap missing')
        approved = event.event_type == 'swap.approved'
        for employee_id in (swap.initiator_employee_id, swap.target_employee_id):
            employee = session.get(Employee, employee_id)
            user = session.get(User, employee.user_id) if employee and employee.user_id else None
            if user:
                _notification(session, event, user, employee, 'SWAP_RESULT',
                    '换班已批准并发布' if approved else '换班申请已拒绝',
                    '新的班表版本已经生效。' if approved else '原班表继续有效。', '/swaps')
    else:
        return 0
    return 1


def process_pending_events(session, limit=50):
    events = session.scalars(
        select(OutboxEvent).where(OutboxEvent.state == 'PENDING', OutboxEvent.available_at <= now())
        .order_by(OutboxEvent.id).limit(limit).with_for_update()
    ).all()
    processed = 0
    for event in events:
        event_id = event.id
        try:
            dispatch_outbox_event(session, event)
            event.state = 'PROCESSED'
            event.attempt += 1
            session.commit()
            processed += 1
        except Exception:
            session.rollback()
            retry = session.get(OutboxEvent, event_id)
            if not retry:
                continue
            retry.attempt += 1
            if retry.attempt >= 3:
                retry.state = 'FAILED'
            else:
                retry.available_at = now() + timedelta(seconds=60)
            session.commit()
    return processed


def notification_worker(engine):
    while True:
        try:
            with Session(engine) as session:
                process_pending_events(session, 50)
        except Exception:
            pass
        time.sleep(2)


def start_notification_worker(engine):
    threading.Thread(target=notification_worker, args=(engine,), daemon=True, name='notification-worker').start()


def notification_data(item):
    return {'id': str(item.id), 'category': item.category, 'title': item.title, 'body': item.body,
        'target_url': item.target_url, 'is_read': item.is_read,
        'read_at': item.read_at.isoformat() + 'Z' if item.read_at else None,
        'created_at': item.created_at.isoformat() + 'Z'}


def register_notification_routes(app, *, db_dependency, business_user_dependency, manager_dependency,
                                 envelope, employee_for_user, timestamp):
    @app.exception_handler(NotificationProblem)
    async def notification_problem(request, exc):
        return JSONResponse(envelope(request, message=exc.message, code=exc.code), status_code=exc.status)

    @app.get('/api/v1/me/notifications')
    def my_notifications(request: Request, unread_only: bool = False, page: int = Query(1, ge=1),
                         page_size: int = Query(50, ge=1, le=100), user=Depends(business_user_dependency),
                         session: Session = Depends(db_dependency)):
        query = select(Notification).where(Notification.recipient_user_id == user.id)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        items = session.scalars(query.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        unread = session.scalar(select(func.count()).select_from(Notification).where(
            Notification.recipient_user_id == user.id, Notification.is_read.is_(False)))
        return envelope(request, {'items': [notification_data(item) for item in items], 'unread': unread})

    @app.post('/api/v1/me/notifications/{notification_id}/read')
    def read_notification(notification_id: int, request: Request, user=Depends(business_user_dependency),
                          session: Session = Depends(db_dependency)):
        item = session.scalar(select(Notification).where(
            Notification.id == notification_id, Notification.recipient_user_id == user.id).with_for_update())
        if not item:
            raise NotificationProblem(404, 'NOT_FOUND', '通知不存在')
        if not item.is_read:
            item.is_read = True
            item.read_at = now()
            session.commit()
        return envelope(request, notification_data(item), '通知已读')

    @app.post('/api/v1/me/notifications/read-all')
    def read_all_notifications(request: Request, user=Depends(business_user_dependency),
                               session: Session = Depends(db_dependency)):
        for item in session.scalars(select(Notification).where(
            Notification.recipient_user_id == user.id, Notification.is_read.is_(False)).with_for_update()).all():
            item.is_read = True
            item.read_at = now()
        session.commit()
        return envelope(request, {}, '全部通知已标记为已读')

    @app.get('/api/v1/me/publication-receipts')
    def my_publication_receipts(request: Request, status: str = Query('', pattern='^(|PENDING|CONFIRMED)$'),
                                user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        query = select(PublicationReceipt, ScheduleVersion, SchedulePeriod).join(
            ScheduleVersion, PublicationReceipt.version_id == ScheduleVersion.id).join(
            SchedulePeriod, PublicationReceipt.period_id == SchedulePeriod.id).where(
            PublicationReceipt.employee_id == employee.id)
        if status:
            query = query.where(PublicationReceipt.status == status)
        rows = session.execute(query.order_by(PublicationReceipt.id.desc())).all()
        return envelope(request, {'items': [{'id': str(receipt.id), 'period_id': str(period.id),
            'version_id': str(version.id), 'version_no': version.version_no, 'week_start': period.week_start.isoformat(),
            'status': receipt.status, 'revision': receipt.row_version,
            'confirmed_at': timestamp(receipt.confirmed_at)} for receipt, version, period in rows]})

    @app.post('/api/v1/me/publication-receipts/{receipt_id}/confirm')
    def confirm_publication(receipt_id: int, body: PublicationConfirm, request: Request,
                            user=Depends(business_user_dependency), session: Session = Depends(db_dependency)):
        employee = employee_for_user(session, user)
        receipt = session.scalar(select(PublicationReceipt).where(
            PublicationReceipt.id == receipt_id, PublicationReceipt.employee_id == employee.id).with_for_update())
        if not receipt:
            raise NotificationProblem(404, 'NOT_FOUND', '发布确认记录不存在')
        if receipt.row_version != body.expected_revision:
            raise NotificationProblem(409, 'VERSION_CONFLICT', '确认状态已变化，请刷新后重试')
        period = session.get(SchedulePeriod, receipt.period_id)
        version = session.get(ScheduleVersion, receipt.version_id)
        if not period or period.current_version_id != receipt.version_id or not version or version.status != 'PUBLISHED':
            raise NotificationProblem(409, 'RECEIPT_OUTDATED', '该班表版本已被替代，不能确认旧版本')
        if receipt.status != 'CONFIRMED':
            receipt.status = 'CONFIRMED'; receipt.confirmed_at = now(); receipt.row_version += 1
            if receipt.notification_id:
                notification = session.get(Notification, receipt.notification_id)
                if notification and not notification.is_read:
                    notification.is_read = True; notification.read_at = now()
            session.add(AuditEvent(actor_id=user.id, action='publication.confirmed', entity_id=receipt.id,
                summary={'version_id': str(receipt.version_id), 'employee_id': str(employee.id)}))
            session.commit()
        return envelope(request, {'id': str(receipt.id), 'status': receipt.status, 'revision': receipt.row_version,
            'confirmed_at': timestamp(receipt.confirmed_at)}, '班表已确认')

    @app.get('/api/v1/periods/{period_id}/confirmation-status')
    def confirmation_status(period_id: int, request: Request, manager=Depends(manager_dependency),
                            session: Session = Depends(db_dependency)):
        period = session.get(SchedulePeriod, period_id)
        if not period or not period.current_version_id:
            raise NotificationProblem(404, 'NOT_FOUND', '周期尚无当前发布版本')
        version = session.get(ScheduleVersion, period.current_version_id)
        rows = session.execute(select(PublicationReceipt, Employee).join(
            Employee, PublicationReceipt.employee_id == Employee.id).where(
            PublicationReceipt.version_id == version.id).order_by(Employee.name)).all()
        items = [{'id': str(receipt.id), 'employee_id': str(employee.id), 'employee_no': employee.employee_no,
            'employee_name': employee.name, 'status': receipt.status, 'revision': receipt.row_version,
            'confirmed_at': timestamp(receipt.confirmed_at)} for receipt, employee in rows]
        return envelope(request, {'period_id': str(period.id), 'version_id': str(version.id), 'version_no': version.version_no,
            'counts': {'PENDING': sum(1 for item in items if item['status'] == 'PENDING'),
                       'CONFIRMED': sum(1 for item in items if item['status'] == 'CONFIRMED')}, 'items': items})

    @app.post('/api/v1/notifications/process')
    def process_notifications(request: Request, manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        count = process_pending_events(session)
        return envelope(request, {'processed': count}, '通知事件处理完成')
