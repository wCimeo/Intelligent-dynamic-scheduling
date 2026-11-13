import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, Assignment, LeaveRequest, OutboxEvent, SchedulePeriod, ScheduleVersion, VersionShift


def current_published_version(session: Session, period_id: int):
    period = session.get(SchedulePeriod, period_id)
    if not period or not period.current_version_id:
        return None
    return session.scalar(
        select(ScheduleVersion).where(
            ScheduleVersion.id == period.current_version_id,
            ScheduleVersion.status == 'PUBLISHED',
        )
    )


def employee_published_assignments(session: Session, employee_id: int, date_from, date_to):
    rows = session.execute(
        select(Assignment, VersionShift, ScheduleVersion, SchedulePeriod)
        .join(VersionShift, Assignment.version_shift_id == VersionShift.id)
        .join(ScheduleVersion, Assignment.version_id == ScheduleVersion.id)
        .join(SchedulePeriod, ScheduleVersion.period_id == SchedulePeriod.id)
        .where(
            Assignment.employee_id == employee_id,
            ScheduleVersion.status == 'PUBLISHED',
            VersionShift.work_date >= date_from,
            VersionShift.work_date <= date_to,
        )
        .order_by(VersionShift.work_date, VersionShift.start_time)
    ).all()
    return [
        {
            'period_id': str(period.id),
            'version_id': str(version.id),
            'version_no': version.version_no,
            'published_at': version.published_at.isoformat() + 'Z' if version.published_at else None,
            'work_date': shift.work_date.isoformat(),
            'shift_key': shift.shift_key,
            'shift_name': shift.name,
            'start_time': shift.start_time.isoformat(timespec='minutes'),
            'end_time': shift.end_time.isoformat(timespec='minutes'),
            'position_id': str(assignment.position_id),
            'position_name': assignment.position_name,
            'employee_id': str(assignment.employee_id),
            'employee_name': assignment.employee_name,
        }
        for assignment, shift, version, period in rows
    ]


def outbox_events(session: Session, after_id=0, state=None, limit=100):
    query = select(OutboxEvent).where(OutboxEvent.id > after_id)
    if state:
        query = query.where(OutboxEvent.state == state)
    return session.scalars(query.order_by(OutboxEvent.id).limit(limit)).all()


def acknowledge_outbox_event(session: Session, event_id):
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
    if not event:
        return None
    if event.state == 'PENDING':
        event.state = 'PROCESSED'
    return event


def record_outbox_event(session: Session, event_type, aggregate_id, payload):
    event = OutboxEvent(
        event_key=str(uuid.uuid4()),
        event_type=event_type,
        aggregate_id=aggregate_id,
        payload=payload,
        state='PENDING',
    )
    session.add(event)
    return event


def audit_events(session: Session, after_id=0, entity_type=None, entity_id=None, limit=100):
    query = select(AuditEvent).where(AuditEvent.id > after_id)
    if entity_type:
        query = query.where(AuditEvent.action.like(f'{entity_type}.%'))
    if entity_id is not None:
        query = query.where(AuditEvent.entity_id == entity_id)
    return session.scalars(query.order_by(AuditEvent.id).limit(limit)).all()


def approved_unavailability(session: Session, employee_ids, date_from, date_to):
    """F09 extension point.

    F09 owns approved leave persistence. Its implementation should return rows shaped as:
    {"employee_id": int|str, "work_date": "YYYY-MM-DD",
     "start_time": "HH:mm", "end_time": "HH:mm"}
    The shared scheduler and validator will subtract these intervals from effective availability.
    """
    if not employee_ids:
        return []
    rows = session.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id.in_(employee_ids),
            LeaveRequest.status == 'APPROVED',
            LeaveRequest.start_date <= date_to,
            LeaveRequest.end_date >= date_from,
        )
    ).all()
    result = []
    for leave in rows:
        current = max(leave.start_date, date_from)
        last = min(leave.end_date, date_to)
        while current <= last:
            start_minutes = (leave.start_time.hour * 60 + leave.start_time.minute) if current == leave.start_date else 0
            end_minutes = (leave.end_time.hour * 60 + leave.end_time.minute) if current == leave.end_date else 24 * 60
            if end_minutes > start_minutes:
                result.append({
                    'employee_id': str(leave.employee_id),
                    'work_date': current.isoformat(),
                    'start_time': f'{start_minutes // 60:02d}:{start_minutes % 60:02d}',
                    'end_time': f'{end_minutes // 60:02d}:{end_minutes % 60:02d}' if end_minutes < 24 * 60 else '23:59',
                })
            current += timedelta(days=1)
    return result
