import secrets
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,OutboxEvent,SchedulePeriod,ScheduleVersion,SwapRequest,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login
from test_f6 import setup_inputs,future_week_start
from test_f8 import full_assignments,publish


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


def published_swap_context(c,alternate=False):
    _,period,draft=setup_inputs(c,1,week_start=future_week_start().isoformat())
    employees=c.get('/api/v1/employees').json()['data']['items']
    employee_a=next(item for item in employees if item['employee_no']=='E601')
    employee_b=next(item for item in employees if item['employee_no']=='E602')
    ids=[employee_a['id'],employee_b['id']]
    items=[]
    for index,shift in enumerate(draft['shifts']):
        demand=shift['demands'][0]
        employee_id=ids[index%2] if alternate else ids[0]
        items.append({'shift_key':shift['shift_key'],'employee_id':int(employee_id),'position_id':int(demand['position_id']),'locked':False})
    saved=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':draft['revision'],'items':items})
    assert saved.status_code==200,saved.text
    validation=mutate(c,'POST',f"/versions/{draft['id']}/validate",{'expected_revision':saved.json()['data']['revision']}).json()['data']
    published=publish(c,saved.json()['data'],period,validation)
    assert published.status_code==200,published.text
    current=c.get(f"/api/v1/shared/periods/{period['id']}/published-version").json()['data']
    source_assignment=next(item for item in current['assignments'] if item['employee_id']==employee_a['id'])
    return period,current,employee_a,employee_b,source_assignment


def test_transfer_request_acceptance_and_atomic_publish(fixture):
    c,engine=fixture
    period,current,employee_a,employee_b,source=published_swap_context(c)
    assert login(c,'worker1').status_code==200
    candidates=c.get(f"/api/v1/me/swap-candidates?source_shift_key={source['shift_key']}&source_position_id={source['position_id']}")
    assert candidates.status_code==200
    assert any(item['employee_id']==employee_b['id'] and item['eligible'] for item in candidates.json()['data']['items'])
    body={'mode':'TRANSFER','target_employee_id':int(employee_b['id']),'source_shift_key':source['shift_key'],'source_position_id':int(source['position_id']),'note':'临时换班'}
    created=post(c,'/me/swap-requests',body)
    assert created.status_code==201,created.text
    swap=created.json()['data']
    assert swap['status']=='PENDING_TARGET'
    assert login(c,'worker2').status_code==200
    accepted=post(c,f"/me/swap-requests/{swap['id']}/respond",{'decision':'ACCEPT','expected_revision':swap['revision'],'note':'可以'})
    assert accepted.status_code==200
    assert accepted.json()['data']['status']=='PENDING_MANAGER'
    assert login(c).status_code==200
    approved=post(c,f"/swap-requests/{swap['id']}/review",{'decision':'APPROVE','expected_revision':accepted.json()['data']['revision'],'note':'已核实'})
    assert approved.status_code==200,approved.text
    assert approved.json()['data']['status']=='APPROVED'
    result_id=approved.json()['data']['result_version_id']
    period_after=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    assert period_after['current_version_id']==result_id
    new_version=c.get(f"/api/v1/versions/{result_id}").json()['data']
    replaced=next(item for item in new_version['assignments'] if item['shift_key']==source['shift_key'])
    assert replaced['employee_id']==employee_b['id']
    with Session(engine) as db:
        assert db.scalar(select(SwapRequest).where(SwapRequest.id==int(swap['id']))).status=='APPROVED'
        assert db.scalar(select(OutboxEvent).where(OutboxEvent.event_type=='swap.approved')) is not None


def test_exchange_swaps_both_assignments(fixture):
    c,_=fixture
    period,current,employee_a,employee_b,source=published_swap_context(c,alternate=True)
    target=next(item for item in current['assignments'] if item['employee_id']==employee_b['id'])
    assert login(c,'worker1').status_code==200
    exchange={'mode':'EXCHANGE','target_employee_id':int(employee_b['id']),'source_shift_key':source['shift_key'],
        'source_position_id':int(source['position_id']),'target_shift_key':target['shift_key'],
        'target_position_id':int(target['position_id'])}
    created=post(c,'/me/swap-requests',exchange)
    assert created.status_code==201,created.text
    swap=created.json()['data']
    assert login(c,'worker2').status_code==200
    accepted=post(c,f"/me/swap-requests/{swap['id']}/respond",{'decision':'ACCEPT','expected_revision':swap['revision']})
    assert login(c).status_code==200
    approved=post(c,f"/swap-requests/{swap['id']}/review",{'decision':'APPROVE','expected_revision':accepted.json()['data']['revision']})
    assert approved.status_code==200,approved.text
    version=c.get(f"/api/v1/versions/{approved.json()['data']['result_version_id']}").json()['data']
    source_after=next(item for item in version['assignments'] if item['shift_key']==source['shift_key'])
    target_after=next(item for item in version['assignments'] if item['shift_key']==target['shift_key'])
    assert source_after['employee_id']==employee_b['id']
    assert target_after['employee_id']==employee_a['id']


def test_target_rejection_keeps_current_version(fixture):
    c,_=fixture
    period,current,employee_a,employee_b,source=published_swap_context(c)
    assert login(c,'worker1').status_code==200
    created=post(c,'/me/swap-requests',{'mode':'TRANSFER','target_employee_id':int(employee_b['id']),
        'source_shift_key':source['shift_key'],'source_position_id':int(source['position_id'])}).json()['data']
    assert login(c,'worker2').status_code==200
    rejected=post(c,f"/me/swap-requests/{created['id']}/respond",{'decision':'REJECT','expected_revision':created['revision'],'note':'不方便'})
    assert rejected.status_code==200 and rejected.json()['data']['status']=='TARGET_REJECTED'
    assert login(c).status_code==200
    assert c.get(f"/api/v1/periods/{period['id']}").json()['data']['current_version_id']==current['id']
