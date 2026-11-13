import secrets
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User,Employee,Skill,Position
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login


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


def test_employee_skills_and_position_qualification_flow(fixture):
    c,_=fixture
    assert login(c).status_code==200
    employee=post(c,'/employees',{'employee_no':'E100','name':'林晓','employment_type':'FULL_TIME','weekly_limit_minutes':2400})
    assert employee.status_code==201
    employee_id=employee.json()['data']['id']
    brew=post(c,'/skills',{'code':'brew','name':'咖啡制作'}).json()['data']
    cashier=post(c,'/skills',{'code':'cashier','name':'收银'}).json()['data']
    position=post(c,'/positions',{'code':'barista','name':'咖啡师'}).json()['data']
    position_id=position['id']
    required=mutate(c,'PUT',f'/positions/{position_id}/skills',{'skill_ids':[int(brew['id']),int(cashier['id'])],'expected_revision':position['revision']})
    assert required.status_code==200,required.text
    assert {item['code'] for item in required.json()['data']['required_skills']}=={'brew','cashier'}
    unqualified=c.get(f'/api/v1/employees?position_id={position_id}').json()['data']
    assert unqualified['total']==0
    assigned=mutate(c,'PUT',f'/employees/{employee_id}/skills',{'skill_ids':[int(brew['id']),int(cashier['id'])],'expected_revision':employee.json()['data']['revision']})
    assert assigned.status_code==200,assigned.text
    assigned_data=assigned.json()['data']
    assert {item['code'] for item in assigned_data['skills']}=={'brew','cashier'}
    assert [item['code'] for item in assigned_data['qualified_positions']]==['barista']
    qualified=c.get(f'/api/v1/employees?position_id={position_id}&status=ACTIVE').json()['data']
    assert qualified['total']==1 and qualified['items'][0]['employee_no']=='E100'
    edited=mutate(c,'PATCH',f'/employees/{employee_id}',{'name':'林晓然','weekly_limit_minutes':1800,'expected_revision':assigned_data['revision']})
    assert edited.status_code==200
    assert edited.json()['data']['name']=='林晓然' and edited.json()['data']['weekly_limit_minutes']==1800
    disabled=mutate(c,'PATCH',f'/employees/{employee_id}/status',{'status':'INACTIVE','expected_revision':edited.json()['data']['revision']})
    assert disabled.status_code==200
    assert disabled.json()['data']['employee']['status']=='INACTIVE'
    assert disabled.json()['data']['affected_future_assignments']==0
    assert c.get('/api/v1/employees?status=INACTIVE').json()['data']['total']==1
    enabled=mutate(c,'PATCH',f'/employees/{employee_id}/status',{'status':'ACTIVE','expected_revision':disabled.json()['data']['employee']['revision']})
    assert enabled.status_code==200


def test_qualification_catalog_permissions_and_employee_profile(fixture):
    c,engine=fixture
    assert login(c).status_code==200
    employee=post(c,'/employees',{'employee_no':'E101','name':'陈悦'}).json()['data']
    brew=post(c,'/skills',{'code':'brew','name':'咖啡制作'}).json()['data']
    cashier=post(c,'/skills',{'code':'cashier','name':'收银'}).json()['data']
    position=post(c,'/positions',{'code':'barista','name':'咖啡师'}).json()['data']
    mutate(c,'PUT',f"/positions/{position['id']}/skills",{'skill_ids':[int(brew['id']),int(cashier['id'])],'expected_revision':position['revision']})
    mutate(c,'PUT',f"/employees/{employee['id']}/skills",{'skill_ids':[int(brew['id']),int(cashier['id'])],'expected_revision':employee['revision']})
    account=post(c,'/admin/accounts',{'username':'f2_worker','name':'陈悦','employee_id':int(employee['id'])})
    assert account.status_code==201,account.text
    temporary_password=account.json()['data']['temporary_password']
    disabled_skill=mutate(c,'PATCH',f"/skills/{cashier['id']}",{'name':'收银','active':False,'expected_revision':cashier['revision']})
    assert disabled_skill.status_code==200
    assert login(c,'f2_worker',temporary_password).json()['data']['session_scope']=='PASSWORD_CHANGE'
    changed=post(c,'/auth/change-password',{'old_password':temporary_password,'new_password':'f2-worker-password-123','confirmation':'f2-worker-password-123'})
    assert changed.status_code==200
    assert login(c,'f2_worker','f2-worker-password-123').json()['data']['session_scope']=='BUSINESS'
    visible_skills=c.get('/api/v1/skills').json()['data']
    assert visible_skills['total']==1 and visible_skills['items'][0]['code']=='brew'
    profile=c.get('/api/v1/me/profile').json()['data']
    assert {item['code'] for item in profile['skills']}=={'brew','cashier'}
    assert [item['code'] for item in profile['qualified_positions']]==['barista']
    assert post(c,'/skills',{'code':'latte','name':'拉花'}).status_code==403
    with Session(engine) as db:
        assert db.scalar(select(Skill).where(Skill.code=='cashier')).active is False
        assert db.scalar(select(Position).where(Position.code=='barista')) is not None


def test_f2_validation_conflicts_and_versions(fixture):
    c,_=fixture
    assert login(c).status_code==200
    first=post(c,'/skills',{'code':'brew','name':'咖啡制作'})
    assert first.status_code==201
    assert post(c,'/skills',{'code':'BREW','name':'重复技能'}).status_code==409
    stale=mutate(c,'PATCH',f"/skills/{first.json()['data']['id']}",{'name':'咖啡制作','active':False,'expected_revision':2})
    assert stale.status_code==409 and stale.json()['code']=='VERSION_CONFLICT'
    position=post(c,'/positions',{'code':'service','name':'服务'}).json()['data']
    duplicate=mutate(c,'PUT',f"/positions/{position['id']}/skills",{'skill_ids':[int(first.json()['data']['id']),int(first.json()['data']['id'])],'expected_revision':position['revision']})
    assert duplicate.status_code==422
    employee=post(c,'/employees',{'employee_no':'E102','name':'周宁'}).json()['data']
    unavailable=mutate(c,'PUT',f"/employees/{employee['id']}/skills",{'skill_ids':[9999],'expected_revision':employee['revision']})
    assert unavailable.status_code==409 and unavailable.json()['code']=='SKILL_UNAVAILABLE'
