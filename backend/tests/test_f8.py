import secrets
from datetime import date,datetime as real_datetime,timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,OutboxEvent,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login
from test_f6 import setup_inputs


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


def full_assignments(draft,employee_ids):
    items=[]
    for shift in draft['shifts']:
        if not shift['enabled']: continue
        for demand in shift['demands']:
            for index in range(demand['required_count']):
                items.append({'shift_key':shift['shift_key'],'employee_id':int(employee_ids[index%len(employee_ids)]),
                    'position_id':int(demand['position_id']),'locked':False})
    return items


def prepare_valid_draft(c):
    _,period,draft=setup_inputs(c,2)
    employees=[item['id'] for item in c.get('/api/v1/employees').json()['data']['items']]
    saved=mutate(c,'PUT',f"/versions/{draft['id']}/assignments",{'expected_revision':draft['revision'],'items':full_assignments(draft,employees)})
    assert saved.status_code==200,saved.text
    validation=mutate(c,'POST',f"/versions/{draft['id']}/validate",{'expected_revision':saved.json()['data']['revision']}).json()['data']
    assert validation['valid'] is True
    return period,saved.json()['data'],validation


def publish(c,version,period,validation,base=None,key=None):
    body={'expected_draft_revision':version['revision'],'expected_period_revision':period['revision'],
        'base_published_version_id':int(base['id']) if base else None,'expected_input_revision':validation['input_revision']}
    return post(c,f"/versions/{version['id']}/publish",body,key or secrets.token_hex(16))


def test_publish_supersede_diff_and_employee_schedule(fixture):
    c,engine=fixture
    period,version,validation=prepare_valid_draft(c)
    key=secrets.token_hex(16)
    first=publish(c,version,period,validation,key=key)
    assert first.status_code==200,first.text
    first_data=first.json()['data']
    replay=publish(c,version,period,validation,key=key)
    assert replay.status_code==200 and replay.json()['data']==first_data
    period_after=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    assert period_after['current_version_id']==version['id']
    copy=post(c,f"/versions/{version['id']}/copy-to-draft",{'expected_period_revision':first_data['period_revision']})
    assert copy.status_code==201,copy.text
    second=copy.json()['data']
    period_for_second=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    second_validation=mutate(c,'POST',f"/versions/{second['id']}/validate",{'expected_revision':second['revision']}).json()['data']
    second_publish=publish(c,second,period_for_second,second_validation,version)
    assert second_publish.status_code==200,second_publish.text
    versions=c.get(f"/api/v1/periods/{period['id']}/versions").json()['data']
    by_id={item['id']:item for item in versions['items']}
    assert by_id[version['id']]['status']=='SUPERSEDED'
    assert by_id[second['id']]['status']=='PUBLISHED'
    diff=c.get(f"/api/v1/versions/{version['id']}/diff?other_version_id={second['id']}").json()['data']
    assert diff['summary']['shifts_changed']==0 and diff['summary']['assignments_added']==0
    with Session(engine) as db:
        assert db.query(OutboxEvent).filter(OutboxEvent.event_type=='schedule.published').count()==2
    assert login(c,'worker1').status_code==200
    week_start=date.fromisoformat(period['week_start']);week_end=week_start+timedelta(days=6)
    schedules=c.get(f"/api/v1/me/schedules?from={week_start.isoformat()}&to={week_end.isoformat()}").json()['data']['items']
    assert len(schedules)==7 and all(item['version_id']==second['id'] for item in schedules)


def test_publish_blocks_hard_conflicts_and_stale_period(fixture):
    c,_=fixture
    period,version,validation=prepare_valid_draft(c)
    assert publish(c,version,period,validation).status_code==200
    period_after=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    copy=post(c,f"/versions/{version['id']}/copy-to-draft",{'expected_period_revision':period_after['revision']}).json()['data']
    period_for_copy=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    broken_items=[{'shift_key':item['shift_key'],'employee_id':int(item['employee_id']),'position_id':int(item['position_id']),'locked':item['locked']} for item in copy['assignments'][1:]]
    broken=mutate(c,'PUT',f"/versions/{copy['id']}/assignments",{'expected_revision':copy['revision'],'items':broken_items}).json()['data']
    broken_validation=mutate(c,'POST',f"/versions/{copy['id']}/validate",{'expected_revision':broken['revision']}).json()['data']
    blocked=publish(c,broken,period_for_copy,broken_validation,version)
    assert blocked.status_code==422 and blocked.json()['code']=='HARD_CONSTRAINT_VIOLATION'
    period_now=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    another=post(c,f"/versions/{version['id']}/copy-to-draft",{'expected_period_revision':period_now['revision']}).json()['data']
    stale=post(c,f"/versions/{another['id']}/publish",{'expected_draft_revision':another['revision'],'expected_period_revision':period_now['revision']-1,'base_published_version_id':int(version['id']),'expected_input_revision':broken_validation['input_revision']})
    assert stale.status_code==409 and stale.json()['code']=='VERSION_CONFLICT'


def test_started_shift_is_immutable_after_publication(fixture,monkeypatch):
    import app.main as main_module
    c,_=fixture
    period,version,validation=prepare_valid_draft(c)
    frozen_day=date.fromisoformat(period['week_start'])+timedelta(days=1)
    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls,tz=None):
            value=real_datetime(frozen_day.year,frozen_day.month,frozen_day.day,12,0,0)
            return value.replace(tzinfo=tz) if tz else value
    monkeypatch.setattr(main_module,'datetime',FrozenDateTime)
    first=publish(c,version,period,validation)
    assert first.status_code==200,first.text
    period_after=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    copied=post(c,f"/versions/{version['id']}/copy-to-draft",{'expected_period_revision':period_after['revision']}).json()['data']
    period_after_copy=c.get(f"/api/v1/periods/{period['id']}").json()['data']
    items=[{'shift_key':item['shift_key'],'employee_id':int(item['employee_id']),'position_id':int(item['position_id']),'locked':item['locked']} for item in copied['assignments']]
    started_dates={period['week_start'],frozen_day.isoformat()}
    started_keys={shift['shift_key'] for shift in copied['shifts'] if shift['work_date'] in started_dates}
    target_index=next(index for index,item in enumerate(items) if item['shift_key'] in started_keys)
    items[target_index]['locked']=True
    changed=mutate(c,'PUT',f"/versions/{copied['id']}/assignments",{'expected_revision':copied['revision'],'items':items}).json()['data']
    changed_validation=mutate(c,'POST',f"/versions/{copied['id']}/validate",{'expected_revision':changed['revision']}).json()['data']
    blocked=post(c,f"/versions/{copied['id']}/publish",{'expected_draft_revision':changed['revision'],'expected_period_revision':period_after_copy['revision'],'base_published_version_id':int(version['id']),'expected_input_revision':changed_validation['input_revision']})
    assert blocked.status_code==409 and blocked.json()['code']=='IMMUTABLE_SHIFT_CHANGED'
