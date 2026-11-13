import json

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AdjustmentCandidate,
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
    SolverTask,
    VersionDemand,
    VersionShift,
    now,
)
from .schemas import AdjustmentApply, AdjustmentCandidateDiscard, AdjustmentGenerate, PublishRequest
from .security import digest
from .shared import record_outbox_event
from .solver import solve_repair_candidates
from .validation import validate_assignments


class AdjustmentProblem(Exception):
    def __init__(self, status, code, message, data=None):
        self.status, self.code, self.message, self.data = status, code, message, data


def register_adjustment_routes(app, *, db_dependency, manager_dependency, envelope,
                               build_snapshot, version_data, publish_in_transaction,
                               scheduling_input_revision, shift_started):
    @app.exception_handler(AdjustmentProblem)
    async def adjustment_problem(request, exc):
        return JSONResponse(envelope(request, data=exc.data, message=exc.message, code=exc.code), status_code=exc.status)

    def event_data(session, event):
        shift = session.get(VersionShift, event.version_shift_id)
        employee = session.get(Employee, event.employee_id)
        position = session.get(Position, event.position_id)
        period = session.get(SchedulePeriod, event.period_id)
        return {
            'id': str(event.id), 'source_type': event.source_type, 'source_id': str(event.source_id),
            'status': event.status, 'period_id': str(event.period_id), 'version_id': str(event.version_id),
            'version_shift_id': str(event.version_shift_id), 'shift_key': shift.shift_key if shift else None,
            'work_date': shift.work_date.isoformat() if shift else None, 'shift_name': shift.name if shift else None,
            'start_time': shift.start_time.isoformat(timespec='minutes') if shift else None,
            'end_time': shift.end_time.isoformat(timespec='minutes') if shift else None,
            'week_start': period.week_start.isoformat() if period else None,
            'employee_id': str(event.employee_id), 'employee_name': employee.name if employee else None,
            'position_id': str(event.position_id), 'position_name': position.name if position else None,
            'created_at': event.created_at.isoformat() + 'Z'
        }

    def candidate_data(candidate):
        return {'id': str(candidate.id), 'task_id': str(candidate.task_id),
            'event_ids': candidate.event_ids, 'period_id': str(candidate.period_id),
            'base_version_id': str(candidate.base_version_id), 'input_revision': candidate.input_revision,
            'sequence': candidate.sequence, 'assignments': candidate.assignments,
            'metrics': candidate.metrics_json, 'change_summary': candidate.change_summary,
            'status': candidate.status, 'revision': candidate.row_version,
            'created_at': candidate.created_at.isoformat() + 'Z'}

    def load_events(session, event_ids):
        events = session.scalars(select(AdjustmentEvent).where(AdjustmentEvent.id.in_(event_ids)).with_for_update()).all()
        if len(events) != len(event_ids):
            raise AdjustmentProblem(404, 'NOT_FOUND', '部分调班事件不存在')
        if any(event.status != 'OPEN' for event in events):
            raise AdjustmentProblem(409, 'EVENT_NOT_OPEN', '只能为待处理缺岗生成方案')
        period_ids = {event.period_id for event in events}
        version_ids = {event.version_id for event in events}
        if len(period_ids) != 1 or len(version_ids) != 1:
            raise AdjustmentProblem(422, 'VALIDATION_FAILED', '只能同时处理同一周期、同一发布版本的缺岗')
        return events

    @app.get('/api/v1/adjustment-events')
    def adjustment_events(request: Request, status: str = Query('OPEN', pattern='^(OPEN|RESOLVED|SUPERSEDED|)$'),
                          period_id: int | None = Query(None, ge=1), manager=Depends(manager_dependency),
                          session: Session = Depends(db_dependency)):
        query = select(AdjustmentEvent)
        if status:
            query = query.where(AdjustmentEvent.status == status)
        if period_id is not None:
            query = query.where(AdjustmentEvent.period_id == period_id)
        events = session.scalars(query.order_by(AdjustmentEvent.id.desc()).limit(300)).all()
        return envelope(request, {'items': [event_data(session, event) for event in events], 'total': len(events)})

    @app.get('/api/v1/adjustment-events/{event_id}')
    def adjustment_event_detail(event_id: int, request: Request, manager=Depends(manager_dependency),
                                session: Session = Depends(db_dependency)):
        event = session.get(AdjustmentEvent, event_id)
        if not event:
            raise AdjustmentProblem(404, 'NOT_FOUND', '调班事件不存在')
        return envelope(request, event_data(session, event))

    @app.post('/api/v1/adjustment-candidates/generate', status_code=201)
    def generate_candidates(body: AdjustmentGenerate, request: Request, manager=Depends(manager_dependency),
                            session: Session = Depends(db_dependency)):
        events = load_events(session, body.event_ids)
        period = session.get(SchedulePeriod, events[0].period_id)
        current = session.get(ScheduleVersion, events[0].version_id)
        if not period or period.current_version_id != current.id or current.status != 'PUBLISHED':
            raise AdjustmentProblem(409, 'BASE_VERSION_CHANGED', '基准发布版本已变化，不能生成调班方案')
        event_shifts = [session.get(VersionShift, event.version_shift_id) for event in events]
        if any(shift_started(shift) for shift in event_shifts):
            raise AdjustmentProblem(409, 'SHIFT_STARTED', '涉及班次已经开始，不能生成调班方案')
        rule = session.get(RuleVersion, current.rule_version_id) if current.rule_version_id else None
        snapshot = build_snapshot(session, current, period, rule, require_draft=False)
        base_assignments = [{'shift_key': item['shift_key'], 'employee_id': item['employee_id'],
            'position_id': item['position_id'], 'locked': item['locked']} for item in version_data(session, current)['assignments']]
        base_keys={(item['shift_key'],item['employee_id'],item['position_id']) for item in base_assignments}
        locked=[]
        for item in body.locked_assignments:
            key=(item.shift_key,str(item.employee_id),str(item.position_id))
            if key not in base_keys:
                raise AdjustmentProblem(422, 'VALIDATION_FAILED', '锁定安排不属于当前发布版本')
            locked.append({'shift_key':item.shift_key,'employee_id':str(item.employee_id),'position_id':str(item.position_id),'locked':True})
        snapshot['locked_assignments']=[{'version_shift_id':next(shift['id'] for shift in snapshot['shifts'] if shift['shift_key']==item['shift_key']),
            'shift_key':item['shift_key'],'employee_id':item['employee_id'],'position_id':item['position_id'],'locked':True} for item in locked]
        result=solve_repair_candidates(snapshot,base_assignments,body.time_limit_seconds,3)
        task=SolverTask(period_id=period.id,draft_version_id=current.id,mode='REPAIR',
            state=result['status'],input_snapshot=snapshot,input_revision=scheduling_input_revision(session,period),
            draft_revision=current.row_version,time_limit_seconds=body.time_limit_seconds,attempt=1,
            result_json=result,created_by=manager.id,started_at=now(),finished_at=now())
        session.add(task); session.flush()
        for old in session.scalars(select(AdjustmentCandidate).where(
            AdjustmentCandidate.period_id==period.id,AdjustmentCandidate.base_version_id==current.id,
            AdjustmentCandidate.status=='PROPOSED')).all():
            old.status='EXPIRED'; old.row_version+=1
        candidates=[]
        locked_set={(item['shift_key'],item['employee_id'],item['position_id']) for item in locked}
        for item in result['candidates']:
            for assignment in item['assignments']:
                assignment['locked']=(assignment['shift_key'],assignment['employee_id'],assignment['position_id']) in locked_set
            candidate=AdjustmentCandidate(task_id=task.id,event_ids=[str(event.id) for event in events],
                period_id=period.id,base_version_id=current.id,input_revision=task.input_revision,sequence=item['sequence'],
                assignments=item['assignments'],metrics_json=item['metrics'],change_summary=item['change_summary'],created_by=manager.id)
            session.add(candidate); session.flush(); candidates.append(candidate_data(candidate))
        session.add(AuditEvent(actor_id=manager.id,action='adjustment.candidates_generated',entity_id=task.id,
            summary={'event_ids':[str(event.id) for event in events],'candidate_count':len(candidates)}))
        session.commit()
        return envelope(request,{'task_id':str(task.id),'state':result['status'],'issues':result['issues'],
            'candidates':candidates,'solve_ms':result['solve_ms']},'调班候选方案已生成')

    @app.get('/api/v1/adjustment-events/{event_id}/candidates')
    def event_candidates(event_id: int, request: Request, status: str = Query('PROPOSED', pattern='^(PROPOSED|APPLIED|DISCARDED|EXPIRED|)$'),
                         manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        event=session.get(AdjustmentEvent,event_id)
        if not event:
            raise AdjustmentProblem(404,'NOT_FOUND','调班事件不存在')
        query=select(AdjustmentCandidate)
        if status: query=query.where(AdjustmentCandidate.status==status)
        items=[item for item in session.scalars(query.order_by(AdjustmentCandidate.id.desc())).all()
            if str(event_id) in item.event_ids]
        return envelope(request,{'items':[candidate_data(item) for item in items]})

    @app.post('/api/v1/adjustment-candidates/{candidate_id}/apply')
    def apply_candidate(candidate_id: int, body: AdjustmentApply, request: Request,
                        manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        key=request.headers.get('idempotency-key','')
        if not 8<=len(key)<=64:
            raise AdjustmentProblem(422,'IDEMPOTENCY_REQUIRED','请提供有效的操作编号')
        record_key=f'{manager.id}:adjustment-apply:{key}'
        fingerprint=digest(json.dumps({'candidate_id':candidate_id,**body.model_dump()},sort_keys=True))
        record=session.get(IdempotencyRecord,record_key)
        if record:
            if record.request_hash!=fingerprint:
                raise AdjustmentProblem(409,'IDEMPOTENCY_CONFLICT','操作编号已用于其他请求')
            return envelope(request,record.response,'该调班方案已应用')
        guard=session.get(SchedulingGuard,1)
        if not guard:
            guard=SchedulingGuard(id=1,input_revision=1);session.add(guard);session.flush()
        session.scalar(select(SchedulingGuard).where(SchedulingGuard.id==1).with_for_update())
        candidate=session.scalar(select(AdjustmentCandidate).where(AdjustmentCandidate.id==candidate_id).with_for_update())
        if not candidate or candidate.status!='PROPOSED':
            raise AdjustmentProblem(409,'CANDIDATE_UNAVAILABLE','调班方案不存在或不可应用')
        period=session.scalar(select(SchedulePeriod).where(SchedulePeriod.id==candidate.period_id).with_for_update())
        current=session.get(ScheduleVersion,period.current_version_id) if period else None
        if not period or not current or current.id!=body.expected_base_version_id or current.id!=candidate.base_version_id:
            candidate.status='EXPIRED';candidate.row_version+=1;session.commit()
            raise AdjustmentProblem(409,'CANDIDATE_EXPIRED','基准版本已变化，调班方案失效')
        input_revision=scheduling_input_revision(session,period)
        if input_revision!=body.expected_input_revision or input_revision!=candidate.input_revision:
            candidate.status='EXPIRED';candidate.row_version+=1;session.commit()
            raise AdjustmentProblem(409,'INPUT_CHANGED','员工或时间输入已变化，请重新生成方案')
        events=load_events(session,[int(item) for item in candidate.event_ids])
        rule=session.get(RuleVersion,current.rule_version_id) if current.rule_version_id else None
        snapshot=build_snapshot(session,current,period,rule,require_draft=False)
        validation=validate_assignments(snapshot,candidate.assignments)
        if not validation['valid']:
            candidate.status='EXPIRED';candidate.row_version+=1;session.commit()
            raise AdjustmentProblem(409,'CANDIDATE_EXPIRED','调班方案已不满足当前约束',{'hard_conflicts':validation['hard_conflicts']})
        latest_no=session.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.period_id==period.id)) or 0
        draft=ScheduleVersion(period_id=period.id,version_no=latest_no+1,parent_id=current.id,status='DRAFT',
            rule_version_id=rule.id,created_by=manager.id,base_published_id=current.id,
            input_snapshot={'adjustment_candidate_id':str(candidate.id),'base_version_id':str(current.id)},
            input_revision=input_revision,metrics_json={})
        session.add(draft);session.flush()
        shift_by_key={}
        for source in session.scalars(select(VersionShift).where(VersionShift.version_id==current.id).order_by(VersionShift.work_date,VersionShift.start_time)).all():
            shift=VersionShift(version_id=draft.id,shift_key=source.shift_key,template_id=source.template_id,
                work_date=source.work_date,name=source.name,start_time=source.start_time,end_time=source.end_time,enabled=source.enabled)
            session.add(shift);session.flush();shift_by_key[shift.shift_key]=shift
            for demand in session.scalars(select(VersionDemand).where(VersionDemand.version_shift_id==source.id)).all():
                session.add(VersionDemand(version_shift_id=shift.id,position_id=demand.position_id,
                    position_name=demand.position_name,required_count=demand.required_count))
        employees={employee.id:employee for employee in session.scalars(select(Employee)).all()}
        positions={position.id:position for position in session.scalars(select(Position)).all()}
        for item in candidate.assignments:
            shift=shift_by_key[item['shift_key']];employee=employees[int(item['employee_id'])];position=positions[int(item['position_id'])]
            session.add(Assignment(version_id=draft.id,version_shift_id=shift.id,employee_id=employee.id,
                position_id=position.id,employee_name=employee.name,position_name=position.name,locked=item.get('locked',False)))
        publish_body=PublishRequest(expected_draft_revision=draft.row_version,expected_period_revision=period.row_version,
            base_published_version_id=current.id,expected_input_revision=input_revision)
        publish_result=publish_in_transaction(session,draft.id,publish_body,manager)
        candidate.status='APPLIED';candidate.row_version+=1
        for other in session.scalars(select(AdjustmentCandidate).where(
            AdjustmentCandidate.task_id==candidate.task_id,AdjustmentCandidate.id!=candidate.id,
            AdjustmentCandidate.status=='PROPOSED')).all():
            other.status='EXPIRED';other.row_version+=1
        for event in events:
            event.status='RESOLVED';event.resolved_version_id=int(publish_result['version_id']);event.resolved_at=now()
        session.add(AuditEvent(actor_id=manager.id,action='adjustment.applied',entity_id=candidate.id,
            summary={'result_version_id':publish_result['version_id'],'event_ids':candidate.event_ids}))
        response={'candidate_id':str(candidate.id),'status':'APPLIED','result_version_id':publish_result['version_id'],
            'period_revision':publish_result['period_revision'],'input_revision':input_revision}
        record_outbox_event(session,'adjustment.applied',candidate.id,response)
        session.add(IdempotencyRecord(key=record_key,request_hash=fingerprint,response=response))
        session.commit()
        return envelope(request,response,'调班方案已应用并发布新版本')

    @app.post('/api/v1/adjustment-candidates/{candidate_id}/discard')
    def discard_candidate(candidate_id: int, body: AdjustmentCandidateDiscard, request: Request,
                          manager=Depends(manager_dependency), session: Session = Depends(db_dependency)):
        candidate=session.scalar(select(AdjustmentCandidate).where(AdjustmentCandidate.id==candidate_id).with_for_update())
        if not candidate: raise AdjustmentProblem(404,'NOT_FOUND','调班方案不存在')
        if candidate.row_version!=body.expected_revision: raise AdjustmentProblem(409,'VERSION_CONFLICT','方案状态已变化')
        if candidate.status!='PROPOSED': raise AdjustmentProblem(409,'CANDIDATE_UNAVAILABLE','只有待选方案可以弃用')
        candidate.status='DISCARDED';candidate.row_version+=1
        session.commit()
        return envelope(request,candidate_data(candidate),'调班方案已弃用')
