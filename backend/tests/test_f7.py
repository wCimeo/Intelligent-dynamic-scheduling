import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login
from test_f6 import setup_inputs,wait_terminal


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


def assignment_items(draft,employee_ids):
    items=[]
    for shift in draft['shifts']:
        if not shift['enabled']: continue
        for demand in shift['demands']:
            for index in range(demand['required_count']):
                items.append({'shift_key':shift['shift_key'],'employee_id':int(employee_ids[index%len(employee_ids)]),
                    'position_id':int(demand['position_id']),'locked':False})
    return items


def test_manual_assignments_save_then_validation_reports_conflicts(fixture):
    c,_=fixture
    _,period,draft=setup_inputs(c,2)
    employees=c.get('/api/v1/employees').json()['data']['items']
    employee_ids=[item['id'] for item in employees]
    items=assignment_items(draft,employee_ids)
    eligible=c.get(f"/api/v1/versions/{draft['id']}/eligible-employees?shift_key={draft['shifts'][0]['shift_key']}&position_id={draft['shifts'][0]['demands'][0]['position_id']}")
    assert eligible.status_code==200 and sum(1 for item in eligible.json()['data']['items'] if item['eligible'])==2
    saved=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':draft['revision'],'items':items})
    assert saved.status_code==200,saved.text
    saved_data=saved.json()['data']
    assert len(saved_data['assignments'])==14
    valid=mutate(c,'POST',f"/versions/{draft['id']}/validate",{'expected_revision':saved_data['revision']})
    assert valid.status_code==200
    assert valid.json()['data']['valid'] is True
    missing=items[1:]
    shortage_saved=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':saved_data['revision'],'items':missing})
    assert shortage_saved.status_code==200
    shortage=mutate(c,'POST',f"/versions/{draft['id']}/validate",{'expected_revision':shortage_saved.json()['data']['revision']})
    assert shortage.json()['data']['valid'] is False
    assert any(item['rule_code']=='POSITION_SHORTAGE' for item in shortage.json()['data']['hard_conflicts'])
    extra_registration=post(c,'/auth/register',{'username':'extra_worker','name':'无技能员工','password':PASSWORD,'password_confirmation':PASSWORD})
    extra_uid=extra_registration.json()['data']['user_id']
    extra_review=post(c,f'/admin/accounts/{extra_uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'E799','name':'无技能员工'}})
    third_id=extra_review.json()['data']['employee_id']
    extra=items+[{'shift_key':draft['shifts'][0]['shift_key'],'employee_id':int(third_id),'position_id':int(draft['shifts'][0]['demands'][0]['position_id']),'locked':False}]
    extra_saved=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':shortage_saved.json()['data']['revision'],'items':extra})
    assert extra_saved.status_code==200,extra_saved.text
    extra_validation=mutate(c,'POST',f"/versions/{draft['id']}/validate",{'expected_revision':extra_saved.json()['data']['revision']})
    codes={item['rule_code'] for item in extra_validation.json()['data']['hard_conflicts']}
    assert {'SKILL_MISMATCH','UNAVAILABLE','EXTRA_ASSIGNMENT'}.issubset(codes)


def test_locked_assignment_is_preserved_by_regeneration(fixture):
    c,_=fixture
    rule,period,draft=setup_inputs(c,2)
    employees=c.get('/api/v1/employees').json()['data']['items']
    employee_ids=[item['id'] for item in employees]
    items=assignment_items(draft,employee_ids)
    items[0]['locked']=True
    locked_employee=items[0]['employee_id']
    locked_shift=items[0]['shift_key']
    saved=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':draft['revision'],'items':items})
    assert saved.status_code==200
    task=post(c,'/solver-tasks',{'period_id':int(period['id']),'draft_version_id':int(draft['id']),'expected_draft_revision':saved.json()['data']['revision'],'time_limit_seconds':10})
    assert task.status_code==202,task.text
    finished=wait_terminal(c,task.json()['data']['id'])
    assert finished['state'] in {'OPTIMAL','FEASIBLE'}
    version=c.get(f"/api/v1/versions/{draft['id']}").json()['data']
    preserved=next(item for item in version['assignments'] if item['shift_key']==locked_shift and int(item['employee_id'])==locked_employee)
    assert preserved['locked'] is True


def test_workbench_requires_manager_and_structure(fixture):
    c,_=fixture
    _,_,draft=setup_inputs(c,2)
    assert login(c,'worker1').status_code==200
    assert c.get(f"/api/v1/versions/{draft['id']}").status_code==403
    assert login(c).status_code==200
    invalid=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':draft['revision'],'items':[{'shift_key':draft['shifts'][0]['shift_key'],'employee_id':9999,'position_id':int(draft['shifts'][0]['demands'][0]['position_id']),'locked':False}]})
    assert invalid.status_code==422
