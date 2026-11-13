import hmac, secrets, json, uuid, threading, sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, Response, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import create_engine, select, update, delete, func, text, exists
from sqlalchemy.orm import Session, aliased
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from .config import Settings
from .models import User, Employee, Skill, Position, EmployeeSkill, PositionSkill, ShiftTemplate, TemplateDemand, SchedulePeriod, RuleVersion, ScheduleVersion, VersionShift, VersionDemand, SolverTask, Assignment, SchedulingGuard, OutboxEvent, StoreSetting, AvailabilityProfile, AvailabilityWindow, AvailabilityOverride, OverrideWindow, PreferenceSubmission, Preference, AuthSession, ResetRequest, AuditEvent, IdempotencyRecord, now
from .schemas import Login, Register, ChangePassword, AccountName, EmployeeInput, EmployeeUpdate, EmployeeStatusChange, QualificationInput, QualificationUpdate, QualificationSkillSet, ShiftTemplateInput, ShiftTemplateUpdate, PeriodInput, DraftCreate, VersionShiftsUpdate, AssignmentReplace, AssignmentValidation, PublishRequest, CopyVersionToDraft, DiscardVersion, WeeklyAvailabilityUpdate, AvailabilityOverrideUpdate, AvailabilityOverrideDelete, PreferenceUpdate, ProxiedWeeklyAvailabilityUpdate, ProxiedAvailabilityOverrideUpdate, ProxiedAvailabilityOverrideDelete, ProxiedPreferenceUpdate, RuleVersionInput, SolverTaskCreate, StoreSettingUpdate, Review, PasswordReset, ManagedAccountCreate, AccountStatusChange
from .solver import solve_snapshot
from .validation import validate_assignments,eligible_employees
from .shared import current_published_version,employee_published_assignments,outbox_events,acknowledge_outbox_event,audit_events,approved_unavailability
from .leave import register_leave_routes
from .swap import register_swap_routes
from .notifications import register_notification_routes, start_notification_worker
from .adjustment import register_adjustment_routes
from .reports import register_report_routes
from .settings import register_settings_routes
from .ai_service import DeepSeekProvider,register_ai_routes
from .security import passwords, DUMMY_HASH, digest, csrf_token, csrf_valid, RateLimiter

class Problem(Exception):
    def __init__(self,status,code,message,data=None):
        self.status,self.code,self.message,self.data = status,code,message,data


def execute_solver_task(engine,task_id):
    with Session(engine) as session:
        task=session.scalar(select(SolverTask).where(SolverTask.id==task_id).with_for_update())
        if not task or task.state!='QUEUED': return
        task.state='RUNNING'; task.worker_id=f'solver-{secrets.token_hex(8)}'
        task.started_at=now(); task.lease_until=now()+timedelta(seconds=task.time_limit_seconds+60)
        task.attempt+=1; task.row_version+=1
        snapshot=task.input_snapshot; time_limit=task.time_limit_seconds
        session.commit()
    try:
        result=solve_snapshot(snapshot,time_limit)
    except Exception:
        result={'status':'FAILED','issues':[{'code':'SOLVER_EXCEPTION','message':'求解执行异常，请联系管理员检查服务日志'}],
            'assignments':[],'metrics':{},'solve_ms':0}
    with Session(engine) as session:
        task=session.scalar(select(SolverTask).where(SolverTask.id==task_id).with_for_update())
        if not task or task.state!='RUNNING': return
        version=session.scalar(select(ScheduleVersion).where(ScheduleVersion.id==task.draft_version_id).with_for_update())
        task.finished_at=now(); task.lease_until=None; task.row_version+=1
        if not version or version.row_version!=task.draft_revision:
            task.state='FAILED'; task.error_code='DRAFT_CHANGED'; task.error_message='排班草稿在求解期间已变化，请重新生成'
            task.result_json={'status':'FAILED','issues':[{'code':'DRAFT_CHANGED','message':task.error_message}],
                'assignments':[],'metrics':{},'solve_ms':result.get('solve_ms',0)}
            session.commit(); return
        if result['status'] in {'OPTIMAL','FEASIBLE'}:
            session.execute(delete(Assignment).where(Assignment.version_id==version.id))
            locked_keys={(item['version_shift_id'],item['employee_id'],item['position_id']) for item in snapshot.get('locked_assignments',[])}
            for item in result.get('assignments',[]):
                is_locked=(item['version_shift_id'],item['employee_id'],item['position_id']) in locked_keys
                item['locked']=is_locked
                session.add(Assignment(version_id=version.id,version_shift_id=int(item['version_shift_id']),
                    employee_id=int(item['employee_id']),position_id=int(item['position_id']),
                    employee_name=item['employee_name'],position_name=item['position_name'],locked=is_locked))
            version.source_task_id=task.id
            version.metrics_json={**(version.metrics_json or {}),'solver':result.get('metrics',{})}
            version.input_revision=task.input_revision
            version.row_version+=1
            result['applied_revision']=version.row_version
        task.state=result['status']; task.result_json=result
        if result['status']=='FAILED':
            issue=(result.get('issues') or [{}])[0]
            task.error_code=issue.get('code','SOLVER_FAILED'); task.error_message=issue.get('message','求解执行失败')
        else:
            task.error_code=None; task.error_message=None
        session.commit()

def create_app(settings=None, test_engine=None, ai_provider=None):
    settings = settings or Settings()
    ai_provider = ai_provider or DeepSeekProvider(settings)
    app = FastAPI(title='智能排班与动态调班系统', version='0.1.0', docs_url='/api/docs', openapi_url='/api/openapi.json', redoc_url=None)
    engine = test_engine or create_engine(settings.url, pool_pre_ping=True, connect_args={'connect_timeout':3})
    app.state.engine = engine
    app.state.settings = settings
    limiter = RateLimiter()
    configured = test_engine is not None or bool(settings.db_password.get_secret_value())
    secret = settings.csrf_secret.get_secret_value()
    origins = set(settings.allowed_origins.split(','))

    def envelope(request,data=None,message='操作成功',code='OK'):
        return {'code':code,'message':message,'data':data or {},'trace_id':getattr(request.state,'trace_id','')}

    @app.exception_handler(Problem)
    async def problem(request,exc):
        return JSONResponse(envelope(request,data=exc.data,message=exc.message,code=exc.code), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):
        errors = [{'field':'.'.join(str(p) for p in e['loc'][1:]),'message':'字段格式不正确或超出允许范围'} for e in exc.errors()]
        return JSONResponse(envelope(request,{'errors':errors},'请检查填写内容与密码确认','VALIDATION_FAILED'),status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request,exc):
        return JSONResponse(envelope(request,message='接口不存在' if exc.status_code == 404 else '请求方式不正确',code='HTTP_ERROR'),status_code=exc.status_code)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request,exc):
        # Deliberately do not log SQL parameters: these may include credential hashes.
        return JSONResponse(envelope(request,message='数据库暂不可用，请检查本地配置和迁移状态',code='DATABASE_UNAVAILABLE'),status_code=503)

    @app.middleware('http')
    async def protections(request,call_next):
        request.state.trace_id = secrets.token_hex(8)
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            if len(secret) < 32:
                return JSONResponse(envelope(request,message='服务端安全配置尚未完成',code='SETUP_REQUIRED'),status_code=503)
            origin = request.headers.get('origin')
            token = request.headers.get('x-csrf-token','')
            cookie = request.cookies.get('schedule_csrf','')
            if origin not in origins or not cookie or not hmac.compare_digest(token,cookie) or not csrf_valid(token,secret):
                return JSONResponse(envelope(request,message='请求验证已失效，请刷新页面后重试',code='CSRF_FAILED'),status_code=403)
            if request.url.path.startswith('/api/v1/auth/'):
                ip = request.client.host if request.client else 'local'
                if not limiter.allow((ip,request.url.path)):
                    return JSONResponse(envelope(request,message='操作过于频繁，请一分钟后重试',code='RATE_LIMITED'),status_code=429)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Request-ID'] = request.state.trace_id
        return response

    def db():
        if not configured: raise Problem(503,'SETUP_REQUIRED','请先填写本地数据库配置并完成初始化')
        with Session(engine) as session:
            yield session

    def identity(request: Request, session: Session = Depends(db)):
        token = request.cookies.get('schedule_session','')
        auth = session.scalar(select(AuthSession).where(AuthSession.token_hash==digest(token), AuthSession.revoked_at.is_(None), AuthSession.expires_at>now())) if token else None
        user = session.get(User,auth.user_id) if auth else None
        if not user or user.status == 'DISABLED': raise Problem(401,'UNAUTHENTICATED','请先登录')
        if user.must_change_password and user.temporary_password_expires_at and user.temporary_password_expires_at <= now():
            raise Problem(401,'PASSWORD_EXPIRED','临时密码已过期，请联系管理员')
        return user,auth

    def manager(pair=Depends(identity)):
        user,auth = pair
        if user.status!='ACTIVE' or user.role!='MANAGER' or user.must_change_password or auth.scope!='BUSINESS':
            raise Problem(403,'FORBIDDEN','没有访问权限')
        return user

    def business_user(pair=Depends(identity)):
        user,auth = pair
        if user.status!='ACTIVE' or user.must_change_password or auth.scope!='BUSINESS':
            raise Problem(403,'FORBIDDEN','请先完成账号审核或密码修改')
        return user

    def user_data(user,scope=None):
        return {'id':str(user.id),'name':user.display_name,'username':user.username,'role':user.role,'status':user.status,'revision':user.row_version,'review_note':user.review_note,'must_change_password':user.must_change_password,'session_scope':scope}

    def employee_data(e):
        return {'id':str(e.id),'employee_no':e.employee_no,'name':e.name,'status':e.status,'employment_type':e.employment_type,'weekly_limit_minutes':e.weekly_limit_minutes,'revision':e.row_version,'bound':e.user_id is not None}

    def skill_data(skill):
        return {'id':str(skill.id),'code':skill.code,'name':skill.name,'active':skill.active,'revision':skill.row_version}

    def skills_for(session,employee_id):
        return session.scalars(select(Skill).join(EmployeeSkill,EmployeeSkill.skill_id==Skill.id).where(EmployeeSkill.employee_id==employee_id).order_by(Skill.name,Skill.id)).all()

    def skills_for_position(session,position_id):
        return session.scalars(select(Skill).join(PositionSkill,PositionSkill.skill_id==Skill.id).where(PositionSkill.position_id==position_id).order_by(Skill.name,Skill.id)).all()

    def position_data(position,required_skills):
        return {'id':str(position.id),'code':position.code,'name':position.name,'active':position.active,'revision':position.row_version,'required_skills':[skill_data(skill) for skill in required_skills]}

    def employee_detail_data(session,employee):
        skills=skills_for(session,employee.id)
        skill_ids={skill.id for skill in skills}
        positions=[]
        for position in session.scalars(select(Position).where(Position.active.is_(True)).order_by(Position.name,Position.id)).all():
            required=skills_for_position(session,position.id)
            if {skill.id for skill in required}.issubset(skill_ids):
                positions.append(position_data(position,required))
        return {**employee_data(employee),'skills':[skill_data(skill) for skill in skills],'qualified_positions':positions}

    def template_data(session,template):
        rows=session.execute(select(TemplateDemand,Position).join(Position,TemplateDemand.position_id==Position.id).where(TemplateDemand.template_id==template.id).order_by(Position.name,Position.id)).all()
        return {
            'id':str(template.id),'code':template.code,'name':template.name,
            'start_time':template.start_time.isoformat(timespec='minutes'),
            'end_time':template.end_time.isoformat(timespec='minutes'),
            'active':template.active,'revision':template.row_version,
            'demands':[{'position_id':str(demand.position_id),'position_name':position.name,'position_active':position.active,'required_count':demand.required_count} for demand,position in rows]
        }

    def version_metrics(shifts):
        enabled=[shift for shift in shifts if shift['enabled']]
        total_positions=sum(sum(demand['required_count'] for demand in shift['demands']) for shift in enabled)
        required_minutes=0
        for shift in enabled:
            start_hour,start_minute=map(int,shift['start_time'].split(':')[:2])
            end_hour,end_minute=map(int,shift['end_time'].split(':')[:2])
            duration=(end_hour*60+end_minute)-(start_hour*60+start_minute)
            required_minutes+=duration*sum(demand['required_count'] for demand in shift['demands'])
        return {'enabled_shifts':len(enabled),'total_positions':total_positions,'required_minutes':required_minutes,'required_hours':round(required_minutes/60,2)}

    def version_data(session,version):
        shift_rows=session.scalars(select(VersionShift).where(VersionShift.version_id==version.id).order_by(VersionShift.work_date,VersionShift.start_time,VersionShift.id)).all()
        shifts=[]
        for shift in shift_rows:
            demand_rows=session.execute(select(VersionDemand,Position).join(Position,VersionDemand.position_id==Position.id).where(VersionDemand.version_shift_id==shift.id).order_by(Position.name,Position.id)).all()
            shifts.append({
                'id':str(shift.id),'shift_key':shift.shift_key,
                'template_id':str(shift.template_id) if shift.template_id else None,
                'work_date':shift.work_date.isoformat(),'name':shift.name,
                'start_time':shift.start_time.isoformat(timespec='minutes'),
                'end_time':shift.end_time.isoformat(timespec='minutes'),
                'enabled':shift.enabled,
                'demands':[{'position_id':str(demand.position_id),'position_name':demand.position_name,'position_active':position.active,'required_count':demand.required_count} for demand,position in demand_rows]
            })
        shift_by_id={item['id']:item['shift_key'] for item in shifts}
        assignment_rows=session.scalars(select(Assignment).where(Assignment.version_id==version.id).order_by(Assignment.version_shift_id,Assignment.position_id,Assignment.employee_id)).all()
        assignments=[{'id':str(item.id),'shift_key':shift_by_id.get(str(item.version_shift_id)),
            'employee_id':str(item.employee_id),'employee_name':item.employee_name,
            'position_id':str(item.position_id),'position_name':item.position_name,'locked':item.locked}
            for item in assignment_rows]
        metrics=version_metrics(shifts)
        solver_metrics=(version.metrics_json or {}).get('solver')
        if solver_metrics is not None: metrics['solver']=solver_metrics
        return {
            'id':str(version.id),'period_id':str(version.period_id),'version_no':version.version_no,
            'status':version.status,'revision':version.row_version,'input_revision':version.input_revision,
            'rule_version_id':str(version.rule_version_id) if version.rule_version_id else None,
            'base_published_id':str(version.base_published_id) if version.base_published_id else None,
            'created_at':timestamp(version.created_at),'published_at':timestamp(version.published_at),
            'published_by':str(version.published_by) if version.published_by else None,
            'shifts':shifts,'assignments':assignments,'metrics':metrics
        }

    def version_summary_data(session,version):
        publisher=session.get(User,version.published_by) if version.published_by else None
        return {'id':str(version.id),'period_id':str(version.period_id),'version_no':version.version_no,
            'status':version.status,'revision':version.row_version,'input_revision':version.input_revision,
            'rule_version_id':str(version.rule_version_id) if version.rule_version_id else None,
            'created_at':timestamp(version.created_at),'published_at':timestamp(version.published_at),
            'published_by_name':publisher.display_name if publisher else None,'metrics':version.metrics_json or {}}

    def version_content_map(session,version):
        data=version_data(session,version)
        assignments=defaultdict(list)
        for item in data['assignments']:
            assignments[item['shift_key']].append((item['employee_id'],item['position_id'],item['locked']))
        result={}
        for shift in data['shifts']:
            result[shift['shift_key']]={
                'work_date':shift['work_date'],'name':shift['name'],'start_time':shift['start_time'],'end_time':shift['end_time'],
                'enabled':shift['enabled'],
                'demands':sorted((item['position_id'],item['required_count']) for item in shift['demands']),
                'assignments':sorted(assignments.get(shift['shift_key'],[]))
            }
        return result

    def shift_started(shift):
        work_date=shift['work_date'] if isinstance(shift,dict) else shift.work_date.isoformat()
        start_time=shift['start_time'] if isinstance(shift,dict) else shift.start_time.isoformat(timespec='minutes')
        local=datetime.fromisoformat(f"{work_date}T{start_time}:00").replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        return local<=datetime.now(ZoneInfo('Asia/Shanghai'))

    def period_data(session,period):
        latest=session.scalar(select(ScheduleVersion).where(ScheduleVersion.period_id==period.id,ScheduleVersion.status=='DRAFT').order_by(ScheduleVersion.version_no.desc()))
        return {
            'id':str(period.id),'week_start':period.week_start.isoformat(),
            'week_end':(period.week_start+timedelta(days=6)).isoformat(),
            'revision':period.row_version,
            'current_version_id':str(period.current_version_id) if period.current_version_id else None,
            'latest_draft':version_data(session,latest) if latest else None
        }

    def validate_demands(session,demands,require_active=False):
        position_ids=[item.position_id for item in demands]
        if not position_ids: return []
        positions=session.scalars(select(Position).where(Position.id.in_(position_ids)).order_by(Position.id)).all()
        if len(positions)!=len(position_ids) or (require_active and any(not position.active for position in positions)):
            raise Problem(409,'POSITION_UNAVAILABLE','岗位不存在或无法使用')
        by_id={position.id:position for position in positions}
        return [(by_id[item.position_id],item.required_count) for item in demands]

    def employee_for_user(session,user):
        employee=session.scalar(select(Employee).where(Employee.user_id==user.id))
        if not employee: raise Problem(404,'PROFILE_NOT_FOUND','尚未绑定员工档案')
        return employee

    def minutes_of(value):
        return value.hour*60+value.minute

    def minutes_label(value):
        return f'{value//60:02d}:{value%60:02d}'

    def window_payload(window):
        data={'start_time':window.start_time.isoformat(timespec='minutes'),'end_time':window.end_time.isoformat(timespec='minutes')}
        if hasattr(window,'weekday'): data['weekday']=window.weekday
        return data

    def subtract_windows(regular,blocks):
        intervals=[(minutes_of(start),minutes_of(end)) for start,end in regular]
        for block_start,block_end in blocks:
            start_min,start_max=minutes_of(block_start),minutes_of(block_end)
            remaining=[]
            for start,end in intervals:
                if start_max<=start or start_min>=end:
                    remaining.append((start,end))
                    continue
                if start_min>start: remaining.append((start,start_min))
                if start_max<end: remaining.append((start_max,end))
            intervals=remaining
        return intervals

    def availability_data(session,employee,date_from,date_to):
        if date_from>date_to or (date_to-date_from).days>366:
            raise Problem(422,'VALIDATION_FAILED','查询日期范围不正确')
        profiles=session.scalars(select(AvailabilityProfile).where(
            AvailabilityProfile.employee_id==employee.id,
            AvailabilityProfile.effective_from<=date_to,
            (AvailabilityProfile.effective_to.is_(None))|(AvailabilityProfile.effective_to>=date_from)
        ).order_by(AvailabilityProfile.effective_from)).all()
        profile_payloads=[]
        profile_windows={}
        for profile in profiles:
            windows=session.scalars(select(AvailabilityWindow).where(AvailabilityWindow.profile_id==profile.id).order_by(AvailabilityWindow.weekday,AvailabilityWindow.start_time)).all()
            profile_windows[profile.id]=windows
            profile_payloads.append({'id':str(profile.id),'effective_from':profile.effective_from.isoformat(),
                'effective_to':profile.effective_to.isoformat() if profile.effective_to else None,
                'revision':profile.row_version,'windows':[window_payload(window) for window in windows]})
        overrides=session.scalars(select(AvailabilityOverride).where(
            AvailabilityOverride.employee_id==employee.id,
            AvailabilityOverride.work_date>=date_from,
            AvailabilityOverride.work_date<=date_to
        ).order_by(AvailabilityOverride.work_date)).all()
        override_payloads=[]
        override_map={}
        for override in overrides:
            windows=session.scalars(select(OverrideWindow).where(OverrideWindow.override_id==override.id).order_by(OverrideWindow.start_time)).all()
            override_map[override.work_date]=(override,windows)
            override_payloads.append({'id':str(override.id),'work_date':override.work_date.isoformat(),'mode':override.mode,
                'revision':override.row_version,'windows':[window_payload(window) for window in windows]})
        all_profiles=session.scalars(select(AvailabilityProfile).where(AvailabilityProfile.employee_id==employee.id).order_by(AvailabilityProfile.effective_from)).all()
        days=[]
        current_date=date_from
        while current_date<=date_to:
            profile=next((item for item in reversed(all_profiles) if item.effective_from<=current_date and (item.effective_to is None or item.effective_to>=current_date)),None)
            regular=[]
            if profile:
                regular=[(window.start_time,window.end_time) for window in profile_windows.get(profile.id,[]) if window.weekday==current_date.isoweekday()]
            override_entry=override_map.get(current_date)
            source='REGULAR' if profile else 'NONE'
            if override_entry:
                override,windows=override_entry
                source='OVERRIDE'
                if override.mode=='REPLACE':
                    intervals=[(minutes_of(window.start_time),minutes_of(window.end_time)) for window in windows]
                else:
                    intervals=subtract_windows(regular,[(window.start_time,window.end_time) for window in windows])
            else:
                intervals=[(minutes_of(start),minutes_of(end)) for start,end in regular]
            days.append({'date':current_date.isoformat(),'weekday':current_date.isoweekday(),'source':source,
                'override_mode':override_entry[0].mode if override_entry else None,
                'windows':[{'start_time':minutes_label(start),'end_time':minutes_label(end)} for start,end in intervals]})
            current_date+=timedelta(days=1)
        return {'employee_id':str(employee.id),'from':date_from.isoformat(),'to':date_to.isoformat(),
            'profiles':profile_payloads,'overrides':override_payloads,'days':days}

    def save_weekly_availability(session,employee,body,actor,reason=None):
        if reason is not None:
            reason=reason.strip()
            if not reason: raise Problem(422,'VALIDATION_FAILED','请填写代录原因')
        latest=session.scalar(select(AvailabilityProfile).where(AvailabilityProfile.employee_id==employee.id).order_by(AvailabilityProfile.effective_from.desc()).with_for_update())
        expected=latest.row_version if latest else 0
        if body.expected_revision!=expected: raise Problem(409,'VERSION_CONFLICT','常规可用时间已变化，请刷新后重试')
        profile=session.scalar(select(AvailabilityProfile).where(AvailabilityProfile.employee_id==employee.id,AvailabilityProfile.effective_from==body.effective_from).with_for_update())
        if profile and profile.id!=latest.id:
            raise Problem(409,'EFFECTIVE_DATE_CONFLICT','只能修改最新生效的常规可用时间版本')
        if not profile:
            if latest and body.effective_from<=latest.effective_from:
                raise Problem(409,'EFFECTIVE_DATE_CONFLICT','新版本必须晚于当前最新生效日期')
            profile=AvailabilityProfile(employee_id=employee.id,effective_from=body.effective_from,effective_to=None)
            session.add(profile); session.flush()
            if latest:
                latest.effective_to=body.effective_from-timedelta(days=1)
                latest.row_version+=1
        else:
            profile.row_version+=1
            session.execute(delete(AvailabilityWindow).where(AvailabilityWindow.profile_id==profile.id))
        for window in body.windows:
            session.add(AvailabilityWindow(profile_id=profile.id,weekday=window.weekday,start_time=window.start_time,end_time=window.end_time))
        session.add(AuditEvent(actor_id=actor.id,action='availability.weekly_updated',entity_id=employee.id,
            summary={'effective_from':body.effective_from.isoformat(),'window_count':len(body.windows),'proxy':bool(reason),'reason':reason}))
        session.commit()
        return {'id':str(profile.id),'employee_id':str(employee.id),'effective_from':profile.effective_from.isoformat(),
            'effective_to':profile.effective_to.isoformat() if profile.effective_to else None,'revision':profile.row_version,
            'windows':[{'weekday':window.weekday,'start_time':window.start_time.isoformat(timespec='minutes'),'end_time':window.end_time.isoformat(timespec='minutes')} for window in body.windows]}

    def save_availability_override(session,employee,work_date,body,actor,reason=None):
        if reason is not None:
            reason=reason.strip()
            if not reason: raise Problem(422,'VALIDATION_FAILED','请填写代录原因')
        if work_date<datetime.now(ZoneInfo('Asia/Shanghai')).date() and reason is None:
            raise Problem(422,'VALIDATION_FAILED','不能修改过去的日期例外')
        override=session.scalar(select(AvailabilityOverride).where(AvailabilityOverride.employee_id==employee.id,AvailabilityOverride.work_date==work_date).with_for_update())
        expected=override.row_version if override else 0
        if body.expected_revision!=expected: raise Problem(409,'VERSION_CONFLICT','日期例外已变化，请刷新后重试')
        if not override:
            override=AvailabilityOverride(employee_id=employee.id,work_date=work_date,mode=body.mode)
            session.add(override); session.flush()
        else:
            override.mode=body.mode; override.row_version+=1
            session.execute(delete(OverrideWindow).where(OverrideWindow.override_id==override.id))
        for window in body.windows:
            session.add(OverrideWindow(override_id=override.id,start_time=window.start_time,end_time=window.end_time))
        session.add(AuditEvent(actor_id=actor.id,action='availability.override_updated',entity_id=employee.id,
            summary={'work_date':work_date.isoformat(),'mode':body.mode,'window_count':len(body.windows),'proxy':bool(reason),'reason':reason}))
        session.commit()
        return {'id':str(override.id),'employee_id':str(employee.id),'work_date':work_date.isoformat(),'mode':override.mode,
            'revision':override.row_version,'windows':[{'start_time':window.start_time.isoformat(timespec='minutes'),'end_time':window.end_time.isoformat(timespec='minutes')} for window in body.windows]}

    def preference_data(session,employee,period):
        submission=session.scalar(select(PreferenceSubmission).where(PreferenceSubmission.employee_id==employee.id,PreferenceSubmission.period_id==period.id))
        if not submission:
            return {'employee_id':str(employee.id),'period_id':str(period.id),'status':'NOT_SUBMITTED','exists':False,
                'revision':0,'submitted_at':None,'items':[]}
        rows=session.execute(select(Preference,ShiftTemplate).join(ShiftTemplate,Preference.shift_template_id==ShiftTemplate.id).where(Preference.submission_id==submission.id).order_by(Preference.work_date,ShiftTemplate.start_time)).all()
        return {'employee_id':str(employee.id),'period_id':str(period.id),'status':submission.status,'exists':True,
            'revision':submission.row_version,'submitted_at':timestamp(submission.submitted_at),
            'items':[{'id':str(preference.id),'work_date':preference.work_date.isoformat(),'template_id':str(preference.shift_template_id),
                'template_name':template.name,'kind':preference.kind,'weight':preference.weight} for preference,template in rows]}

    def save_preferences(session,employee,period,body,actor,reason=None):
        if reason is not None:
            reason=reason.strip()
            if not reason: raise Problem(422,'VALIDATION_FAILED','请填写代录原因')
        valid_dates={period.week_start+timedelta(days=day) for day in range(7)}
        template_ids={item.template_id for item in body.items}
        templates=session.scalars(select(ShiftTemplate).where(ShiftTemplate.id.in_(template_ids))).all() if template_ids else []
        if len(templates)!=len(template_ids): raise Problem(409,'TEMPLATE_UNAVAILABLE','偏好包含不存在或不可用的班次模板')
        if any(not template.active for template in templates): raise Problem(409,'TEMPLATE_UNAVAILABLE','不能为已停用班次提交新偏好')
        if any(item.work_date not in valid_dates for item in body.items): raise Problem(422,'VALIDATION_FAILED','偏好日期必须位于该周内')
        submission=session.scalar(select(PreferenceSubmission).where(PreferenceSubmission.employee_id==employee.id,PreferenceSubmission.period_id==period.id).with_for_update())
        expected=submission.row_version if submission else 0
        if body.expected_revision!=expected: raise Problem(409,'VERSION_CONFLICT','个人偏好已变化，请刷新后重试')
        if not submission:
            submission=PreferenceSubmission(employee_id=employee.id,period_id=period.id,status='DRAFT')
            session.add(submission); session.flush()
        else:
            submission.row_version+=1
            session.execute(delete(Preference).where(Preference.submission_id==submission.id))
        submission.status='SUBMITTED' if body.submit else 'DRAFT'
        submission.submitted_at=now() if body.submit else None
        for item in body.items:
            session.add(Preference(submission_id=submission.id,work_date=item.work_date,shift_template_id=item.template_id,kind=item.kind,weight=item.weight))
        session.add(AuditEvent(actor_id=actor.id,action='preferences.saved',entity_id=employee.id,
            summary={'period_id':str(period.id),'status':submission.status,'item_count':len(body.items),'proxy':bool(reason),'reason':reason}))
        session.commit()
        return preference_data(session,employee,period)

    def delete_availability_override(session,employee,work_date,expected,actor,reason=None):
        if reason is not None:
            reason=reason.strip()
            if not reason: raise Problem(422,'VALIDATION_FAILED','请填写代录原因')
        override=session.scalar(select(AvailabilityOverride).where(AvailabilityOverride.employee_id==employee.id,AvailabilityOverride.work_date==work_date).with_for_update())
        if not override: raise Problem(404,'NOT_FOUND','日期例外不存在')
        if override.row_version!=expected: raise Problem(409,'VERSION_CONFLICT','日期例外已变化，请刷新后重试')
        session.execute(delete(OverrideWindow).where(OverrideWindow.override_id==override.id))
        session.delete(override)
        session.add(AuditEvent(actor_id=actor.id,action='availability.override_deleted',entity_id=employee.id,
            summary={'work_date':work_date.isoformat(),'proxy':bool(reason),'reason':reason}))
        session.commit()
        return {'employee_id':str(employee.id),'work_date':work_date.isoformat(),'deleted':True}

    def rule_version_data(session,rule,public=False):
        creator=session.get(User,rule.created_by)
        weights=rule.weights_json or {}
        data={'id':str(rule.id),'version_no':rule.version_no,'effective_week':rule.effective_week.isoformat(),
            'daily_shift_limit':rule.daily_shift_limit,'weekly_minutes_limit':rule.weekly_minutes_limit,
            'consecutive_days_limit':rule.consecutive_days_limit,'min_rest_minutes':rule.min_rest_minutes,
            'weights':{'preference':int(weights.get('preference',30)),'hours_balance':int(weights.get('hours_balance',20)),
                'evening_balance':int(weights.get('evening_balance',10))},
            'created_at':timestamp(rule.created_at),'schema_version':rule.schema_version}
        if not public:
            data['created_by']=str(rule.created_by); data['created_by_name']=creator.display_name if creator else None
        return data

    def effective_rule_version(session,week_start):
        return session.scalar(select(RuleVersion).where(RuleVersion.effective_week<=week_start).order_by(RuleVersion.effective_week.desc(),RuleVersion.version_no.desc()))

    def scheduling_input_revision(session,period):
        employees=[]
        for employee in session.scalars(select(Employee).order_by(Employee.id)).all():
            skills=sorted(str(item) for item in session.scalars(select(EmployeeSkill.skill_id).where(EmployeeSkill.employee_id==employee.id)).all())
            profiles=[]
            for profile in session.scalars(select(AvailabilityProfile).where(AvailabilityProfile.employee_id==employee.id).order_by(AvailabilityProfile.effective_from)).all():
                windows=[{'weekday':window.weekday,'start':window.start_time.isoformat(),'end':window.end_time.isoformat()} for window in session.scalars(select(AvailabilityWindow).where(AvailabilityWindow.profile_id==profile.id).order_by(AvailabilityWindow.weekday,AvailabilityWindow.start_time)).all()]
                profiles.append({'from':profile.effective_from.isoformat(),'to':profile.effective_to.isoformat() if profile.effective_to else None,'revision':profile.row_version,'windows':windows})
            overrides=[]
            for override in session.scalars(select(AvailabilityOverride).where(AvailabilityOverride.employee_id==employee.id).order_by(AvailabilityOverride.work_date)).all():
                windows=[{'start':window.start_time.isoformat(),'end':window.end_time.isoformat()} for window in session.scalars(select(OverrideWindow).where(OverrideWindow.override_id==override.id).order_by(OverrideWindow.start_time)).all()]
                overrides.append({'date':override.work_date.isoformat(),'mode':override.mode,'revision':override.row_version,'windows':windows})
            employees.append({'id':str(employee.id),'status':employee.status,'revision':employee.row_version,'weekly_limit':employee.weekly_limit_minutes,'skills':skills,'profiles':profiles,'overrides':overrides})
        preferences=[]
        for submission in session.scalars(select(PreferenceSubmission).where(PreferenceSubmission.period_id==period.id,PreferenceSubmission.status=='SUBMITTED').order_by(PreferenceSubmission.employee_id)).all():
            items=[{'date':item.work_date.isoformat(),'template':str(item.shift_template_id),'kind':item.kind,'weight':item.weight} for item in session.scalars(select(Preference).where(Preference.submission_id==submission.id).order_by(Preference.work_date,Preference.shift_template_id)).all()]
            preferences.append({'employee':str(submission.employee_id),'revision':submission.row_version,'items':items})
        positions=[]
        for position in session.scalars(select(Position).order_by(Position.id)).all():
            skill_ids=sorted(str(item) for item in session.scalars(select(PositionSkill.skill_id).where(PositionSkill.position_id==position.id)).all())
            positions.append({'id':str(position.id),'active':position.active,'revision':position.row_version,'skills':skill_ids})
        skills_catalog=[{'id':str(skill.id),'active':skill.active,'revision':skill.row_version} for skill in session.scalars(select(Skill).order_by(Skill.id)).all()]
        rule=effective_rule_version(session,period.week_start)
        payload={'employees':employees,'preferences':preferences,'positions':positions,'skills':skills_catalog,'rule':rule_version_data(session,rule) if rule else None}
        value=int(digest(json.dumps(payload,sort_keys=True,ensure_ascii=False))[:15],16)
        return value

    def build_solver_snapshot(session,draft,period,rule,require_draft=True):
        if require_draft and draft.status!='DRAFT': raise Problem(409,'DRAFT_REQUIRED','只有排班草稿可以执行求解')
        if not rule: raise Problem(409,'RULE_REQUIRED','该周没有可用的排班规则版本')
        draft_data=version_data(session,draft)
        enabled=[shift for shift in draft_data['shifts'] if shift['enabled']]
        if not any(sum(demand['required_count'] for demand in shift['demands'])>0 for shift in enabled):
            raise Problem(409,'INPUT_INCOMPLETE','本周没有可安排的启用岗位需求')
        for shift in enabled:
            for demand in shift['demands']:
                demand['skill_ids']=[str(skill_id) for skill_id in session.scalars(select(PositionSkill.skill_id).where(PositionSkill.position_id==int(demand['position_id']))).all()]
            start_hour,start_minute=map(int,shift['start_time'].split(':')[:2])
            end_hour,end_minute=map(int,shift['end_time'].split(':')[:2])
            shift['duration_minutes']=(end_hour*60+end_minute)-(start_hour*60+start_minute)
            shift['evening']=end_hour>=22
        employee_rows=session.execute(select(Employee,User).join(User,Employee.user_id==User.id).where(
            Employee.status=='ACTIVE',User.status=='ACTIVE')).all()
        if not employee_rows: raise Problem(409,'EMPLOYEES_REQUIRED','没有处于在岗状态且账号有效的员工')
        week_end=period.week_start+timedelta(days=6)
        employees=[]
        employee_ids=[employee.id for employee,account in employee_rows]
        external_unavailability=approved_unavailability(session,employee_ids,period.week_start,week_end)
        for employee,account in employee_rows:
            availability=availability_data(session,employee,period.week_start,week_end)
            blocks=[item for item in external_unavailability if str(item.get('employee_id'))==str(employee.id)]
            if blocks:
                for day in availability['days']:
                    day_blocks=[(time.fromisoformat(item['start_time']),time.fromisoformat(item['end_time']))
                        for item in blocks if item.get('work_date')==day['date']]
                    if day_blocks:
                        regular=[(time.fromisoformat(window['start_time']),time.fromisoformat(window['end_time'])) for window in day['windows']]
                        remaining=subtract_windows(regular,day_blocks)
                        day['windows']=[{'start_time':minutes_label(start),'end_time':minutes_label(end)} for start,end in remaining]
            preference=preference_data(session,employee,period)
            employees.append({
                'id':str(employee.id),'employee_no':employee.employee_no,'name':employee.name,
                'weekly_limit_minutes':employee.weekly_limit_minutes,
                'skills':[str(skill.id) for skill in skills_for(session,employee.id) if skill.active],
                'availability':availability['days'],
                'preferences':preference['items'] if preference['status']=='SUBMITTED' else []
            })
        shift_key_by_id={shift['id']:shift['shift_key'] for shift in enabled}
        locked_rows=session.scalars(select(Assignment).where(Assignment.version_id==draft.id,Assignment.locked.is_(True))).all()
        locked_assignments=[{'version_shift_id':str(item.version_shift_id),'shift_key':shift_key_by_id.get(str(item.version_shift_id)),
            'employee_id':str(item.employee_id),'position_id':str(item.position_id),'locked':True} for item in locked_rows]
        input_revision=scheduling_input_revision(session,period)
        week_dates=[(period.week_start+timedelta(days=offset)).isoformat() for offset in range(7)]
        return {
            'period_id':str(period.id),'draft_version_id':str(draft.id),'draft_revision':draft.row_version,
            'week_start':period.week_start.isoformat(),'week_dates':week_dates,'rule_version_id':str(rule.id),
            'rules':rule_version_data(session,rule),'shifts':enabled,'employees':employees,'locked_assignments':locked_assignments,
            'input_revision':input_revision
        }

    def solver_task_data(task):
        result=task.result_json or {}
        snapshot=task.input_snapshot or {}
        return {
            'id':str(task.id),'period_id':str(task.period_id),'draft_version_id':str(task.draft_version_id),
            'state':task.state,'mode':task.mode,'created_at':timestamp(task.created_at),
            'started_at':timestamp(task.started_at),'finished_at':timestamp(task.finished_at),
            'error_code':task.error_code,'error_message':task.error_message,
            'input_summary':{'employee_count':len(snapshot.get('employees',[])),'shift_count':len(snapshot.get('shifts',[])),
                'rule_version_id':snapshot.get('rule_version_id'),'time_limit_seconds':task.time_limit_seconds},
            'issues':result.get('issues',[]),'metrics':result.get('metrics',{}),'assignments':result.get('assignments',[]),
            'solve_ms':result.get('solve_ms'),'applied_revision':result.get('applied_revision')
        }

    def timestamp(value):
        return value.isoformat(timespec='seconds')+'Z' if value else None

    def reset_request_data(reset,account,processed_by=None):
        return {
            'id':str(reset.id),'user_id':str(account.id),'username':account.username,
            'name':account.display_name,'account_status':account.status,
            'account_revision':account.row_version,'status':reset.status,
            'requested_at':timestamp(reset.created_at),
            'processed_by':str(reset.processed_by) if reset.processed_by else None,
            'processed_by_name':processed_by.display_name if processed_by else None,
            'processed_at':timestamp(reset.processed_at),'note':reset.note
        }

    @app.get('/api/health')
    def health(request:Request):
        return envelope(request,{'service':'运行中','database_configured':configured,'stage':'基础框架'})

    @app.get('/api/ready')
    def ready(request:Request,session:Session=Depends(db)):
        session.execute(text('SELECT 1'))
        session.execute(select(User.id).limit(1))
        return envelope(request,{'database':'可连接','schema':'已初始化'})

    @app.get('/api/v1/auth/csrf')
    def csrf(request:Request,response:Response):
        if len(secret)<32: raise Problem(503,'SETUP_REQUIRED','服务端安全配置尚未完成')
        token = csrf_token(secret)
        response.set_cookie('schedule_csrf',token,httponly=True,secure=settings.cookie_secure,samesite='lax',path='/')
        return envelope(request,{'token':token})

    @app.post('/api/v1/auth/register',status_code=201)
    def register(body:Register,request:Request,session:Session=Depends(db)):
        user=User(username=body.username,display_name=body.name.strip(),password_hash=passwords.hash(body.password))
        session.add(user)
        try: session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'ACCOUNT_UNAVAILABLE','该账号暂不可用，请换一个账号')
        return envelope(request,{'user_id':str(user.id),'status':user.status},'注册成功，请等待管理员审核')

    @app.post('/api/v1/auth/login')
    def login(body:Login,request:Request,response:Response,session:Session=Depends(db)):
        user=session.scalar(select(User).where(User.username==body.username))
        valid=passwords.verify(body.password,user.password_hash if user else DUMMY_HASH)
        if not valid or not user or user.status=='DISABLED': raise Problem(401,'INVALID_CREDENTIALS','账号或密码不正确')
        if user.must_change_password and user.temporary_password_expires_at and user.temporary_password_expires_at<=now():
            raise Problem(401,'PASSWORD_EXPIRED','临时密码已过期，请联系管理员')
        old=request.cookies.get('schedule_session')
        if old: session.execute(update(AuthSession).where(AuthSession.token_hash==digest(old)).values(revoked_at=now()))
        scope='PASSWORD_CHANGE' if user.must_change_password else ('BUSINESS' if user.status=='ACTIVE' else 'ACCOUNT_STATUS')
        token=secrets.token_urlsafe(48)
        session.add(AuthSession(user_id=user.id,token_hash=digest(token),scope=scope,expires_at=now()+timedelta(hours=8)))
        session.commit()
        response.set_cookie('schedule_session',token,max_age=28800,httponly=True,secure=settings.cookie_secure,samesite='lax',path='/')
        return envelope(request,user_data(user,scope))

    @app.get('/api/v1/auth/me')
    def me(request:Request,pair=Depends(identity)): return envelope(request,user_data(pair[0],pair[1].scope))

    @app.post('/api/v1/auth/logout')
    def logout(request:Request,response:Response,session:Session=Depends(db)):
        session.execute(update(AuthSession).where(AuthSession.token_hash==digest(request.cookies.get('schedule_session',''))).values(revoked_at=now()))
        session.commit(); response.delete_cookie('schedule_session',path='/')
        return envelope(request,message='已退出登录')

    @app.post('/api/v1/auth/change-password')
    def change(body:ChangePassword,request:Request,response:Response,pair=Depends(identity),session:Session=Depends(db)):
        user=session.scalar(select(User).where(User.id==pair[0].id).with_for_update())
        if not passwords.verify(body.old_password,user.password_hash): raise Problem(400,'INVALID_PASSWORD','原密码不正确')
        user.password_hash=passwords.hash(body.new_password); user.must_change_password=False; user.temporary_password_expires_at=None; user.row_version+=1
        session.execute(update(AuthSession).where(AuthSession.user_id==user.id).values(revoked_at=now()))
        session.add(AuditEvent(actor_id=user.id,action='account.password_changed',entity_id=user.id))
        session.commit(); response.delete_cookie('schedule_session',path='/')
        return envelope(request,message='密码已修改，请重新登录')

    @app.post('/api/v1/auth/password-reset-requests')
    def reset_request(body:AccountName,request:Request,session:Session=Depends(db)):
        user=session.scalar(select(User).where(User.username==body.username).with_for_update())
        if user and not session.scalar(select(ResetRequest).where(ResetRequest.user_id==user.id,ResetRequest.status=='PENDING')):
            session.add(ResetRequest(user_id=user.id)); session.commit()
        return envelope(request,message='如账号有效，管理员将核实并协助处理；请联系门店管理员')

    @app.get('/api/v1/admin/accounts')
    def accounts(request:Request,status:str=Query('',pattern='^(|PENDING|ACTIVE|REJECTED|DISABLED)$'),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),user=Depends(manager),session:Session=Depends(db)):
        query=select(User)
        if status: query=query.where(User.status==status)
        total=session.scalar(select(func.count()).select_from(query.subquery()))
        items=session.scalars(query.order_by(User.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
        return envelope(request,{'items':[user_data(u) for u in items],'total':total,'page':page,'page_size':page_size})

    @app.post('/api/v1/admin/accounts',status_code=201)
    def create_managed_account(body:ManagedAccountCreate,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        key=request.headers.get('idempotency-key','')
        if not 8<=len(key)<=64: raise Problem(422,'IDEMPOTENCY_REQUIRED','请提供有效的操作编号')
        record_key=f'{actor.id}:create-account:{key}'
        fingerprint=digest(json.dumps(body.model_dump(),sort_keys=True))
        record=session.get(IdempotencyRecord,record_key)
        if record:
            if record.request_hash!=fingerprint: raise Problem(409,'IDEMPOTENCY_CONFLICT','操作编号已用于其他请求')
            return envelope(request,{**record.response,'temporary_password':None},'账号已创建，临时密码不会重复显示')
        if session.scalar(select(User.id).where(User.username==body.username)):
            raise Problem(409,'ACCOUNT_UNAVAILABLE','该账号暂不可用，请换一个账号')
        employee=None
        if body.employee_id is not None:
            employee=session.scalar(select(Employee).where(Employee.id==body.employee_id).with_for_update())
            if not employee or employee.user_id is not None or employee.status!='ACTIVE':
                raise Problem(409,'EMPLOYEE_UNAVAILABLE','员工档案无法绑定')
        temporary_password=secrets.token_urlsafe(24)
        expires_at=now()+timedelta(hours=24)
        user=User(username=body.username,display_name=body.name,role='EMPLOYEE',status='ACTIVE',
            password_hash=passwords.hash(temporary_password),must_change_password=True,
            temporary_password_expires_at=expires_at)
        session.add(user)
        try: session.flush()
        except IntegrityError:
            session.rollback(); raise Problem(409,'ACCOUNT_UNAVAILABLE','该账号暂不可用，请换一个账号')
        if employee: employee.user_id=user.id
        session.add(AuditEvent(actor_id=actor.id,action='account.created_by_manager',entity_id=user.id,summary={'employee_id':str(employee.id) if employee else None}))
        response_data={
            'user_id':str(user.id),'username':user.username,'name':user.display_name,
            'role':user.role,'status':user.status,'revision':user.row_version,
            'employee_id':str(employee.id) if employee else None,
            'expires_at':timestamp(expires_at),'already_processed':True
        }
        session.add(IdempotencyRecord(key=record_key,request_hash=fingerprint,response=response_data))
        try: session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'DATA_CONFLICT','账号创建冲突，请刷新后重试')
        return envelope(request,{**response_data,'temporary_password':temporary_password,'already_processed':False},'账号已创建，请安全交付一次性临时密码')

    @app.post('/api/v1/admin/accounts/{user_id}/review')
    def review(user_id:int,body:Review,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        key=request.headers.get('idempotency-key','')
        if not 8<=len(key)<=64: raise Problem(422,'IDEMPOTENCY_REQUIRED','请提供有效的操作编号')
        record_key=f'{actor.id}:review:{key}'
        fingerprint=digest(json.dumps({'id':user_id,**body.model_dump()},sort_keys=True))
        user=session.scalar(select(User).where(User.id==user_id).with_for_update())
        record=session.get(IdempotencyRecord,record_key)
        if record:
            if record.request_hash!=fingerprint: raise Problem(409,'IDEMPOTENCY_CONFLICT','操作编号已用于其他请求')
            return envelope(request,record.response)
        if not user: raise Problem(404,'NOT_FOUND','账号不存在')
        if user.status!='PENDING' or user.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','账号状态已变化，请刷新')
        if body.decision=='APPROVE':
            if body.employee_id is not None:
                employee=session.scalar(select(Employee).where(Employee.id==body.employee_id).with_for_update())
                if not employee or employee.user_id is not None or employee.status!='ACTIVE': raise Problem(409,'EMPLOYEE_UNAVAILABLE','员工档案无法绑定')
            else:
                employee=Employee(**body.new_employee.model_dump()); session.add(employee)
            employee.user_id=user.id; user.status='ACTIVE'
        else: user.status='REJECTED'
        user.review_note=body.note; user.reviewed_by=actor.id; user.reviewed_at=now(); user.row_version+=1
        session.execute(update(AuthSession).where(AuthSession.user_id==user.id).values(revoked_at=now()))
        data=user_data(user)
        if user.status=='ACTIVE':
            bound_employee=session.scalar(select(Employee).where(Employee.user_id==user.id))
            data['employee_id']=str(bound_employee.id) if bound_employee else None
        session.add(AuditEvent(actor_id=actor.id,action='account.reviewed',entity_id=user.id,summary={'decision':body.decision}))
        session.add(IdempotencyRecord(key=record_key,request_hash=fingerprint,response=data))
        try: session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'DATA_CONFLICT','员工编号或绑定关系冲突，请刷新后检查')
        return envelope(request,data)

    @app.patch('/api/v1/admin/accounts/{user_id}/status')
    def change_account_status(user_id:int,body:AccountStatusChange,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        # Lock managers in a stable order so two administrators cannot disable
        # one another in concurrent transactions and leave zero active managers.
        active_managers=session.scalars(select(User).where(User.role=='MANAGER',User.status=='ACTIVE').order_by(User.id).with_for_update()).all()
        active_manager_ids={manager.id for manager in active_managers}
        user=session.scalar(select(User).where(User.id==user_id).with_for_update())
        if not user: raise Problem(404,'NOT_FOUND','账号不存在')
        if user.status not in {'ACTIVE','DISABLED'}:
            raise Problem(409,'ACCOUNT_STATE_CONFLICT','待审核或未通过的账号不能直接停用或启用')
        if user.row_version!=body.expected_revision:
            raise Problem(409,'VERSION_CONFLICT','账号状态已变化，请刷新后重试')
        if user.status==body.status:
            return envelope(request,user_data(user),'账号状态未发生变化')
        if body.status=='DISABLED' and user.id in active_manager_ids and len(active_manager_ids)<=1:
            raise Problem(409,'LAST_MANAGER','不能停用最后一个有效管理员账号')
        previous=user.status
        user.status=body.status
        user.row_version+=1
        if body.status=='DISABLED':
            session.execute(update(AuthSession).where(AuthSession.user_id==user.id).values(revoked_at=now()))
        session.add(AuditEvent(actor_id=actor.id,action='account.status_changed',entity_id=user.id,summary={'from':previous,'to':body.status}))
        session.commit()
        return envelope(request,user_data(user),'账号已启用' if body.status=='ACTIVE' else '账号已停用，原会话已撤销')

    @app.get('/api/v1/admin/password-reset-requests')
    def reset_requests(request:Request,status:str=Query('PENDING',pattern='^(PENDING|PROCESSED|REJECTED)$'),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),actor=Depends(manager),session:Session=Depends(db)):
        processor=aliased(User)
        query=(select(ResetRequest,User,processor)
            .join(User,ResetRequest.user_id==User.id)
            .outerjoin(processor,ResetRequest.processed_by==processor.id)
            .where(ResetRequest.status==status))
        total=session.scalar(select(func.count()).select_from(query.subquery()))
        rows=session.execute(query.order_by(ResetRequest.created_at.desc()).offset((page-1)*page_size).limit(page_size)).all()
        return envelope(request,{'items':[reset_request_data(reset,account,processed_by) for reset,account,processed_by in rows],'total':total,'page':page,'page_size':page_size})

    @app.post('/api/v1/admin/accounts/{user_id}/reset-password')
    def reset_password(user_id:int,body:PasswordReset,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        key=request.headers.get('idempotency-key','')
        if not 8<=len(key)<=64: raise Problem(422,'IDEMPOTENCY_REQUIRED','请提供有效的操作编号')
        record_key=f'{actor.id}:reset-password:{key}'
        fingerprint=digest(json.dumps({'user_id':user_id,**body.model_dump()},sort_keys=True))
        record=session.get(IdempotencyRecord,record_key)
        if record:
            if record.request_hash!=fingerprint: raise Problem(409,'IDEMPOTENCY_CONFLICT','操作编号已用于其他请求')
            return envelope(request,{**record.response,'temporary_password':None},'密码重置已完成，临时密码不会重复显示')
        user=session.scalar(select(User).where(User.id==user_id).with_for_update())
        if not user: raise Problem(404,'NOT_FOUND','账号不存在')
        if user.status!='ACTIVE': raise Problem(409,'ACCOUNT_NOT_ACTIVE','仅已启用的账号可以重置密码')
        if user.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','账号状态已变化，请刷新后重试')
        reset=None
        if body.request_id is not None:
            reset=session.get(ResetRequest,body.request_id,with_for_update=True)
            if not reset or reset.user_id!=user.id: raise Problem(404,'NOT_FOUND','重置申请不存在')
            if reset.status!='PENDING': raise Problem(409,'RESET_REQUEST_INVALID','该重置申请已处理，请刷新列表')
        temporary_password=secrets.token_urlsafe(24)
        expires_at=now()+timedelta(hours=24)
        user.password_hash=passwords.hash(temporary_password)
        user.must_change_password=True
        user.temporary_password_expires_at=expires_at
        user.row_version+=1
        session.execute(update(AuthSession).where(AuthSession.user_id==user.id).values(revoked_at=now()))
        if reset:
            reset.status='PROCESSED'; reset.processed_by=actor.id; reset.processed_at=now(); reset.note=body.verification_note
        session.add(AuditEvent(actor_id=actor.id,action='account.password_reset',entity_id=user.id,summary={'request_id':str(reset.id) if reset else None}))
        response_data={
            'user_id':str(user.id),'username':user.username,'revision':user.row_version,
            'expires_at':timestamp(expires_at),'request_id':str(reset.id) if reset else None,
            'already_processed':True
        }
        session.add(IdempotencyRecord(key=record_key,request_hash=fingerprint,response=response_data))
        session.commit()
        return envelope(request,{**response_data,'temporary_password':temporary_password,'already_processed':False},'临时密码已生成，请安全交付给已核实的账号本人')

    @app.get('/api/v1/employees')
    def employees(request:Request,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),search:str=Query('',max_length=64),status:str=Query('',pattern='^(|ACTIVE|INACTIVE)$'),position_id:int|None=Query(None,ge=1),user=Depends(manager),session:Session=Depends(db)):
        query=select(Employee)
        if search: query=query.where(Employee.name.contains(search,autoescape=True)|Employee.employee_no.contains(search,autoescape=True))
        if status: query=query.where(Employee.status==status)
        if position_id is not None:
            position=session.get(Position,position_id)
            if not position: raise Problem(404,'NOT_FOUND','岗位不存在')
            required_ids=session.scalars(select(PositionSkill.skill_id).where(PositionSkill.position_id==position_id)).all()
            for skill_id in required_ids:
                query=query.where(exists(select(EmployeeSkill.id).where(EmployeeSkill.employee_id==Employee.id,EmployeeSkill.skill_id==skill_id)))
        total=session.scalar(select(func.count()).select_from(query.subquery()))
        items=session.scalars(query.order_by(Employee.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
        return envelope(request,{'items':[employee_data(e) for e in items],'total':total,'page':page,'page_size':page_size})

    @app.post('/api/v1/employees',status_code=201)
    def add_employee(body:EmployeeInput,request:Request,user=Depends(manager),session:Session=Depends(db)):
        employee=Employee(**body.model_dump()); session.add(employee)
        try:
            session.flush(); session.add(AuditEvent(actor_id=user.id,action='employee.created',entity_id=employee.id)); session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'EMPLOYEE_NO_EXISTS','员工编号已存在')
        return envelope(request,employee_data(employee))

    @app.get('/api/v1/employees/{employee_id}')
    def employee_detail(employee_id:int,request:Request,user=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        return envelope(request,employee_detail_data(session,employee))

    @app.patch('/api/v1/employees/{employee_id}')
    def edit_employee(employee_id:int,body:EmployeeUpdate,request:Request,user=Depends(manager),session:Session=Depends(db)):
        employee=session.scalar(select(Employee).where(Employee.id==employee_id).with_for_update())
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        if employee.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','员工资料已变化，请刷新后重试')
        changes=body.model_dump(exclude={'expected_revision'},exclude_none=True)
        for field,value in changes.items(): setattr(employee,field,value)
        employee.row_version+=1
        session.add(AuditEvent(actor_id=user.id,action='employee.updated',entity_id=employee.id,summary={'fields':sorted(changes)}))
        try: session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'EMPLOYEE_NO_EXISTS','员工编号已存在')
        return envelope(request,employee_detail_data(session,employee),'员工资料已更新')

    @app.put('/api/v1/employees/{employee_id}/skills')
    def set_employee_skills(employee_id:int,body:QualificationSkillSet,request:Request,user=Depends(manager),session:Session=Depends(db)):
        employee=session.scalar(select(Employee).where(Employee.id==employee_id).with_for_update())
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        if employee.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','员工资料已变化，请刷新后重试')
        skills=session.scalars(select(Skill).where(Skill.id.in_(body.skill_ids),Skill.active.is_(True)).order_by(Skill.id).with_for_update()).all() if body.skill_ids else []
        if len(skills)!=len(body.skill_ids): raise Problem(409,'SKILL_UNAVAILABLE','包含不存在或已停用的技能')
        session.execute(delete(EmployeeSkill).where(EmployeeSkill.employee_id==employee.id))
        for skill in skills: session.add(EmployeeSkill(employee_id=employee.id,skill_id=skill.id))
        employee.row_version+=1
        session.add(AuditEvent(actor_id=user.id,action='employee.skills_changed',entity_id=employee.id,summary={'skill_ids':[str(skill.id) for skill in skills]}))
        session.commit()
        return envelope(request,employee_detail_data(session,employee),'员工技能已更新')

    @app.patch('/api/v1/employees/{employee_id}/status')
    def change_employee_status(employee_id:int,body:EmployeeStatusChange,request:Request,user=Depends(manager),session:Session=Depends(db)):
        employee=session.scalar(select(Employee).where(Employee.id==employee_id).with_for_update())
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        if employee.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','员工资料已变化，请刷新后重试')
        if employee.status==body.status:
            return envelope(request,{'employee':employee_data(employee),'affected_future_assignments':0,'affected_periods':[]},'员工状态未发生变化')
        previous=employee.status
        employee.status=body.status
        employee.row_version+=1
        session.add(AuditEvent(actor_id=user.id,action='employee.status_changed',entity_id=employee.id,summary={'from':previous,'to':body.status}))
        session.commit()
        return envelope(request,{'employee':employee_data(employee),'affected_future_assignments':0,'affected_periods':[]},'员工已停用' if body.status=='INACTIVE' else '员工已启用')

    @app.get('/api/v1/skills')
    def skills(request:Request,active:bool|None=Query(None),page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=100),user=Depends(business_user),session:Session=Depends(db)):
        query=select(Skill)
        if user.role!='MANAGER': query=query.where(Skill.active.is_(True))
        elif active is not None: query=query.where(Skill.active==active)
        total=session.scalar(select(func.count()).select_from(query.subquery()))
        items=session.scalars(query.order_by(Skill.active.desc(),Skill.name,Skill.id).offset((page-1)*page_size).limit(page_size)).all()
        return envelope(request,{'items':[skill_data(skill) for skill in items],'total':total,'page':page,'page_size':page_size})

    @app.post('/api/v1/skills',status_code=201)
    def create_skill(body:QualificationInput,request:Request,user=Depends(manager),session:Session=Depends(db)):
        skill=Skill(**body.model_dump()); session.add(skill)
        try:
            session.flush(); session.add(AuditEvent(actor_id=user.id,action='skill.created',entity_id=skill.id)); session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'CODE_EXISTS','技能编码已存在')
        return envelope(request,skill_data(skill))

    @app.patch('/api/v1/skills/{skill_id}')
    def update_skill(skill_id:int,body:QualificationUpdate,request:Request,user=Depends(manager),session:Session=Depends(db)):
        skill=session.scalar(select(Skill).where(Skill.id==skill_id).with_for_update())
        if not skill: raise Problem(404,'NOT_FOUND','技能不存在')
        if skill.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','技能已变化，请刷新后重试')
        skill.name=body.name; skill.active=body.active; skill.row_version+=1
        session.add(AuditEvent(actor_id=user.id,action='skill.updated',entity_id=skill.id,summary={'active':body.active}))
        session.commit()
        return envelope(request,skill_data(skill),'技能已更新')

    @app.get('/api/v1/positions')
    def positions(request:Request,active:bool|None=Query(None),page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=100),user=Depends(business_user),session:Session=Depends(db)):
        query=select(Position)
        if user.role!='MANAGER': query=query.where(Position.active.is_(True))
        elif active is not None: query=query.where(Position.active==active)
        total=session.scalar(select(func.count()).select_from(query.subquery()))
        items=session.scalars(query.order_by(Position.active.desc(),Position.name,Position.id).offset((page-1)*page_size).limit(page_size)).all()
        return envelope(request,{'items':[position_data(position,skills_for_position(session,position.id)) for position in items],'total':total,'page':page,'page_size':page_size})

    @app.post('/api/v1/positions',status_code=201)
    def create_position(body:QualificationInput,request:Request,user=Depends(manager),session:Session=Depends(db)):
        position=Position(**body.model_dump()); session.add(position)
        try:
            session.flush(); session.add(AuditEvent(actor_id=user.id,action='position.created',entity_id=position.id)); session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'CODE_EXISTS','岗位编码已存在')
        return envelope(request,position_data(position,[]))

    @app.patch('/api/v1/positions/{position_id}')
    def update_position(position_id:int,body:QualificationUpdate,request:Request,user=Depends(manager),session:Session=Depends(db)):
        position=session.scalar(select(Position).where(Position.id==position_id).with_for_update())
        if not position: raise Problem(404,'NOT_FOUND','岗位不存在')
        if position.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','岗位已变化，请刷新后重试')
        position.name=body.name; position.active=body.active; position.row_version+=1
        session.add(AuditEvent(actor_id=user.id,action='position.updated',entity_id=position.id,summary={'active':body.active}))
        session.commit()
        return envelope(request,position_data(position,skills_for_position(session,position.id)),'岗位已更新')

    @app.put('/api/v1/positions/{position_id}/skills')
    def set_position_skills(position_id:int,body:QualificationSkillSet,request:Request,user=Depends(manager),session:Session=Depends(db)):
        position=session.scalar(select(Position).where(Position.id==position_id).with_for_update())
        if not position: raise Problem(404,'NOT_FOUND','岗位不存在')
        if position.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','岗位已变化，请刷新后重试')
        skills=session.scalars(select(Skill).where(Skill.id.in_(body.skill_ids),Skill.active.is_(True)).order_by(Skill.id).with_for_update()).all() if body.skill_ids else []
        if len(skills)!=len(body.skill_ids): raise Problem(409,'SKILL_UNAVAILABLE','包含不存在或已停用的技能')
        session.execute(delete(PositionSkill).where(PositionSkill.position_id==position.id))
        for skill in skills: session.add(PositionSkill(position_id=position.id,skill_id=skill.id))
        position.row_version+=1
        session.add(AuditEvent(actor_id=user.id,action='position.skills_changed',entity_id=position.id,summary={'skill_ids':[str(skill.id) for skill in skills]}))
        session.commit()
        return envelope(request,position_data(position,skills_for_position(session,position.id)),'岗位技能已更新')

    @app.get('/api/v1/shift-templates')
    def shift_templates(request:Request,user=Depends(manager),session:Session=Depends(db)):
        items=session.scalars(select(ShiftTemplate).order_by(ShiftTemplate.active.desc(),ShiftTemplate.start_time,ShiftTemplate.id)).all()
        return envelope(request,{'items':[template_data(session,item) for item in items],'total':len(items),'page':1,'page_size':100})

    @app.post('/api/v1/shift-templates',status_code=201)
    def create_shift_template(body:ShiftTemplateInput,request:Request,user=Depends(manager),session:Session=Depends(db)):
        demands=validate_demands(session,body.demands,require_active=True)
        template=ShiftTemplate(code=body.code,name=body.name,start_time=body.start_time,end_time=body.end_time,active=True)
        session.add(template)
        try: session.flush()
        except IntegrityError:
            session.rollback(); raise Problem(409,'CODE_EXISTS','班次编码已存在')
        for position,count in demands: session.add(TemplateDemand(template_id=template.id,position_id=position.id,required_count=count))
        session.add(AuditEvent(actor_id=user.id,action='shift_template.created',entity_id=template.id))
        session.commit()
        return envelope(request,template_data(session,template))

    @app.patch('/api/v1/shift-templates/{template_id}')
    def update_shift_template(template_id:int,body:ShiftTemplateUpdate,request:Request,user=Depends(manager),session:Session=Depends(db)):
        template=session.scalar(select(ShiftTemplate).where(ShiftTemplate.id==template_id).with_for_update())
        if not template: raise Problem(404,'NOT_FOUND','班次模板不存在')
        if template.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','班次模板已变化，请刷新后重试')
        demands=validate_demands(session,body.demands,require_active=True)
        template.code=body.code; template.name=body.name; template.start_time=body.start_time; template.end_time=body.end_time
        template.active=body.active; template.row_version+=1
        session.execute(delete(TemplateDemand).where(TemplateDemand.template_id==template.id))
        for position,count in demands: session.add(TemplateDemand(template_id=template.id,position_id=position.id,required_count=count))
        session.add(AuditEvent(actor_id=user.id,action='shift_template.updated',entity_id=template.id,summary={'active':body.active}))
        try: session.commit()
        except IntegrityError:
            session.rollback(); raise Problem(409,'CODE_EXISTS','班次编码已存在')
        return envelope(request,template_data(session,template),'班次模板已更新，仅影响之后生成的排班周期')

    @app.post('/api/v1/periods',status_code=201)
    def create_period(body:PeriodInput,request:Request,user=Depends(manager),session:Session=Depends(db)):
        existing=session.scalar(select(SchedulePeriod).where(SchedulePeriod.week_start==body.week_start))
        if existing: raise Problem(409,'PERIOD_EXISTS','该周排班周期已存在')
        period=SchedulePeriod(week_start=body.week_start)
        session.add(period)
        try: session.flush()
        except IntegrityError:
            session.rollback(); raise Problem(409,'PERIOD_EXISTS','该周排班周期已存在')
        session.add(AuditEvent(actor_id=user.id,action='schedule_period.created',entity_id=period.id,summary={'week_start':body.week_start.isoformat()}))
        session.commit()
        return envelope(request,period_data(session,period))

    @app.get('/api/v1/periods')
    def periods(request:Request,date_from:date|None=Query(None,alias='from'),date_to:date|None=Query(None,alias='to'),user=Depends(manager),session:Session=Depends(db)):
        query=select(SchedulePeriod)
        if date_from: query=query.where(SchedulePeriod.week_start>=date_from)
        if date_to: query=query.where(SchedulePeriod.week_start<=date_to)
        items=session.scalars(query.order_by(SchedulePeriod.week_start.desc()).limit(200)).all()
        return envelope(request,{'items':[period_data(session,period) for period in items],'total':len(items),'page':1,'page_size':200})

    @app.get('/api/v1/period-options')
    def period_options(request:Request,user=Depends(business_user),session:Session=Depends(db)):
        items=session.scalars(select(SchedulePeriod).order_by(SchedulePeriod.week_start).limit(100)).all()
        return envelope(request,{'items':[{'id':str(period.id),'week_start':period.week_start.isoformat(),'week_end':(period.week_start+timedelta(days=6)).isoformat()} for period in items]})

    @app.get('/api/v1/shift-template-options')
    def shift_template_options(request:Request,user=Depends(business_user),session:Session=Depends(db)):
        items=session.scalars(select(ShiftTemplate).where(ShiftTemplate.active.is_(True)).order_by(ShiftTemplate.start_time,ShiftTemplate.id)).all()
        return envelope(request,{'items':[{'id':str(item.id),'name':item.name,'start_time':item.start_time.isoformat(timespec='minutes'),'end_time':item.end_time.isoformat(timespec='minutes')} for item in items]})

    @app.get('/api/v1/periods/{period_id}')
    def period_detail(period_id:int,request:Request,user=Depends(manager),session:Session=Depends(db)):
        period=session.get(SchedulePeriod,period_id)
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        return envelope(request,period_data(session,period))

    @app.post('/api/v1/periods/{period_id}/drafts',status_code=201)
    def create_period_draft(period_id:int,body:DraftCreate,request:Request,user=Depends(manager),session:Session=Depends(db)):
        period=session.scalar(select(SchedulePeriod).where(SchedulePeriod.id==period_id).with_for_update())
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        source_version=None
        source_period=None
        if body.source_version_id is not None:
            source_version=session.get(ScheduleVersion,body.source_version_id)
            if not source_version or source_version.status!='DRAFT': raise Problem(409,'SOURCE_UNAVAILABLE','复制来源草稿不存在或不可复制')
            source_period=session.get(SchedulePeriod,source_version.period_id)
        elif body.source_period_id is not None:
            source_period=session.get(SchedulePeriod,body.source_period_id)
            if not source_period: raise Problem(404,'NOT_FOUND','来源周期不存在')
            source_version=session.scalar(select(ScheduleVersion).where(ScheduleVersion.period_id==source_period.id,ScheduleVersion.status=='DRAFT').order_by(ScheduleVersion.version_no.desc()))
            if not source_version: raise Problem(409,'SOURCE_UNAVAILABLE','来源周期没有可复制的排班草稿')
        latest_no=session.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.period_id==period.id)) or 0
        rule_version=effective_rule_version(session,period.week_start)
        version=ScheduleVersion(period_id=period.id,version_no=latest_no+1,parent_id=source_version.id if source_version else None,
            status='DRAFT',rule_version_id=rule_version.id if rule_version else None,created_by=user.id,
            input_snapshot={'source_version_id':str(source_version.id) if source_version else None,
                            'source_period_id':str(source_period.id) if source_period else None,
                            'week_start':period.week_start.isoformat(),'rule_version_id':str(rule_version.id) if rule_version else None})
        session.add(version); session.flush()
        if source_version:
            delta_days=(period.week_start-source_period.week_start).days
            shifts=session.scalars(select(VersionShift).where(VersionShift.version_id==source_version.id).order_by(VersionShift.work_date,VersionShift.start_time,VersionShift.id)).all()
            for source_shift in shifts:
                shift_key=source_shift.shift_key if source_period.id==period.id else str(uuid.uuid4())
                shift=VersionShift(version_id=version.id,shift_key=shift_key,template_id=source_shift.template_id,
                    work_date=source_shift.work_date+timedelta(days=delta_days),name=source_shift.name,
                    start_time=source_shift.start_time,end_time=source_shift.end_time,enabled=source_shift.enabled)
                session.add(shift); session.flush()
                source_demands=session.scalars(select(VersionDemand).where(VersionDemand.version_shift_id==source_shift.id).order_by(VersionDemand.position_id)).all()
                for demand in source_demands:
                    session.add(VersionDemand(version_shift_id=shift.id,position_id=demand.position_id,position_name=demand.position_name,required_count=demand.required_count))
        else:
            templates=session.scalars(select(ShiftTemplate).where(ShiftTemplate.active.is_(True)).order_by(ShiftTemplate.start_time,ShiftTemplate.id)).all()
            if not templates: raise Problem(409,'TEMPLATES_REQUIRED','请先创建并启用至少一个班次模板')
            for day in range(7):
                work_date=period.week_start+timedelta(days=day)
                for template in templates:
                    shift=VersionShift(version_id=version.id,shift_key=str(uuid.uuid4()),template_id=template.id,
                        work_date=work_date,name=template.name,start_time=template.start_time,end_time=template.end_time,enabled=True)
                    session.add(shift); session.flush()
                    demands=session.execute(select(TemplateDemand,Position).join(Position,TemplateDemand.position_id==Position.id).where(TemplateDemand.template_id==template.id)).all()
                    for demand,position in demands:
                        session.add(VersionDemand(version_shift_id=shift.id,position_id=position.id,position_name=position.name,required_count=demand.required_count))
        session.flush()
        data=version_data(session,version)
        version.metrics_json=data['metrics']
        session.add(AuditEvent(actor_id=user.id,action='schedule_draft.created',entity_id=version.id,summary={'period_id':str(period.id),'source_version_id':str(source_version.id) if source_version else None}))
        session.commit()
        return envelope(request,version_data(session,version),'排班输入草稿已生成')

    @app.get('/api/v1/versions/{version_id}')
    def version_detail(version_id:int,request:Request,user=Depends(manager),session:Session=Depends(db)):
        version=session.get(ScheduleVersion,version_id)
        if not version: raise Problem(404,'NOT_FOUND','排班草稿不存在')
        return envelope(request,version_data(session,version))

    @app.get('/api/v1/versions/{version_id}/eligible-employees')
    def version_eligible_employees(version_id:int,request:Request,shift_key:str=Query(...,min_length=1,max_length=36),position_id:int=Query(...,ge=1),actor=Depends(manager),session:Session=Depends(db)):
        version=session.get(ScheduleVersion,version_id)
        if not version: raise Problem(404,'NOT_FOUND','排班草稿不存在')
        period=session.get(SchedulePeriod,version.period_id)
        rule=session.get(RuleVersion,version.rule_version_id) if version.rule_version_id else None
        snapshot=build_solver_snapshot(session,version,period,rule)
        assignments=version_data(session,version)['assignments']
        return envelope(request,{'items':eligible_employees(snapshot,shift_key,position_id,assignments)})

    @app.put('/api/v1/versions/{version_id}/assignments')
    def replace_assignments(version_id:int,body:AssignmentReplace,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        version=session.scalar(select(ScheduleVersion).where(ScheduleVersion.id==version_id).with_for_update())
        if not version: raise Problem(404,'NOT_FOUND','排班草稿不存在')
        if version.status!='DRAFT': raise Problem(409,'VERSION_LOCKED','只有草稿可以修改人员安排')
        if version.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','排班草稿已变化，请刷新后重试')
        shifts=session.scalars(select(VersionShift).where(VersionShift.version_id==version.id)).all()
        shift_by_key={shift.shift_key:shift for shift in shifts}
        prepared=[]
        for item in body.items:
            shift=shift_by_key.get(item.shift_key)
            employee=session.get(Employee,item.employee_id)
            position=session.get(Position,item.position_id)
            if not shift or not employee or not position:
                raise Problem(422,'VALIDATION_FAILED','人员安排包含不存在的班次、员工或岗位')
            demand=session.scalar(select(VersionDemand.id).where(VersionDemand.version_shift_id==shift.id,VersionDemand.position_id==position.id))
            if not demand: raise Problem(422,'VALIDATION_FAILED','岗位不属于该班次的需求')
            prepared.append((shift,employee,position,item.locked))
        session.execute(delete(Assignment).where(Assignment.version_id==version.id))
        for shift,employee,position,locked in prepared:
            session.add(Assignment(version_id=version.id,version_shift_id=shift.id,employee_id=employee.id,
                position_id=position.id,employee_name=employee.name,position_name=position.name,locked=locked))
        version.row_version+=1
        session.add(AuditEvent(actor_id=actor.id,action='assignments.replaced',entity_id=version.id,summary={'assignment_count':len(prepared),'locked_count':sum(1 for item in prepared if item[3])}))
        session.commit()
        return envelope(request,version_data(session,version),'人员安排已保存；业务冲突需统一校验后处理')

    @app.post('/api/v1/versions/{version_id}/validate')
    def validate_version(version_id:int,body:AssignmentValidation,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        version=session.get(ScheduleVersion,version_id)
        if not version: raise Problem(404,'NOT_FOUND','排班草稿不存在')
        if version.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','排班草稿已变化，请刷新后重试')
        period=session.get(SchedulePeriod,version.period_id)
        rule=session.get(RuleVersion,version.rule_version_id) if version.rule_version_id else None
        snapshot=build_solver_snapshot(session,version,period,rule)
        result=validate_assignments(snapshot,version_data(session,version)['assignments'])
        result['input_revision']=snapshot['input_revision']
        return envelope(request,result)

    @app.put('/api/v1/versions/{version_id}/shifts')
    def replace_version_shifts(version_id:int,body:VersionShiftsUpdate,request:Request,user=Depends(manager),session:Session=Depends(db)):
        version=session.scalar(select(ScheduleVersion).where(ScheduleVersion.id==version_id).with_for_update())
        if not version: raise Problem(404,'NOT_FOUND','排班草稿不存在')
        if version.status!='DRAFT': raise Problem(409,'VERSION_LOCKED','只有草稿可以修改')
        if version.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','排班草稿已变化，请刷新后重试')
        period=session.get(SchedulePeriod,version.period_id)
        valid_dates={period.week_start+timedelta(days=day) for day in range(7)}
        if any(shift.work_date not in valid_dates for shift in body.shifts): raise Problem(422,'VALIDATION_FAILED','班次日期必须位于该周内')
        keys=[shift.shift_key or str(uuid.uuid4()) for shift in body.shifts]
        if len(set(keys))!=len(keys): raise Problem(422,'VALIDATION_FAILED','班次键不能重复')
        template_ids={shift.template_id for shift in body.shifts if shift.template_id is not None}
        if template_ids:
            found=set(session.scalars(select(ShiftTemplate.id).where(ShiftTemplate.id.in_(template_ids))).all())
            if found!=template_ids: raise Problem(409,'TEMPLATE_UNAVAILABLE','班次模板不存在')
        prepared=[]
        for shift,key in zip(body.shifts,keys):
            prepared.append((shift,key,validate_demands(session,shift.demands,require_active=True)))
        old_ids=session.scalars(select(VersionShift.id).where(VersionShift.version_id==version.id)).all()
        if old_ids: session.execute(delete(VersionDemand).where(VersionDemand.version_shift_id.in_(old_ids)))
        session.execute(delete(VersionShift).where(VersionShift.version_id==version.id))
        for shift,key,demands in prepared:
            row=VersionShift(version_id=version.id,shift_key=key,template_id=shift.template_id,work_date=shift.work_date,
                name=shift.name,start_time=shift.start_time,end_time=shift.end_time,enabled=shift.enabled)
            session.add(row); session.flush()
            for position,count in demands:
                session.add(VersionDemand(version_shift_id=row.id,position_id=position.id,position_name=position.name,required_count=count))
        version.row_version+=1; version.input_revision+=1
        session.flush()
        data=version_data(session,version)
        version.metrics_json=data['metrics']
        session.add(AuditEvent(actor_id=user.id,action='schedule_draft.updated',entity_id=version.id,summary={'shift_count':len(body.shifts),**data['metrics']}))
        session.commit()
        return envelope(request,version_data(session,version),'本周班次与岗位需求已保存')

    @app.get('/api/v1/me/availability')
    def my_availability(request:Request,date_from:date=Query(alias='from'),date_to:date=Query(alias='to'),user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        return envelope(request,availability_data(session,employee,date_from,date_to))

    @app.put('/api/v1/me/availability/weekly')
    def update_my_weekly_availability(body:WeeklyAvailabilityUpdate,request:Request,user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        if employee.status!='ACTIVE': raise Problem(409,'EMPLOYEE_INACTIVE','已停用员工不能修改可用时间')
        return envelope(request,save_weekly_availability(session,employee,body,user),'常规可用时间已保存')

    @app.put('/api/v1/me/availability/overrides/{work_date}')
    def update_my_availability_override(work_date:date,body:AvailabilityOverrideUpdate,request:Request,user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        if employee.status!='ACTIVE': raise Problem(409,'EMPLOYEE_INACTIVE','已停用员工不能修改可用时间')
        return envelope(request,save_availability_override(session,employee,work_date,body,user),'日期例外已保存')

    @app.delete('/api/v1/me/availability/overrides/{work_date}')
    def delete_my_availability_override(work_date:date,body:AvailabilityOverrideDelete,request:Request,user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        if employee.status!='ACTIVE': raise Problem(409,'EMPLOYEE_INACTIVE','已停用员工不能修改可用时间')
        return envelope(request,delete_availability_override(session,employee,work_date,body.expected_revision,user),'日期例外已删除')

    @app.get('/api/v1/me/preferences/{period_id}')
    def my_preferences(period_id:int,request:Request,user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        period=session.get(SchedulePeriod,period_id)
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        return envelope(request,preference_data(session,employee,period))

    @app.put('/api/v1/me/preferences/{period_id}')
    def update_my_preferences(period_id:int,body:PreferenceUpdate,request:Request,user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        if employee.status!='ACTIVE': raise Problem(409,'EMPLOYEE_INACTIVE','已停用员工不能提交偏好')
        period=session.get(SchedulePeriod,period_id)
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        return envelope(request,save_preferences(session,employee,period,body,user),'个人偏好已保存')

    @app.get('/api/v1/employees/{employee_id}/availability')
    def employee_availability(employee_id:int,request:Request,date_from:date=Query(alias='from'),date_to:date=Query(alias='to'),actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        return envelope(request,availability_data(session,employee,date_from,date_to))

    @app.put('/api/v1/employees/{employee_id}/availability/weekly')
    def proxy_weekly_availability(employee_id:int,body:ProxiedWeeklyAvailabilityUpdate,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        data=save_weekly_availability(session,employee,body,actor,body.reason)
        return envelope(request,data,'管理员代录的常规可用时间已保存')

    @app.put('/api/v1/employees/{employee_id}/availability/overrides/{work_date}')
    def proxy_availability_override(employee_id:int,work_date:date,body:ProxiedAvailabilityOverrideUpdate,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        data=save_availability_override(session,employee,work_date,body,actor,body.reason)
        return envelope(request,data,'管理员代录的日期例外已保存')

    @app.delete('/api/v1/employees/{employee_id}/availability/overrides/{work_date}')
    def proxy_delete_availability_override(employee_id:int,work_date:date,body:ProxiedAvailabilityOverrideDelete,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        data=delete_availability_override(session,employee,work_date,body.expected_revision,actor,body.reason)
        return envelope(request,data,'管理员已删除日期例外')

    @app.get('/api/v1/employees/{employee_id}/preferences/{period_id}')
    def proxy_employee_preferences(employee_id:int,period_id:int,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        period=session.get(SchedulePeriod,period_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        return envelope(request,preference_data(session,employee,period))

    @app.put('/api/v1/employees/{employee_id}/preferences/{period_id}')
    def proxy_employee_preferences_update(employee_id:int,period_id:int,body:ProxiedPreferenceUpdate,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        period=session.get(SchedulePeriod,period_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        data=save_preferences(session,employee,period,body,actor,body.reason)
        return envelope(request,data,'管理员代录的员工偏好已保存')

    @app.get('/api/v1/periods/{period_id}/submission-status')
    def period_submission_status(period_id:int,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        period=session.get(SchedulePeriod,period_id)
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        employees=session.scalars(select(Employee).where(Employee.status=='ACTIVE').order_by(Employee.name,Employee.id)).all()
        submissions={submission.employee_id:submission for submission in session.scalars(select(PreferenceSubmission).where(PreferenceSubmission.period_id==period.id)).all()}
        items=[]
        for employee in employees:
            submission=submissions.get(employee.id)
            items.append({'employee_id':str(employee.id),'employee_no':employee.employee_no,'name':employee.name,
                'status':submission.status if submission else 'NOT_SUBMITTED','revision':submission.row_version if submission else 0,
                'submitted_at':timestamp(submission.submitted_at) if submission else None})
        counts={'SUBMITTED':sum(1 for item in items if item['status']=='SUBMITTED'),
            'DRAFT':sum(1 for item in items if item['status']=='DRAFT'),
            'NOT_SUBMITTED':sum(1 for item in items if item['status']=='NOT_SUBMITTED')}
        return envelope(request,{'period_id':str(period.id),'week_start':period.week_start.isoformat(),'counts':counts,'items':items})

    @app.get('/api/v1/rule-versions')
    def rule_versions(request:Request,actor=Depends(manager),session:Session=Depends(db)):
        items=session.scalars(select(RuleVersion).order_by(RuleVersion.effective_week.desc(),RuleVersion.version_no.desc())).all()
        return envelope(request,{'items':[rule_version_data(session,item) for item in items],'total':len(items),'page':1,'page_size':100})

    @app.post('/api/v1/rule-versions',status_code=201)
    def create_rule_version(body:RuleVersionInput,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        session.scalars(select(RuleVersion).order_by(RuleVersion.id).with_for_update()).all()
        version_no=(session.scalar(select(func.max(RuleVersion.version_no))) or 0)+1
        rule=RuleVersion(version_no=version_no,effective_week=body.effective_week,
            daily_shift_limit=body.daily_shift_limit,weekly_minutes_limit=body.weekly_minutes_limit,
            consecutive_days_limit=body.consecutive_days_limit,min_rest_minutes=body.min_rest_minutes,
            weights_json=body.weights.model_dump(),schema_version=1,created_by=actor.id)
        session.add(rule)
        try: session.flush()
        except IntegrityError:
            session.rollback(); raise Problem(409,'RULE_VERSION_CONFLICT','规则版本创建冲突，请刷新后重试')
        session.add(AuditEvent(actor_id=actor.id,action='rule_version.created',entity_id=rule.id,
            summary={'effective_week':body.effective_week.isoformat(),'version_no':version_no}))
        session.commit()
        return envelope(request,rule_version_data(session,rule),'排班规则版本已创建')

    @app.get('/api/v1/rule-versions/effective')
    def effective_rules(request:Request,week:date=Query(...),user=Depends(business_user),session:Session=Depends(db)):
        if week.weekday()!=0: raise Problem(422,'VALIDATION_FAILED','查询周必须从周一开始')
        rule=effective_rule_version(session,week)
        if not rule: raise Problem(404,'RULE_UNAVAILABLE','该周尚未配置生效的排班规则')
        return envelope(request,rule_version_data(session,rule,public=user.role!='MANAGER'))

    @app.get('/api/v1/rule-versions/{rule_id}')
    def rule_version_detail(rule_id:int,request:Request,user=Depends(business_user),session:Session=Depends(db)):
        rule=session.get(RuleVersion,rule_id)
        if not rule: raise Problem(404,'NOT_FOUND','规则版本不存在')
        return envelope(request,rule_version_data(session,rule,public=user.role!='MANAGER'))

    @app.post('/api/v1/solver-tasks',status_code=202)
    def create_solver_task(body:SolverTaskCreate,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        key=request.headers.get('idempotency-key','')
        if not 8<=len(key)<=64: raise Problem(422,'IDEMPOTENCY_REQUIRED','请提供有效的操作编号')
        record_key=f'{actor.id}:solver:{key}'
        fingerprint=digest(json.dumps(body.model_dump(),sort_keys=True))
        record=session.get(IdempotencyRecord,record_key)
        if record:
            if record.request_hash!=fingerprint: raise Problem(409,'IDEMPOTENCY_CONFLICT','操作编号已用于其他请求')
            existing=session.get(SolverTask,int(record.response['task_id']))
            if not existing: raise Problem(409,'IDEMPOTENCY_CONFLICT','原求解任务不存在')
            return envelope(request,solver_task_data(existing),'已返回原求解任务')
        period=session.get(SchedulePeriod,body.period_id)
        draft=session.scalar(select(ScheduleVersion).where(ScheduleVersion.id==body.draft_version_id).with_for_update())
        if not period or not draft or draft.period_id!=period.id: raise Problem(404,'NOT_FOUND','排班周期或草稿不存在')
        if draft.status!='DRAFT': raise Problem(409,'DRAFT_REQUIRED','只有排班草稿可以执行求解')
        if draft.row_version!=body.expected_draft_revision: raise Problem(409,'VERSION_CONFLICT','排班草稿已变化，请刷新后重试')
        if body.base_published_version_id is not None: raise Problem(409,'PUBLISH_SUPPORT_PENDING','发布版本调班将在后续阶段开放')
        if not draft.rule_version_id: raise Problem(409,'RULE_REQUIRED','当前草稿没有绑定排班规则，请重新生成草稿')
        if body.rule_version_id is not None and body.rule_version_id!=draft.rule_version_id:
            raise Problem(409,'RULE_CONFLICT','草稿绑定的规则版本与请求不一致')
        busy=session.scalar(select(SolverTask.id).where(SolverTask.draft_version_id==draft.id,SolverTask.state.in_(['QUEUED','RUNNING'])))
        if busy: raise Problem(409,'SOLVER_BUSY','该草稿已有排队或运行中的求解任务')
        rule=session.get(RuleVersion,draft.rule_version_id)
        snapshot=build_solver_snapshot(session,draft,period,rule)
        store_settings=session.get(StoreSetting,1)
        time_limit=body.time_limit_seconds or (store_settings.solver_time_limit_seconds if store_settings else 30)
        task=SolverTask(period_id=period.id,draft_version_id=draft.id,base_version_id=None,mode='INITIAL',state='QUEUED',
            input_snapshot=snapshot,input_revision=snapshot['input_revision'],draft_revision=draft.row_version,
            time_limit_seconds=time_limit,created_by=actor.id)
        session.add(task); session.flush()
        session.add(IdempotencyRecord(key=record_key,request_hash=fingerprint,response={'task_id':str(task.id)}))
        session.add(AuditEvent(actor_id=actor.id,action='solver_task.created',entity_id=task.id,
            summary={'period_id':str(period.id),'draft_version_id':str(draft.id),'time_limit_seconds':time_limit}))
        session.commit()
        if test_engine is not None:
            execute_solver_task(engine,task.id)
        else:
            threading.Thread(target=execute_solver_task,args=(engine,task.id),daemon=True).start()
        return envelope(request,solver_task_data(task),'求解任务已创建')

    @app.get('/api/v1/solver-tasks')
    def solver_tasks(request:Request,draft_version_id:int|None=Query(None,ge=1),actor=Depends(manager),session:Session=Depends(db)):
        query=select(SolverTask)
        if draft_version_id is not None: query=query.where(SolverTask.draft_version_id==draft_version_id)
        items=session.scalars(query.order_by(SolverTask.id.desc()).limit(50)).all()
        return envelope(request,{'items':[solver_task_data(task) for task in items],'total':len(items)})

    @app.get('/api/v1/solver-tasks/{task_id}')
    def solver_task_detail(task_id:int,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        task=session.get(SolverTask,task_id)
        if not task: raise Problem(404,'NOT_FOUND','求解任务不存在')
        return envelope(request,solver_task_data(task))

    @app.get('/api/v1/periods/{period_id}/versions')
    def period_versions(period_id:int,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        period=session.get(SchedulePeriod,period_id)
        if not period: raise Problem(404,'NOT_FOUND','排班周期不存在')
        versions=session.scalars(select(ScheduleVersion).where(ScheduleVersion.period_id==period.id).order_by(ScheduleVersion.version_no.desc())).all()
        return envelope(request,{'items':[version_summary_data(session,version) for version in versions],
            'current_version_id':str(period.current_version_id) if period.current_version_id else None,'period_revision':period.row_version})

    @app.get('/api/v1/versions/{version_id}/diff')
    def version_diff(version_id:int,request:Request,other_version_id:int=Query(...,ge=1),actor=Depends(manager),session:Session=Depends(db)):
        version=session.get(ScheduleVersion,version_id); other=session.get(ScheduleVersion,other_version_id)
        if not version or not other: raise Problem(404,'NOT_FOUND','版本不存在')
        if version.period_id!=other.period_id: raise Problem(422,'VALIDATION_FAILED','只能比较同一排班周期的版本')
        left=version_content_map(session,version); right=version_content_map(session,other)
        shifts_added=[]; shifts_removed=[]; shifts_changed=[]
        for key in sorted(set(left)|set(right)):
            if key not in left: shifts_added.append({'shift_key':key,**right[key]})
            elif key not in right: shifts_removed.append({'shift_key':key,**left[key]})
            elif left[key]!=right[key]:
                changed_fields=[field for field in left[key] if left[key][field]!=right[key].get(field)]
                shifts_changed.append({'shift_key':key,'changed_fields':changed_fields,'before':left[key],'after':right[key]})
        assignments_added=[]; assignments_removed=[]
        for key in set(left)|set(right):
            before=set((item[0],item[1]) for item in left.get(key,{}).get('assignments',[]))
            after=set((item[0],item[1]) for item in right.get(key,{}).get('assignments',[]))
            assignments_added.extend({'shift_key':key,'employee_id':employee,'position_id':position} for employee,position in sorted(after-before))
            assignments_removed.extend({'shift_key':key,'employee_id':employee,'position_id':position} for employee,position in sorted(before-after))
        return envelope(request,{'version_id':str(version.id),'other_version_id':str(other.id),'shifts_added':shifts_added,
            'shifts_removed':shifts_removed,'shifts_changed':shifts_changed,
            'assignments_added':assignments_added,'assignments_removed':assignments_removed,
            'summary':{'shifts_added':len(shifts_added),'shifts_removed':len(shifts_removed),'shifts_changed':len(shifts_changed),
                'assignments_added':len(assignments_added),'assignments_removed':len(assignments_removed)}})

    def publish_in_transaction(session,version_id,body,actor,idempotency_record=None):
        guard=session.get(SchedulingGuard,1)
        if not guard:
            guard=SchedulingGuard(id=1,input_revision=1); session.add(guard); session.flush()
        guard=session.scalar(select(SchedulingGuard).where(SchedulingGuard.id==1).with_for_update())
        preliminary=session.get(ScheduleVersion,version_id)
        if not preliminary: raise Problem(404,'NOT_FOUND','排班草稿不存在')
        period=session.scalar(select(SchedulePeriod).where(SchedulePeriod.id==preliminary.period_id).with_for_update())
        version=session.scalar(select(ScheduleVersion).where(ScheduleVersion.id==version_id).with_for_update())
        if version.status!='DRAFT': raise Problem(409,'DRAFT_REQUIRED','只有草稿可以发布')
        if version.row_version!=body.expected_draft_revision:
            raise Problem(409,'VERSION_CONFLICT','排班草稿已变化，请重新校验后刷新')
        if period.row_version!=body.expected_period_revision:
            raise Problem(409,'VERSION_CONFLICT','排班周期已变化，请刷新后重试')
        current=session.get(ScheduleVersion,period.current_version_id) if period.current_version_id else None
        if current and current.id!=body.base_published_version_id:
            raise Problem(409,'VERSION_CONFLICT','当前发布版本已变化，请刷新后重试')
        if not current and body.base_published_version_id is not None:
            raise Problem(409,'VERSION_CONFLICT','基准发布版本不存在或已变化')
        rule=session.get(RuleVersion,version.rule_version_id) if version.rule_version_id else None
        snapshot=build_solver_snapshot(session,version,period,rule)
        validation=validate_assignments(snapshot,version_data(session,version)['assignments'])
        if snapshot['input_revision']!=body.expected_input_revision:
            raise Problem(409,'INPUT_CHANGED','员工、技能、可用时间、偏好或规则在发布前已变化，请重新校验')
        if not validation['valid']:
            raise Problem(422,'HARD_CONSTRAINT_VIOLATION','排班草稿仍存在硬冲突，不能发布',{'hard_conflicts':validation['hard_conflicts']})
        if current:
            current_map=version_content_map(session,current); draft_map=version_content_map(session,version)
            for key,content in current_map.items():
                if shift_started(content) and draft_map.get(key)!=content:
                    raise Problem(409,'IMMUTABLE_SHIFT_CHANGED','已经开始或结束的班次及其人员安排不能修改',{'shift_key':key})
            for key,content in draft_map.items():
                if shift_started(content) and current_map.get(key)!=content:
                    raise Problem(409,'IMMUTABLE_SHIFT_CHANGED','草稿不能新增或改写已经开始/结束的班次',{'shift_key':key})
        old_employee_ids=set(str(item.employee_id) for item in session.scalars(select(Assignment).where(Assignment.version_id==current.id)).all()) if current else set()
        new_employee_ids=set(str(item.employee_id) for item in session.scalars(select(Assignment).where(Assignment.version_id==version.id)).all())
        affected=sorted(old_employee_ids^new_employee_ids if current else new_employee_ids)
        if current:
            current.status='SUPERSEDED'; current.row_version+=1
        version.status='PUBLISHED'; version.published_at=now(); version.published_by=actor.id
        version.base_published_id=current.id if current else None; version.input_revision=snapshot['input_revision']; version.row_version+=1
        version.metrics_json={**(version.metrics_json or {}),'validation':validation['metrics'],'validation_valid':True}
        period.current_version_id=version.id; period.row_version+=1
        response_data={'version_id':str(version.id),'version_no':version.version_no,'published_at':timestamp(version.published_at),
            'period_revision':period.row_version,'affected_employee_ids':affected}
        session.add(AuditEvent(actor_id=actor.id,action='schedule.published',entity_id=version.id,
            summary={'period_id':str(period.id),'old_version_id':str(current.id) if current else None,'affected_employee_ids':affected}))
        session.add(OutboxEvent(event_key=str(uuid.uuid4()),event_type='schedule.published',aggregate_id=version.id,
            payload={'period_id':str(period.id),'old_version_id':str(current.id) if current else None,'new_version_id':str(version.id),
                'affected_employee_ids':affected,'actor_id':str(actor.id),'occurred_at':timestamp(now())}))
        if idempotency_record:
            session.add(IdempotencyRecord(key=idempotency_record['key'],request_hash=idempotency_record['hash'],response=response_data))
        session.flush()
        return response_data

    @app.post('/api/v1/versions/{version_id}/publish')
    def publish_version(version_id:int,body:PublishRequest,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        key=request.headers.get('idempotency-key','')
        if not 8<=len(key)<=64: raise Problem(422,'IDEMPOTENCY_REQUIRED','请提供有效的操作编号')
        record_key=f'{actor.id}:publish:{key}'
        fingerprint=digest(json.dumps({'version_id':version_id,**body.model_dump()},sort_keys=True))
        record=session.get(IdempotencyRecord,record_key)
        if record:
            if record.request_hash!=fingerprint: raise Problem(409,'IDEMPOTENCY_CONFLICT','操作编号已用于其他请求')
            return envelope(request,record.response,'该发布请求已成功处理')
        response_data=publish_in_transaction(session,version_id,body,actor,{'key':record_key,'hash':fingerprint})
        session.commit()
        return envelope(request,response_data,'班表已发布')

    @app.post('/api/v1/versions/{version_id}/copy-to-draft',status_code=201)
    def copy_version_to_draft(version_id:int,body:CopyVersionToDraft,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        source=session.get(ScheduleVersion,version_id)
        if not source or source.status=='DISCARDED': raise Problem(404,'NOT_FOUND','来源版本不存在或不可恢复')
        period=session.scalar(select(SchedulePeriod).where(SchedulePeriod.id==source.period_id).with_for_update())
        if period.row_version!=body.expected_period_revision: raise Problem(409,'VERSION_CONFLICT','排班周期已变化，请刷新后重试')
        rule=effective_rule_version(session,period.week_start)
        if not rule: raise Problem(409,'RULE_REQUIRED','当前没有生效的排班规则')
        latest_no=session.scalar(select(func.max(ScheduleVersion.version_no)).where(ScheduleVersion.period_id==period.id)) or 0
        draft=ScheduleVersion(period_id=period.id,version_no=latest_no+1,parent_id=source.id,status='DRAFT',
            rule_version_id=rule.id,created_by=actor.id,input_snapshot={'source_version_id':str(source.id),'restored':True})
        session.add(draft); session.flush()
        current=session.get(ScheduleVersion,period.current_version_id) if period.current_version_id else None
        current_shifts=session.scalars(select(VersionShift).where(VersionShift.version_id==current.id)).all() if current else []
        current_started={shift.shift_key:shift for shift in current_shifts if shift_started({'work_date':shift.work_date.isoformat(),'start_time':shift.start_time.isoformat(timespec='minutes')})}
        source_shifts=session.scalars(select(VersionShift).where(VersionShift.version_id==source.id).order_by(VersionShift.work_date,VersionShift.start_time,VersionShift.id)).all()
        selected_shifts=[shift for shift in source_shifts if shift.shift_key not in current_started]+list(current_started.values())
        for source_shift in selected_shifts:
            shift=VersionShift(version_id=draft.id,shift_key=source_shift.shift_key,template_id=source_shift.template_id,
                work_date=source_shift.work_date,name=source_shift.name,start_time=source_shift.start_time,end_time=source_shift.end_time,enabled=source_shift.enabled)
            session.add(shift); session.flush()
            for demand in session.scalars(select(VersionDemand).where(VersionDemand.version_shift_id==source_shift.id)).all():
                session.add(VersionDemand(version_shift_id=shift.id,position_id=demand.position_id,position_name=demand.position_name,required_count=demand.required_count))
            for assignment in session.scalars(select(Assignment).where(Assignment.version_id==source_shift.version_id,Assignment.version_shift_id==source_shift.id)).all():
                session.add(Assignment(version_id=draft.id,version_shift_id=shift.id,employee_id=assignment.employee_id,position_id=assignment.position_id,
                    employee_name=assignment.employee_name,position_name=assignment.position_name,locked=assignment.locked))
        draft.input_revision=scheduling_input_revision(session,period)
        period.row_version+=1
        session.add(AuditEvent(actor_id=actor.id,action='schedule.restored_to_draft',entity_id=draft.id,summary={'source_version_id':str(source.id)}))
        session.commit()
        return envelope(request,version_data(session,draft),'历史版本已复制为新的排班草稿')

    @app.post('/api/v1/versions/{version_id}/discard')
    def discard_version(version_id:int,body:DiscardVersion,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        version=session.scalar(select(ScheduleVersion).where(ScheduleVersion.id==version_id).with_for_update())
        if not version: raise Problem(404,'NOT_FOUND','版本不存在')
        if version.status!='DRAFT': raise Problem(409,'DRAFT_REQUIRED','只有草稿可以废弃')
        if version.row_version!=body.expected_revision: raise Problem(409,'VERSION_CONFLICT','排班草稿已变化，请刷新后重试')
        version.status='DISCARDED'; version.row_version+=1
        session.add(AuditEvent(actor_id=actor.id,action='schedule.draft_discarded',entity_id=version.id))
        session.commit()
        return envelope(request,version_summary_data(session,version),'草稿已废弃')

    @app.get('/api/v1/me/schedules')
    def my_schedules(request:Request,date_from:date=Query(alias='from'),date_to:date=Query(alias='to'),user=Depends(business_user),session:Session=Depends(db)):
        employee=employee_for_user(session,user)
        if date_from>date_to: raise Problem(422,'VALIDATION_FAILED','查询日期范围不正确')
        rows=session.execute(select(Assignment,VersionShift,ScheduleVersion,SchedulePeriod).join(VersionShift,Assignment.version_shift_id==VersionShift.id)
            .join(ScheduleVersion,Assignment.version_id==ScheduleVersion.id).join(SchedulePeriod,ScheduleVersion.period_id==SchedulePeriod.id)
            .where(Assignment.employee_id==employee.id,ScheduleVersion.status=='PUBLISHED',VersionShift.work_date>=date_from,VersionShift.work_date<=date_to)
            .order_by(VersionShift.work_date,VersionShift.start_time)).all()
        return envelope(request,{'items':[{'version_id':str(version.id),'version_no':version.version_no,'published_at':timestamp(version.published_at),
            'work_date':shift.work_date.isoformat(),'shift_key':shift.shift_key,'shift_name':shift.name,'start_time':shift.start_time.isoformat(timespec='minutes'),
            'end_time':shift.end_time.isoformat(timespec='minutes'),'position_id':str(assignment.position_id),'position_name':assignment.position_name,
            'employee_name':assignment.employee_name} for assignment,shift,version,period in rows],'from':date_from.isoformat(),'to':date_to.isoformat()})

    @app.get('/api/v1/shared/capabilities')
    def shared_capabilities(request:Request,actor=Depends(manager)):
        return envelope(request,{'capabilities':[
            'current_published_schedule','employee_published_assignments','schedule_validation',
            'eligible_employee_lookup','schedule_draft_read','schedule_publish','outbox_events',
            'audit_events','background_solver'
        ],'business_owner':'F01-F08','student_modules':'F09-F16'})

    @app.get('/api/v1/shared/periods/{period_id}/published-version')
    def shared_published_version(period_id:int,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        version=current_published_version(session,period_id)
        if not version: raise Problem(404,'NOT_FOUND','该周期尚无当前发布版本')
        return envelope(request,version_data(session,version))

    @app.get('/api/v1/shared/employees/{employee_id}/schedule')
    def shared_employee_schedule(employee_id:int,request:Request,date_from:date=Query(alias='from'),date_to:date=Query(alias='to'),actor=Depends(manager),session:Session=Depends(db)):
        employee=session.get(Employee,employee_id)
        if not employee: raise Problem(404,'NOT_FOUND','员工不存在')
        if date_from>date_to: raise Problem(422,'VALIDATION_FAILED','查询日期范围不正确')
        return envelope(request,{'items':employee_published_assignments(session,employee.id,date_from,date_to),'from':date_from.isoformat(),'to':date_to.isoformat()})

    @app.get('/api/v1/shared/outbox-events')
    def shared_outbox_events(request:Request,after_id:int=Query(0,ge=0),state:str=Query('PENDING',pattern='^(PENDING|PROCESSED|FAILED|)$'),limit:int=Query(100,ge=1,le=500),actor=Depends(manager),session:Session=Depends(db)):
        items=outbox_events(session,after_id,state or None,limit)
        return envelope(request,{'items':[{'id':str(event.id),'event_key':event.event_key,'event_type':event.event_type,
            'aggregate_id':str(event.aggregate_id),'payload':event.payload,'state':event.state,'attempt':event.attempt,
            'available_at':timestamp(event.available_at),'created_at':timestamp(event.created_at)} for event in items],'after_id':after_id})

    @app.post('/api/v1/shared/outbox-events/{event_id}/ack')
    def shared_outbox_ack(event_id:int,request:Request,actor=Depends(manager),session:Session=Depends(db)):
        event=acknowledge_outbox_event(session,event_id)
        if not event: raise Problem(404,'NOT_FOUND','事件不存在')
        session.commit()
        return envelope(request,{'id':str(event.id),'state':event.state},'事件已标记为已处理')

    @app.get('/api/v1/shared/audit-events')
    def shared_audit_events(request:Request,after_id:int=Query(0,ge=0),entity_type:str|None=Query(None,max_length=32),entity_id:int|None=Query(None,ge=1),limit:int=Query(100,ge=1,le=500),actor=Depends(manager),session:Session=Depends(db)):
        items=audit_events(session,after_id,entity_type,entity_id,limit)
        return envelope(request,{'items':[{'id':str(event.id),'actor_id':str(event.actor_id) if event.actor_id else None,
            'action':event.action,'entity_id':str(event.entity_id) if event.entity_id else None,'summary':event.summary,
            'created_at':timestamp(event.created_at)} for event in items],'after_id':after_id})

    @app.get('/api/v1/me/profile')
    def profile(request:Request,user=Depends(business_user),session:Session=Depends(db)):
        employee=session.scalar(select(Employee).where(Employee.user_id==user.id))
        if not employee: raise Problem(404,'PROFILE_NOT_FOUND','尚未绑定员工档案')
        return envelope(request,employee_detail_data(session,employee))

    register_leave_routes(
        app,
        db_dependency=db,
        business_user_dependency=business_user,
        manager_dependency=manager,
        envelope=envelope,
        employee_for_user=employee_for_user,
        timestamp=timestamp,
    )
    register_swap_routes(
        app,
        db_dependency=db,
        business_user_dependency=business_user,
        manager_dependency=manager,
        envelope=envelope,
        employee_for_user=employee_for_user,
        timestamp=timestamp,
        effective_rule_version=effective_rule_version,
        build_snapshot=build_solver_snapshot,
        version_data=version_data,
        publish_in_transaction=publish_in_transaction,
        scheduling_input_revision=scheduling_input_revision,
        shift_started=shift_started,
    )
    register_notification_routes(
        app,
        db_dependency=db,
        business_user_dependency=business_user,
        manager_dependency=manager,
        envelope=envelope,
        employee_for_user=employee_for_user,
        timestamp=timestamp,
    )
    register_adjustment_routes(
        app,
        db_dependency=db,
        manager_dependency=manager,
        envelope=envelope,
        build_snapshot=build_solver_snapshot,
        version_data=version_data,
        publish_in_transaction=publish_in_transaction,
        scheduling_input_revision=scheduling_input_revision,
        shift_started=shift_started,
    )
    register_report_routes(
        app,
        db_dependency=db,
        business_user_dependency=business_user,
        manager_dependency=manager,
        envelope=envelope,
        employee_for_user=employee_for_user,
    )
    register_settings_routes(
        app,
        db_dependency=db,
        business_user_dependency=business_user,
        manager_dependency=manager,
        envelope=envelope,
        timestamp=timestamp,
    )
    register_ai_routes(
        app,
        db_dependency=db,
        business_user_dependency=business_user,
        employee_for_user=employee_for_user,
        envelope=envelope,
        timestamp=timestamp,
        settings=settings,
        provider=ai_provider,
    )
    if test_engine is None and 'pytest' not in sys.modules:
        start_notification_worker(engine)
    return app

app=create_app()
