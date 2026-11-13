import secrets
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,AdjustmentEvent,LeaveRequest,OutboxEvent,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login
from test_f8 import prepare_valid_draft,publish


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


def published_context(c):
    period,version,validation=prepare_valid_draft(c)
    published=publish(c,version,period,validation)
    assert published.status_code==200,published.text
    current=c.get(f"/api/v1/shared/periods/{period['id']}/published-version").json()['data']
    employees=c.get('/api/v1/employees').json()['data']['items']
    xiaolin=next(item for item in employees if item['employee_no']=='E601')
    assignment=next(item for item in current['assignments'] if item['employee_id']==xiaolin['id'])
    shift=next(item for item in current['shifts'] if item['shift_key']==assignment['shift_key'])
    return period,current,xiaolin,shift


def leave_body(shift):
    return {'start_date':shift['work_date'],'start_time':shift['start_time'],'end_date':shift['work_date'],'end_time':shift['end_time'],'reason':'学校临时实验安排'}


def test_leave_create_approve_impact_and_validation(fixture):
    c,engine=fixture
    period,current,employee,shift=published_context(c)
    assert login(c,'worker1').status_code==200
    body=leave_body(shift)
    preview=post(c,'/me/leave-requests/preview',{key:value for key,value in body.items() if key!='reason'})
    assert preview.status_code==200 and preview.json()['data']['affected_shifts'],preview.text
    key=secrets.token_hex(16)
    created=post(c,'/me/leave-requests',{**body,'reason':'学校临时实验安排'},key)
    assert created.status_code==201,created.text
    leave_id=created.json()['data']['id']
    assert created.json()['data']['status']=='PENDING'
    replay=post(c,'/me/leave-requests',{**body,'reason':'学校临时实验安排'},key)
    assert replay.status_code==201 and replay.json()['data']['id']==leave_id
    overlap=post(c,'/me/leave-requests',{**body,'reason':'重复申请'})
    assert overlap.status_code==409 and overlap.json()['code']=='LEAVE_OVERLAP'
    assert login(c).status_code==200
    manager_list=c.get('/api/v1/leave-requests?status=PENDING').json()['data']
    assert manager_list['total']==1
    review_key=secrets.token_hex(16)
    approved=post(c,f'/leave-requests/{leave_id}/review',{'decision':'APPROVE','expected_revision':1,'note':'已电话核实'},review_key)
    assert approved.status_code==200,approved.text
    assert approved.json()['data']['status']=='APPROVED'
    assert approved.json()['data']['open_gap_count']>=1
    replay_review=post(c,f'/leave-requests/{leave_id}/review',{'decision':'APPROVE','expected_revision':1,'note':'已电话核实'},review_key)
    assert replay_review.status_code==200
    with Session(engine) as db:
        assert db.scalar(select(AdjustmentEvent).where(AdjustmentEvent.source_id==int(leave_id))) is not None
        assert db.scalar(select(OutboxEvent).where(OutboxEvent.event_type=='leave.approved')) is not None
    period_now=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    copied=post(c,f"/versions/{current['id']}/copy-to-draft",{'expected_period_revision':period_now['revision']})
    assert copied.status_code==201,copied.text
    validation=mutate(c,'POST',f"/versions/{copied.json()['data']['id']}/validate",{'expected_revision':copied.json()['data']['revision']})
    assert validation.status_code==200,validation.text
    assert any(item['rule_code']=='UNAVAILABLE' and item['employee_id']==employee['id'] for item in validation.json()['data']['hard_conflicts'])


def test_leave_withdraw_reject_and_employee_privacy(fixture):
    c,engine=fixture
    _,_,_,shift=published_context(c)
    assert login(c,'worker1').status_code==200
    first=post(c,'/me/leave-requests',{**leave_body(shift),'reason':'待撤回申请'}).json()['data']
    withdrawn=post(c,f"/me/leave-requests/{first['id']}/withdraw",{'expected_revision':first['revision']})
    assert withdrawn.status_code==200 and withdrawn.json()['data']['status']=='WITHDRAWN'
    second=post(c,'/me/leave-requests',{**leave_body(shift),'reason':'重新提交'}).json()['data']
    assert login(c,'worker2').status_code==200
    assert c.get(f"/api/v1/leave-requests/{second['id']}").status_code==404
    assert login(c).status_code==200
    rejected=post(c,f"/leave-requests/{second['id']}/review",{'decision':'REJECT','expected_revision':second['revision'],'note':'当天必须到岗'})
    assert rejected.status_code==200 and rejected.json()['data']['status']=='REJECTED'
    with Session(engine) as db:
        assert db.scalars(select(AdjustmentEvent).where(AdjustmentEvent.source_id==int(second['id']))).all()==[]
