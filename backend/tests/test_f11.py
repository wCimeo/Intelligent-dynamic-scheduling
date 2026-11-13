import secrets
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import AdjustmentCandidate,AdjustmentEvent,Base,OutboxEvent,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login
from test_f10 import published_swap_context


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


def create_gap(c):
    period,current,employee_a,employee_b,source=published_swap_context(c)
    source_shift=next(item for item in current['shifts'] if item['shift_key']==source['shift_key'])
    source={**source,'work_date':source_shift['work_date'],'start_time':source_shift['start_time'],'end_time':source_shift['end_time']}
    assert login(c,'worker1').status_code==200
    leave=post(c,'/me/leave-requests',{'start_date':source['work_date'],'start_time':source['start_time'],
        'end_date':source['work_date'],'end_time':source['end_time'],'reason':'临时课程冲突'}).json()['data']
    assert login(c).status_code==200
    approved=post(c,f"/leave-requests/{leave['id']}/review",{'decision':'APPROVE','expected_revision':leave['revision'],'note':'已核实'})
    assert approved.status_code==200
    events=c.get('/api/v1/adjustment-events?status=OPEN').json()['data']['items']
    assert len(events)==1
    locked_assignment=next(item for item in current['assignments'] if item['shift_key']!=source['shift_key'] and item['employee_id']==employee_a['id'])
    return period,current,employee_a,employee_b,source,events[0],locked_assignment


def test_repair_candidates_and_apply_close_gap(fixture):
    c,engine=fixture
    period,current,employee_a,employee_b,source,event,locked=create_gap(c)
    generated=post(c,'/adjustment-candidates/generate',{'event_ids':[int(event['id'])],
        'locked_assignments':[{'shift_key':locked['shift_key'],'employee_id':int(locked['employee_id']),
            'position_id':int(locked['position_id']),'locked':True}],'time_limit_seconds':10})
    assert generated.status_code==201,generated.text
    data=generated.json()['data']
    assert 1<=len(data['candidates'])<=3
    assert min(item['metrics']['changed_count'] for item in data['candidates'])==1,[(item['metrics']['changed_count'],item['change_summary']) for item in data['candidates']]
    for candidate in data['candidates']:
        preserved=next(item for item in candidate['assignments'] if item['shift_key']==locked['shift_key'])
        assert preserved['employee_id']==locked['employee_id'] and preserved['locked'] is True
    first=data['candidates'][0]
    applied=post(c,f"/adjustment-candidates/{first['id']}/apply",{'expected_base_version_id':int(current['id']),
        'expected_input_revision':first['input_revision']})
    assert applied.status_code==200,applied.text
    result_id=applied.json()['data']['result_version_id']
    new_version=c.get(f"/api/v1/versions/{result_id}").json()['data']
    replacement=next(item for item in new_version['assignments'] if item['shift_key']==source['shift_key'])
    assert replacement['employee_id']==employee_b['id']
    assert c.get('/api/v1/adjustment-events?status=OPEN').json()['data']['total']==0
    with Session(engine) as db:
        applied_row=db.scalar(select(AdjustmentCandidate).where(AdjustmentCandidate.id==int(first['id'])))
        assert applied_row.status=='APPLIED'
        assert db.scalar(select(OutboxEvent).where(OutboxEvent.event_type=='adjustment.applied')) is not None


def test_candidate_expires_when_input_changes(fixture):
    c,_=fixture
    period,current,employee_a,employee_b,source,event,locked=create_gap(c)
    generated=post(c,'/adjustment-candidates/generate',{'event_ids':[int(event['id'])],'time_limit_seconds':10})
    candidate=generated.json()['data']['candidates'][0]
    changed=mutate(c,'PATCH',f"/employees/{employee_b['id']}",{'weekly_limit_minutes':2940,'expected_revision':employee_b['revision']})
    assert changed.status_code==200
    expired=post(c,f"/adjustment-candidates/{candidate['id']}/apply",{'expected_base_version_id':int(current['id']),
        'expected_input_revision':candidate['input_revision']})
    assert expired.status_code==409 and expired.json()['code']=='INPUT_CHANGED'


def test_adjustment_routes_require_manager(fixture):
    c,_=fixture
    period,current,employee_a,employee_b,source,event,locked=create_gap(c)
    assert login(c,'worker1').status_code==200
    assert c.get('/api/v1/adjustment-events').status_code==403
    assert post(c,'/adjustment-candidates/generate',{'event_ids':[int(event['id'])],'time_limit_seconds':5}).status_code==403
