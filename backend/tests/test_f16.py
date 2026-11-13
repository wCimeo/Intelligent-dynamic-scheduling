from datetime import date,timedelta
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
from test_f8 import prepare_valid_draft


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


def test_settings_update_audit_and_default_solver_limit(fixture):
    c,engine=fixture
    assert login(c).status_code==200
    current=c.get('/api/v1/settings').json()['data']
    assert current['timezone']=='Asia/Shanghai'
    updated=mutate(c,'PATCH','/settings',{'store_name':'交大咖啡实验门店','demo_mode':True,
        'solver_time_limit_seconds':5,'expected_revision':current['revision']})
    assert updated.status_code==200,updated.text
    assert updated.json()['data']['store_name']=='交大咖啡实验门店'
    assert updated.json()['data']['solver_time_limit_seconds']==5
    stale=mutate(c,'PATCH','/settings',{'store_name':'重复','demo_mode':True,
        'solver_time_limit_seconds':10,'expected_revision':current['revision']})
    assert stale.status_code==409
    period,version,validation=prepare_valid_draft(c)
    task=post(c,'/solver-tasks',{'period_id':int(period['id']),'draft_version_id':int(version['id']),
        'expected_draft_revision':version['revision']})
    assert task.status_code==202,task.text
    assert task.json()['data']['input_summary']['time_limit_seconds']==5
    audit=c.get('/api/v1/audit-events?category=settings&actor_search=manager')
    assert audit.status_code==200
    item=audit.json()['data']['items'][0]
    assert item['action']=='settings.updated' and item['action_label']=='更新基础设置'
    assert item['summary']['after']['store_name']=='交大咖啡实验门店'


def test_employee_can_only_read_public_settings(fixture):
    c,_=fixture
    assert login(c).status_code==200
    c.get('/api/v1/settings')
    period,version,validation=prepare_valid_draft(c)
    assert login(c,'worker1').status_code==200
    public=c.get('/api/v1/settings/public')
    assert public.status_code==200
    assert public.json()['data']['store_name']=='校园咖啡门店'
    assert 'solver_time_limit_seconds' not in public.json()['data']
    assert c.get('/api/v1/settings').status_code==403
    assert c.get('/api/v1/audit-events').status_code==403
    assert mutate(c,'PATCH','/settings',{'store_name':'越权修改','demo_mode':False,
        'solver_time_limit_seconds':30,'expected_revision':1}).status_code==403
