import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,Notification,OutboxEvent,PublicationReceipt,User
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


def test_schedule_notifications_and_publication_confirmation(fixture):
    c,engine=fixture
    period,version,validation=prepare_valid_draft(c)
    assert publish(c,version,period,validation).status_code==200
    processed=post(c,'/notifications/process',None)
    assert processed.status_code==200 and processed.json()['data']['processed']>=1
    assert post(c,'/notifications/process',None).json()['data']['processed']==0
    assert login(c,'worker1').status_code==200
    notifications=c.get('/api/v1/me/notifications?unread_only=true').json()['data']
    assert notifications['unread']>=1
    assert any(item['category']=='SCHEDULE_PUBLISHED' for item in notifications['items'])
    receipts=c.get('/api/v1/me/publication-receipts?status=PENDING').json()['data']['items']
    assert len(receipts)==1
    receipt=receipts[0]
    confirmed=post(c,f"/me/publication-receipts/{receipt['id']}/confirm",{'expected_revision':receipt['revision']})
    assert confirmed.status_code==200 and confirmed.json()['data']['status']=='CONFIRMED'
    assert login(c).status_code==200
    status=c.get(f"/api/v1/periods/{period['id']}/confirmation-status").json()['data']
    assert status['counts']['CONFIRMED']==1 and status['counts']['PENDING']==1
    period_now=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    copied=post(c,f"/versions/{version['id']}/copy-to-draft",{'expected_period_revision':period_now['revision']}).json()['data']
    new_validation=mutate(c,'POST',f"/versions/{copied['id']}/validate",{'expected_revision':copied['revision']}).json()['data']
    period_for_copy=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    assert publish(c,copied,period_for_copy,new_validation,version).status_code==200
    post(c,'/notifications/process',None)
    assert login(c,'worker1').status_code==200
    outdated=post(c,f"/me/publication-receipts/{receipt['id']}/confirm",{'expected_revision':confirmed.json()['data']['revision']})
    assert outdated.status_code==409 and outdated.json()['code']=='RECEIPT_OUTDATED'
    with Session(engine) as db:
        assert db.scalar(select(OutboxEvent).where(OutboxEvent.state=='PENDING')) is None


def test_leave_notifications_are_targeted_and_idempotent(fixture):
    c,_=fixture
    period,version,validation=prepare_valid_draft(c)
    assert publish(c,version,period,validation).status_code==200
    current=c.get(f"/api/v1/shared/periods/{period['id']}/published-version").json()['data']
    employees=c.get('/api/v1/employees').json()['data']['items']
    employee=next(item for item in employees if item['employee_no']=='E601')
    assignment=next(item for item in current['assignments'] if item['employee_id']==employee['id'])
    shift=next(item for item in current['shifts'] if item['shift_key']==assignment['shift_key'])
    assert login(c,'worker1').status_code==200
    leave=post(c,'/me/leave-requests',{'start_date':shift['work_date'],'start_time':shift['start_time'],
        'end_date':shift['work_date'],'end_time':shift['end_time'],'reason':'课程安排'}).json()['data']
    assert login(c).status_code==200
    post(c,f"/leave-requests/{leave['id']}/review",{'decision':'APPROVE','expected_revision':leave['revision'],'note':'已核实'})
    post(c,'/notifications/process',None)
    assert post(c,'/notifications/process',None).json()['data']['processed']==0
    manager_notifications=c.get('/api/v1/me/notifications').json()['data']
    assert any(item['category']=='LEAVE_REQUEST' for item in manager_notifications['items'])
    assert login(c,'worker1').status_code==200
    employee_notifications=c.get('/api/v1/me/notifications').json()['data']
    assert any(item['category']=='LEAVE_RESULT' for item in employee_notifications['items'])
