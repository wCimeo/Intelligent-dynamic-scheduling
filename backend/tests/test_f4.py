import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login,register


@pytest.fixture
def fixture():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    settings=Settings(_env_file=None,csrf_secret='test-only-secret-12345678901234567890')
    with Session(engine) as db:
        db.add(User(username='manager',display_name='管理员',password_hash=passwords.hash(PASSWORD),role='MANAGER',status='ACTIVE'))
        db.commit()
    app=create_app(settings,engine)
    with TestClient(app) as client:
        yield client,engine
    engine.dispose()


def active_worker(c,employee_no='E400'):
    registered=register(c)
    uid=registered.json()['data']['user_id']
    assert login(c).status_code==200
    approved=post(c,f'/admin/accounts/{uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':employee_no,'name':'可用时间员工'}})
    assert approved.status_code==200,approved.text
    assert login(c,'worker').status_code==200
    return uid


def create_period_with_template(c):
    position=post(c,'/positions',{'code':'barista','name':'咖啡师'}).json()['data']
    template=post(c,'/shift-templates',{'code':'morning','name':'早班','start_time':'08:00','end_time':'14:00','demands':[{'position_id':int(position['id']),'required_count':2}]}).json()['data']
    period=post(c,'/periods',{'week_start':'2026-11-09'}).json()['data']
    return template,period


def test_weekly_availability_versions_and_date_overrides(fixture):
    c,_=fixture
    active_worker(c)
    weekly={'expected_revision':0,'effective_from':'2026-11-09','windows':[{'weekday':1,'start_time':'08:00','end_time':'12:00'},{'weekday':1,'start_time':'14:00','end_time':'18:00'},{'weekday':2,'start_time':'09:00','end_time':'17:00'}]}
    saved=mutate(c,'PUT','/me/availability/weekly',weekly)
    assert saved.status_code==200,saved.text
    assert saved.json()['data']['revision']==1
    available=c.get('/api/v1/me/availability?from=2026-11-09&to=2026-11-15').json()['data']
    assert available['days'][0]['source']=='REGULAR'
    assert available['days'][0]['windows']==[{'start_time':'08:00','end_time':'12:00'},{'start_time':'14:00','end_time':'18:00'}]
    update={'expected_revision':1,'effective_from':'2026-11-09','windows':[{'weekday':1,'start_time':'07:00','end_time':'15:00'}]}
    assert mutate(c,'PUT','/me/availability/weekly',update).status_code==200
    new_profile={'expected_revision':2,'effective_from':'2026-11-16','windows':[{'weekday':1,'start_time':'10:00','end_time':'16:00'}]}
    created=mutate(c,'PUT','/me/availability/weekly',new_profile)
    assert created.status_code==200,created.text
    history=c.get('/api/v1/me/availability?from=2026-11-09&to=2026-11-22').json()['data']
    assert len(history['profiles'])==2
    assert history['profiles'][0]['effective_to']=='2026-11-15'
    replace=mutate(c,'PUT','/me/availability/overrides/2026-11-09',{'expected_revision':0,'mode':'REPLACE','windows':[{'start_time':'10:00','end_time':'14:00'}]})
    assert replace.status_code==200,replace.text
    blocked=mutate(c,'PUT','/me/availability/overrides/2026-11-09',{'expected_revision':1,'mode':'BLOCK','windows':[{'start_time':'11:00','end_time':'12:00'}]})
    assert blocked.status_code==200,blocked.text
    resolved=c.get('/api/v1/me/availability?from=2026-11-09&to=2026-11-09').json()['data']['days'][0]
    assert resolved['source']=='OVERRIDE' and resolved['override_mode']=='BLOCK'
    assert resolved['windows']==[{'start_time':'07:00','end_time':'11:00'},{'start_time':'12:00','end_time':'15:00'}]
    deleted=c.request('DELETE','/api/v1/me/availability/overrides/2026-11-09',json={'expected_revision':2},headers=_headers(c))
    assert deleted.status_code==200,deleted.text
    stale=mutate(c,'PUT','/me/availability/overrides/2026-11-09',{'expected_revision':2,'mode':'REPLACE','windows':[]})
    assert stale.status_code==409


def _headers(c,method_headers=None):
    token=c.get('/api/v1/auth/csrf').json()['data']['token']
    return {'Origin':'http://localhost:5174','X-CSRF-Token':token}


def test_preferences_submission_and_manager_status(fixture):
    c,_=fixture
    assert login(c).status_code==200
    template,period=create_period_with_template(c)
    active_worker(c)
    prefs=c.get(f"/api/v1/me/preferences/{period['id']}").json()['data']
    assert prefs['status']=='NOT_SUBMITTED' and prefs['revision']==0
    draft=mutate(c,'PUT',f"/me/preferences/{period['id']}",{'expected_revision':0,'submit':False,'items':[{'work_date':'2026-11-09','template_id':int(template['id']),'kind':'PREFER','weight':5}]})
    assert draft.status_code==200,draft.text
    assert draft.json()['data']['status']=='DRAFT' and draft.json()['data']['revision']==1
    submitted=mutate(c,'PUT',f"/me/preferences/{period['id']}",{'expected_revision':1,'submit':True,'items':[{'work_date':'2026-11-10','template_id':int(template['id']),'kind':'AVOID','weight':4}]})
    assert submitted.status_code==200
    assert submitted.json()['data']['status']=='SUBMITTED'
    assert login(c).status_code==200
    statuses=c.get(f"/api/v1/periods/{period['id']}/submission-status").json()['data']
    assert statuses['counts']=={'SUBMITTED':1,'DRAFT':0,'NOT_SUBMITTED':0}
    assert statuses['items'][0]['status']=='SUBMITTED'
    proxy=mutate(c,'PUT',f"/employees/{statuses['items'][0]['employee_id']}/preferences/{period['id']}",{'expected_revision':2,'submit':True,'items':[{'work_date':'2026-11-11','template_id':int(template['id']),'kind':'PREFER','weight':3}],'reason':'管理员电话核实代录'})
    assert proxy.status_code==200,proxy.text
    assert login(c,'worker').status_code==200
    invalid=mutate(c,'PUT',f"/me/preferences/{period['id']}",{'expected_revision':3,'submit':False,'items':[{'work_date':'2026-12-01','template_id':int(template['id']),'kind':'PREFER','weight':3}]})
    assert invalid.status_code==422


def test_manager_availability_proxy_validation_and_permissions(fixture):
    c,_=fixture
    active_worker(c)
    assert login(c).status_code==200
    employees=c.get('/api/v1/employees').json()['data']['items']
    employee_id=employees[0]['id']
    proxy=mutate(c,'PUT',f'/employees/{employee_id}/availability/weekly',{'expected_revision':0,'effective_from':'2026-11-09','windows':[{'weekday':1,'start_time':'09:00','end_time':'17:00'}],'reason':'员工线下提交纸质表'})
    assert proxy.status_code==200,proxy.text
    data=c.get(f'/api/v1/employees/{employee_id}/availability?from=2026-11-09&to=2026-11-09').json()['data']
    assert data['days'][0]['windows']==[{'start_time':'09:00','end_time':'17:00'}]
    overlap=mutate(c,'PUT',f'/employees/{employee_id}/availability/weekly',{'expected_revision':1,'effective_from':'2026-11-09','windows':[{'weekday':1,'start_time':'08:00','end_time':'12:00'},{'weekday':1,'start_time':'11:00','end_time':'15:00'}],'reason':'测试重叠'})
    assert overlap.status_code==422
    assert mutate(c,'PUT',f'/employees/{employee_id}/availability/overrides/2026-11-10',{'expected_revision':0,'mode':'REPLACE','windows':[],'reason':'员工当天请假待审批前不可用'}).status_code==200
    assert login(c,'worker').status_code==200
    assert c.get(f'/api/v1/employees/{employee_id}/availability?from=2026-11-09&to=2026-11-10').status_code==403
    assert c.get('/api/v1/periods/999/submission-status').status_code==403
