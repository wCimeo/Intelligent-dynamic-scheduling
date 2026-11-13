import pytest
from datetime import date,timedelta
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,login
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


def test_shared_publication_context_events_and_audit(fixture):
    c,_=fixture
    period,version,validation=prepare_valid_draft(c)
    published=publish(c,version,period,validation)
    assert published.status_code==200,published.text
    capabilities=c.get('/api/v1/shared/capabilities')
    assert capabilities.status_code==200
    assert 'current_published_schedule' in capabilities.json()['data']['capabilities']
    current=c.get(f"/api/v1/shared/periods/{period['id']}/published-version")
    assert current.status_code==200
    assert current.json()['data']['id']==version['id']
    assert len(current.json()['data']['assignments'])==14
    employee_id=current.json()['data']['assignments'][0]['employee_id']
    week_start=date.fromisoformat(period['week_start']);week_end=week_start+timedelta(days=6)
    schedule=c.get(f"/api/v1/shared/employees/{employee_id}/schedule?from={week_start.isoformat()}&to={week_end.isoformat()}")
    assert schedule.status_code==200 and len(schedule.json()['data']['items'])==7
    events=c.get('/api/v1/shared/outbox-events?after_id=0&state=PENDING')
    assert events.status_code==200 and events.json()['data']['items']
    event=events.json()['data']['items'][0]
    assert event['event_type']=='schedule.published'
    ack=post(c,f"/shared/outbox-events/{event['id']}/ack",None)
    assert ack.status_code==200 and ack.json()['data']['state']=='PROCESSED'
    audit=c.get(f"/api/v1/shared/audit-events?entity_type=schedule&entity_id={version['id']}")
    assert audit.status_code==200
    assert any(item['action']=='schedule.published' for item in audit.json()['data']['items'])


def test_shared_routes_require_manager(fixture):
    c,_=fixture
    prepare_valid_draft(c)
    assert login(c,'worker1').status_code==200
    assert c.get('/api/v1/shared/capabilities').status_code==403
    assert c.get('/api/v1/shared/outbox-events').status_code==403
    assert c.get('/api/v1/shared/audit-events').status_code==403
