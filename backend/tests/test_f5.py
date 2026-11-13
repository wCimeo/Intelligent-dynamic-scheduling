import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,login,register


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


def rule_body(week='2026-11-09',daily=1,minutes=2400,days=6,rest=600,preference=30,hours=20,evening=10):
    return {'effective_week':week,'daily_shift_limit':daily,'weekly_minutes_limit':minutes,
        'consecutive_days_limit':days,'min_rest_minutes':rest,
        'weights':{'preference':preference,'hours_balance':hours,'evening_balance':evening}}


def test_rule_versions_effective_selection_and_validation(fixture):
    c,_=fixture
    assert login(c).status_code==200
    first=post(c,'/rule-versions',rule_body())
    assert first.status_code==201,first.text
    assert first.json()['data']['version_no']==1
    invalid_monday=post(c,'/rule-versions',rule_body('2026-11-10'))
    assert invalid_monday.status_code==422
    invalid_limit=post(c,'/rule-versions',rule_body(daily=0))
    assert invalid_limit.status_code==422
    second=post(c,'/rule-versions',rule_body('2026-11-16',daily=2,minutes=3000,days=5,rest=720,preference=50))
    assert second.status_code==201
    assert second.json()['data']['version_no']==2
    third=post(c,'/rule-versions',rule_body('2026-11-16',daily=1,minutes=1800,days=4,rest=660))
    assert third.status_code==201
    assert third.json()['data']['version_no']==3
    week1=c.get('/api/v1/rule-versions/effective?week=2026-11-09').json()['data']
    week2=c.get('/api/v1/rule-versions/effective?week=2026-11-16').json()['data']
    assert week1['id']==first.json()['data']['id']
    assert week2['id']==third.json()['data']['id']
    listing=c.get('/api/v1/rule-versions').json()['data']
    assert listing['total']==3 and listing['items'][0]['created_by_name']=='管理员'


def test_employee_public_rule_and_permissions(fixture):
    c,_=fixture
    registered=register(c)
    uid=registered.json()['data']['user_id']
    assert login(c).status_code==200
    rule=post(c,'/rule-versions',rule_body()).json()['data']
    assert post(c,f'/admin/accounts/{uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'E500','name':'规则员工'}}).status_code==200
    assert login(c,'worker').status_code==200
    assert c.get('/api/v1/rule-versions').status_code==403
    detail=c.get(f"/api/v1/rule-versions/{rule['id']}")
    assert detail.status_code==200
    assert 'created_by' not in detail.json()['data']
    effective=c.get('/api/v1/rule-versions/effective?week=2026-11-09')
    assert effective.status_code==200
    assert effective.json()['data']['weights']['preference']==30
    assert post(c,'/rule-versions',rule_body()).status_code==403


def test_schedule_draft_binds_rule_version_at_creation(fixture):
    c,_=fixture
    assert login(c).status_code==200
    first=post(c,'/rule-versions',rule_body()).json()['data']
    position=post(c,'/positions',{'code':'barista','name':'咖啡师'}).json()['data']
    template=post(c,'/shift-templates',{'code':'morning','name':'早班','start_time':'08:00','end_time':'14:00','demands':[{'position_id':int(position['id']),'required_count':2}]}).json()['data']
    period=post(c,'/periods',{'week_start':'2026-11-09'}).json()['data']
    first_draft=post(c,f"/periods/{period['id']}/drafts",{}).json()['data']
    assert first_draft['rule_version_id']==first['id']
    newer=post(c,'/rule-versions',rule_body(daily=2,preference=60)).json()['data']
    assert c.get(f"/api/v1/rule-versions/{first['id']}").json()['data']['daily_shift_limit']==1
    second_draft=post(c,f"/periods/{period['id']}/drafts",{}).json()['data']
    assert second_draft['rule_version_id']==newer['id']
    assert first_draft['rule_version_id']!=second_draft['rule_version_id']
