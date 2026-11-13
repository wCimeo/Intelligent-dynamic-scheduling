"""Opt-in MySQL smoke: one rollback-only transaction, no table deletion."""
import os, secrets
from datetime import date,timedelta
import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import User, Employee, Skill, Position, ShiftTemplate, SchedulePeriod, RuleVersion, SolverTask, Assignment, OutboxEvent, AvailabilityProfile, AvailabilityOverride, PreferenceSubmission, AIParseRecord, AIExplanationRecord
from app.security import passwords
from app.main import create_app
from app.solver import solve_snapshot
from test_accounts import post,mutate

@pytest.mark.skipif(os.getenv('IDS_TEST_MYSQL')!='1',reason='需显式启用真实 MySQL 测试')
def test_mysql_transactional_flow():
    settings=Settings()
    assert settings.db_name=='intelligent_dynamic_scheduling'
    engine=create_engine(settings.url)
    tag=secrets.token_hex(4)
    username='probe_'+tag
    worker='worker_'+tag
    password=secrets.token_urlsafe(20)
    week_start=None
    direct_employee_id=None
    rule_id=None
    solver_task_id=None
    draft_version_id=None
    with engine.connect() as connection:
        transaction=connection.begin()
        connection.begin_nested()
        try:
            with Session(connection) as db:
                db.add(User(username=username,display_name='回滚测试管理员',password_hash=passwords.hash(password),role='MANAGER',status='ACTIVE'))
                db.commit()
                with Session(connection) as db:
                    other_manager=User(username='other_'+tag,display_name='回滚测试第二管理员',password_hash=passwords.hash(password),role='MANAGER',status='ACTIVE')
                    db.add(other_manager); db.commit(); other_manager_id=other_manager.id
            app=create_app(settings,connection)
            with TestClient(app) as client:
                registration=post(client,'/auth/register',{'username':worker,'name':'回滚测试员工','password':password,'password_confirmation':password})
                assert registration.status_code==201
                uid=registration.json()['data']['user_id']
                manager_login=post(client,'/auth/login',{'username':username,'password':password})
                assert manager_login.status_code==200
                other_disabled=mutate(client,'PATCH',f'/admin/accounts/{other_manager_id}/status',{'status':'DISABLED','expected_revision':1})
                assert other_disabled.status_code==200 and other_disabled.json()['data']['status']=='DISABLED'
                other_enabled=mutate(client,'PATCH',f'/admin/accounts/{other_manager_id}/status',{'status':'ACTIVE','expected_revision':2})
                assert other_enabled.status_code==200 and other_enabled.json()['data']['status']=='ACTIVE'
                body={'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'PROBE_'+tag,'name':'回滚测试员工'}}
                key=secrets.token_hex(16)
                approved=post(client,f'/admin/accounts/{uid}/review',body,key)
                assert approved.status_code==200,approved.text
                assert post(client,f'/admin/accounts/{uid}/review',body,key).status_code==200
                assert post(client,'/auth/login',{'username':worker,'password':password}).status_code==200
                assert client.get('/api/v1/employees').status_code==403
                assert client.get('/api/v1/me/profile').json()['data']['employee_no']=='PROBE_'+tag
                assert post(client,'/auth/login',{'username':username,'password':password}).status_code==200
                assert post(client,'/auth/password-reset-requests',{'username':worker}).status_code==200
                listing=client.get('/api/v1/admin/password-reset-requests').json()['data']
                assert listing['total']==1
                request=listing['items'][0]
                reset_body={'request_id':int(request['id']),'expected_revision':request['account_revision'],'verification_note':'MySQL事务内现场核实'}
                reset_key=secrets.token_hex(16)
                reset=post(client,f'/admin/accounts/{uid}/reset-password',reset_body,reset_key)
                assert reset.status_code==200,reset.text
                temporary_password=reset.json()['data']['temporary_password']
                assert temporary_password
                assert post(client,f'/admin/accounts/{uid}/reset-password',reset_body,reset_key).json()['data']['temporary_password'] is None
                assert post(client,'/auth/login',{'username':worker,'password':password}).status_code==401
                assert post(client,'/auth/login',{'username':worker,'password':temporary_password}).json()['data']['session_scope']=='PASSWORD_CHANGE'
                assert post(client,'/auth/login',{'username':username,'password':password}).status_code==200
                direct_employee=post(client,'/employees',{'employee_no':'DIRECT_'+tag,'name':'直接创建账号员工','weekly_limit_minutes':3000})
                assert direct_employee.status_code==201
                direct_employee_id=int(direct_employee.json()['data']['id'])
                with Session(connection) as db:
                    ai_record=AIParseRecord(employee_id=direct_employee_id,raw_text='MySQL回滚测试AI解析',
                        status='PENDING_CONFIRMATION',parsed_json={'summary':'回滚测试','overrides':[],'preferences':[],
                        'clarifications':[]},base_snapshot={'overrides':{},'preferences':{}},model='mysql-probe',usage_json={})
                    db.add(ai_record);db.commit();ai_record_id=ai_record.id
                managed_username='managed_'+tag
                managed_body={'username':managed_username,'name':'直接创建账号员工','employee_id':int(direct_employee.json()['data']['id'])}
                managed_key=secrets.token_hex(16)
                managed=post(client,'/admin/accounts',managed_body,managed_key)
                assert managed.status_code==201,managed.text
                managed_uid=managed.json()['data']['user_id']
                assert managed.json()['data']['temporary_password']
                assert post(client,'/admin/accounts',managed_body,managed_key).json()['data']['temporary_password'] is None
                disabled=mutate(client,'PATCH',f'/admin/accounts/{managed_uid}/status',{'status':'DISABLED','expected_revision':1})
                assert disabled.status_code==200 and disabled.json()['data']['status']=='DISABLED'
                enabled=mutate(client,'PATCH',f'/admin/accounts/{managed_uid}/status',{'status':'ACTIVE','expected_revision':2})
                assert enabled.status_code==200 and enabled.json()['data']['status']=='ACTIVE'
                assert post(client,'/auth/login',{'username':managed_username,'password':managed.json()['data']['temporary_password']}).json()['data']['session_scope']=='PASSWORD_CHANGE'
                assert post(client,'/auth/login',{'username':username,'password':password}).status_code==200
                skill=post(client,'/skills',{'code':'skill_'+tag,'name':'回滚测试技能'})
                assert skill.status_code==201
                position=post(client,'/positions',{'code':'position_'+tag,'name':'回滚测试岗位'})
                assert position.status_code==201
                required=mutate(client,'PUT',f"/positions/{position.json()['data']['id']}/skills",{'skill_ids':[int(skill.json()['data']['id'])],'expected_revision':position.json()['data']['revision']})
                assert required.status_code==200
                employee_skills=mutate(client,'PUT',f"/employees/{direct_employee.json()['data']['id']}/skills",{'skill_ids':[int(skill.json()['data']['id'])],'expected_revision':direct_employee.json()['data']['revision']})
                assert employee_skills.status_code==200,employee_skills.text
                qualified=client.get(f"/api/v1/employees?position_id={position.json()['data']['id']}")
                assert qualified.status_code==200 and qualified.json()['data']['total']==1
                shift_template=post(client,'/shift-templates',{'code':'shift_'+tag,'name':'回滚测试班次','start_time':'08:00','end_time':'14:00','demands':[{'position_id':int(position.json()['data']['id']),'required_count':1}]})
                assert shift_template.status_code==201,shift_template.text
                with Session(connection) as db:
                    db.execute(update(ShiftTemplate).where(ShiftTemplate.id!=int(shift_template.json()['data']['id'])).values(active=False))
                    db.commit()
                base_date=date(2035,1,1)+timedelta(days=int(tag[:4],16)%1000)
                week_start=base_date+timedelta(days=(7-base_date.weekday())%7)
                period=post(client,'/periods',{'week_start':week_start.isoformat()})
                assert period.status_code==201,period.text
                with Session(connection) as db:
                    explanation_record=AIExplanationRecord(requested_by=other_manager_id,employee_id=direct_employee_id,
                        period_id=int(period.json()['data']['id']),scope='PUBLISHED_SCHEDULE',
                        question='MySQL回滚测试方案解释',facts_json={'scope':'PUBLISHED_SCHEDULE'},
                        output_json={'title':'回滚测试'},status='COMPLETED',model='mysql-probe',usage_json={})
                    db.add(explanation_record);db.commit();explanation_record_id=explanation_record.id
                rule=post(client,'/rule-versions',{'effective_week':week_start.isoformat(),'daily_shift_limit':1,'weekly_minutes_limit':3000,'consecutive_days_limit':7,'min_rest_minutes':600,'weights':{'preference':30,'hours_balance':20,'evening_balance':10}})
                assert rule.status_code==201,rule.text
                rule_id=int(rule.json()['data']['id'])
                draft=post(client,f"/periods/{period.json()['data']['id']}/drafts",{})
                assert draft.status_code==201,draft.text
                draft_version_id=int(draft.json()['data']['id'])
                assert draft.json()['data']['metrics']['enabled_shifts']==7
                assert draft.json()['data']['rule_version_id']==rule.json()['data']['id']
                availability=mutate(client,'PUT',f"/employees/{direct_employee.json()['data']['id']}/availability/weekly",{'expected_revision':0,'effective_from':week_start.isoformat(),'windows':[{'weekday':day,'start_time':'07:00','end_time':'16:00'} for day in range(1,8)],'reason':'MySQL回滚测试代录'})
                assert availability.status_code==200,availability.text
                override=mutate(client,'PUT',f"/employees/{direct_employee.json()['data']['id']}/availability/overrides/{week_start.isoformat()}",{'expected_revision':0,'mode':'BLOCK','windows':[{'start_time':'14:30','end_time':'15:30'}],'reason':'MySQL回滚测试例外'})
                assert override.status_code==200,override.text
                resolved=client.get(f"/api/v1/employees/{direct_employee.json()['data']['id']}/availability?from={week_start.isoformat()}&to={week_start.isoformat()}")
                assert resolved.status_code==200
                assert resolved.json()['data']['days'][0]['windows']==[{'start_time':'07:00','end_time':'14:30'},{'start_time':'15:30','end_time':'16:00'}]
                preferences=mutate(client,'PUT',f"/employees/{direct_employee.json()['data']['id']}/preferences/{period.json()['data']['id']}",{'expected_revision':0,'submit':True,'items':[{'work_date':week_start.isoformat(),'template_id':int(shift_template.json()['data']['id']),'kind':'PREFER','weight':5}],'reason':'MySQL回滚测试偏好代录'})
                assert preferences.status_code==200,preferences.text
                assert preferences.json()['data']['status']=='SUBMITTED'
                solver=post(client,'/solver-tasks',{'period_id':int(period.json()['data']['id']),'draft_version_id':int(draft.json()['data']['id']),'expected_draft_revision':draft.json()['data']['revision'],'time_limit_seconds':10})
                assert solver.status_code==202,solver.text
                solver_task_id=int(solver.json()['data']['id'])
                solver_result=client.get(f"/api/v1/solver-tasks/{solver_task_id}").json()['data']
                assert solver_result['state'] in {'QUEUED','RUNNING'},solver_result
                with Session(connection) as db:
                    task_record=db.get(SolverTask,solver_task_id)
                    snapshot=task_record.input_snapshot
                direct_result=solve_snapshot(snapshot,10)
                assert direct_result['status'] in {'OPTIMAL','FEASIBLE'}
                assert len(direct_result['assignments'])==7
                shift_key_by_id={item['id']:item['shift_key'] for item in snapshot['shifts']}
                manual_items=[{'shift_key':shift_key_by_id[item['version_shift_id']],'employee_id':int(item['employee_id']),
                    'position_id':int(item['position_id']),'locked':False} for item in direct_result['assignments']]
                assigned=mutate(client,'PUT',f"/versions/{draft_version_id}/assignments",{'expected_revision':draft.json()['data']['revision'],'items':manual_items})
                assert assigned.status_code==200,assigned.text
                validation=mutate(client,'POST',f"/versions/{draft_version_id}/validate",{'expected_revision':assigned.json()['data']['revision']})
                assert validation.status_code==200 and validation.json()['data']['valid'] is True
                published=post(client,f"/versions/{draft_version_id}/publish",{'expected_draft_revision':assigned.json()['data']['revision'],
                    'expected_period_revision':period.json()['data']['revision'],'base_published_version_id':None,
                    'expected_input_revision':validation.json()['data']['input_revision']})
                assert published.status_code==200,published.text
                with Session(connection) as db:
                    assert db.scalar(select(OutboxEvent).where(OutboxEvent.event_type=='schedule.published',OutboxEvent.aggregate_id==draft_version_id)) is not None
        finally:
            transaction.rollback()
    with Session(engine) as db:
        assert db.scalar(select(User).where(User.username==username)) is None
        assert db.scalar(select(User).where(User.username==worker)) is None
        assert db.scalar(select(User).where(User.username=='other_'+tag)) is None
        assert db.scalar(select(User).where(User.username=='managed_'+tag)) is None
        assert db.scalar(select(Employee).where(Employee.employee_no=='PROBE_'+tag)) is None
        assert db.scalar(select(Employee).where(Employee.employee_no=='DIRECT_'+tag)) is None
        assert db.scalar(select(Skill).where(Skill.code=='skill_'+tag)) is None
        assert db.scalar(select(Position).where(Position.code=='position_'+tag)) is None
        assert db.scalar(select(ShiftTemplate).where(ShiftTemplate.code=='shift_'+tag)) is None
        assert week_start is not None
        assert rule_id is not None
        assert db.scalar(select(RuleVersion).where(RuleVersion.id==rule_id)) is None
        assert db.scalar(select(SchedulePeriod).where(SchedulePeriod.week_start==week_start)) is None
        assert direct_employee_id is not None
        assert db.scalar(select(AvailabilityProfile).where(AvailabilityProfile.employee_id==direct_employee_id)) is None
        assert db.scalar(select(AvailabilityOverride).where(AvailabilityOverride.employee_id==direct_employee_id)) is None
        assert db.scalar(select(PreferenceSubmission).where(PreferenceSubmission.employee_id==direct_employee_id)) is None
        assert db.get(AIParseRecord,ai_record_id) is None
        assert db.get(AIExplanationRecord,explanation_record_id) is None
        assert solver_task_id is not None
        assert db.get(SolverTask,solver_task_id) is None
        assert db.scalar(select(Assignment).where(Assignment.version_id==draft_version_id)) is None
    engine.dispose()
