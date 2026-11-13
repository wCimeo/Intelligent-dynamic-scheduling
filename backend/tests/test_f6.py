import time,secrets
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User,Assignment,SolverTask
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login


@pytest.fixture
def fixture(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'f6.db'}",connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    settings=Settings(_env_file=None,csrf_secret='test-only-secret-12345678901234567890')
    with Session(engine) as db:
        db.add(User(username='manager',display_name='管理员',password_hash=passwords.hash(PASSWORD),role='MANAGER',status='ACTIVE'))
        db.commit()
    app=create_app(settings,engine)
    with TestClient(app) as client:
        yield client,engine
    engine.dispose()


def future_week_start():
    today=datetime.now(ZoneInfo('Asia/Shanghai')).date()
    return today-timedelta(days=today.weekday())+timedelta(days=7)


def setup_inputs(c,demand_count=2,week_start=None):
    week_start=week_start or future_week_start().isoformat()
    assert login(c).status_code==200
    skill=post(c,'/skills',{'code':'brew','name':'咖啡制作'}).json()['data']
    position=post(c,'/positions',{'code':'barista','name':'咖啡师'}).json()['data']
    mutate(c,'PUT',f"/positions/{position['id']}/skills",{'skill_ids':[int(skill['id'])],'expected_revision':position['revision']})
    employee_ids=[]
    for index in range(2):
        username=f'worker{index+1}'
        registration=post(c,'/auth/register',{'username':username,'name':f'员工{index+1}','password':PASSWORD,'password_confirmation':PASSWORD})
        uid=registration.json()['data']['user_id']
        approval=post(c,f'/admin/accounts/{uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':f'E60{index+1}','name':f'员工{index+1}','weekly_limit_minutes':3000}})
        employee_id=approval.json()['data']['employee_id']
        employee_ids.append(employee_id)
        mutate(c,'PUT',f"/employees/{employee_id}/skills",{'skill_ids':[int(skill['id'])],'expected_revision':1})
        mutate(c,'PUT',f"/employees/{employee_id}/availability/weekly",{'expected_revision':0,'effective_from':week_start,'windows':[{'weekday':day,'start_time':'08:00','end_time':'14:00'} for day in range(1,8)],'reason':'F06测试输入'})
    rule=post(c,'/rule-versions',{'effective_week':week_start,'daily_shift_limit':1,'weekly_minutes_limit':3000,'consecutive_days_limit':7,'min_rest_minutes':600,'weights':{'preference':30,'hours_balance':20,'evening_balance':10}}).json()['data']
    template=post(c,'/shift-templates',{'code':'morning','name':'早班','start_time':'08:00','end_time':'14:00','demands':[{'position_id':int(position['id']),'required_count':demand_count}]}).json()['data']
    period=post(c,'/periods',{'week_start':week_start}).json()['data']
    draft=post(c,f"/periods/{period['id']}/drafts",{}).json()['data']
    mutate(c,'PUT',f"/employees/{employee_ids[0]}/preferences/{period['id']}",{'expected_revision':0,'submit':True,'items':[{'work_date':week_start,'template_id':int(template['id']),'kind':'PREFER','weight':5}],'reason':'F06测试偏好'})
    return rule,period,draft


def wait_terminal(c,task_id,timeout=15):
    deadline=time.time()+timeout
    while time.time()<deadline:
        task=c.get(f'/api/v1/solver-tasks/{task_id}').json()['data']
        if task['state'] not in {'QUEUED','RUNNING'}: return task
        time.sleep(0.1)
    raise AssertionError('求解任务未在测试时间内结束')


def test_solver_creates_complete_assignments_and_metrics(fixture):
    c,engine=fixture
    rule,period,draft=setup_inputs(c,2)
    body={'period_id':int(period['id']),'draft_version_id':int(draft['id']),'expected_draft_revision':draft['revision'],'base_published_version_id':None,'rule_version_id':int(rule['id']),'time_limit_seconds':10}
    key=secrets.token_hex(16)
    created=post(c,'/solver-tasks',body,key)
    assert created.status_code==202,created.text
    task_id=created.json()['data']['id']
    replay=post(c,'/solver-tasks',body,key)
    assert replay.status_code==202 and replay.json()['data']['id']==task_id
    task=wait_terminal(c,task_id)
    assert task['state'] in {'OPTIMAL','FEASIBLE'}
    assert len(task['assignments'])==14
    assert task['metrics']['required_minutes']==5040
    assert task['metrics']['preference_total']==1 and task['metrics']['preference_satisfied']==1
    assert task['applied_revision']==draft['revision']+1
    with Session(engine) as db:
        assert len(db.scalars(select(Assignment)).all())==14
        assert db.scalar(select(SolverTask).where(SolverTask.id==int(task_id))).state==task['state']


def test_solver_reports_qualified_shortage_without_overwriting(fixture):
    c,engine=fixture
    _,period,draft=setup_inputs(c,3)
    body={'period_id':int(period['id']),'draft_version_id':int(draft['id']),'expected_draft_revision':draft['revision'],'time_limit_seconds':10}
    created=post(c,'/solver-tasks',body)
    assert created.status_code==202,created.text
    task=wait_terminal(c,created.json()['data']['id'])
    assert task['state']=='INFEASIBLE'
    assert task['issues'][0]['code']=='QUALIFIED_AVAILABLE_SHORTAGE'
    assert task['issues'][0]['required']==3 and task['issues'][0]['available']==2
    with Session(engine) as db:
        assert db.scalars(select(Assignment)).all()==[]


def test_solver_task_requires_manager_and_current_draft(fixture):
    c,_=fixture
    rule,period,draft=setup_inputs(c,2)
    assert login(c,'worker1').status_code==200
    forbidden=post(c,'/solver-tasks',{'period_id':int(period['id']),'draft_version_id':int(draft['id']),'expected_draft_revision':draft['revision'],'time_limit_seconds':5})
    assert forbidden.status_code==403
    assert login(c).status_code==200
    stale=post(c,'/solver-tasks',{'period_id':int(period['id']),'draft_version_id':int(draft['id']),'expected_draft_revision':99,'time_limit_seconds':5})
    assert stale.status_code==409 and stale.json()['code']=='VERSION_CONFLICT'
