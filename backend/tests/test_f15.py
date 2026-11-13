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


def test_manager_and_employee_statistics(fixture):
    c,_=fixture
    period,version,validation=prepare_valid_draft(c)
    assert publish(c,version,period,validation).status_code==200
    post(c,'/notifications/process',None)
    stats=c.get(f"/api/v1/statistics?period_id={period['id']}").json()['data']
    assert stats['version']['id']==version['id']
    assert stats['summary']['employee_count']==2
    assert stats['summary']['shift_count']==14
    assert stats['summary']['planned_minutes']==5040
    assert stats['summary']['preference_total']==1 and stats['summary']['preference_satisfied']==1
    assert stats['summary']['confirmation_total']==2 and stats['summary']['confirmation_confirmed']==0
    assert stats['positions'][0]['position_name']=='咖啡师'
    employees=c.get('/api/v1/employees').json()['data']['items']
    worker1=next(item for item in employees if item['employee_no']=='E601')
    one=c.get(f"/api/v1/statistics?period_id={period['id']}&employee_id={worker1['id']}").json()['data']
    assert len(one['employees'])==1 and one['summary']['shift_count']==7
    assert login(c,'worker1').status_code==200
    mine=c.get(f"/api/v1/me/statistics?period_id={period['id']}").json()['data']
    assert len(mine['employees'])==1 and mine['employees'][0]['employee_id']==worker1['id']
    assert c.get(f"/api/v1/statistics?period_id={period['id']}").status_code==403


def test_csv_exports_and_formula_injection(fixture):
    c,_=fixture
    period,version,validation=prepare_valid_draft(c)
    assert publish(c,version,period,validation).status_code==200
    employees=c.get('/api/v1/employees').json()['data']['items']
    target=next(item for item in employees if item['employee_no']=='E601')
    changed=mutate(c,'PATCH',f"/employees/{target['id']}",{'name':'=HYPERLINK("http://bad")','expected_revision':target['revision']})
    assert changed.status_code==200
    schedule=c.get(f"/api/v1/exports/schedule.csv?period_id={period['id']}")
    assert schedule.status_code==200
    assert schedule.content.startswith(b'\xef\xbb\xbf')
    assert '日期,班次,开始时间'.encode('utf-8') in schedule.content
    assert 'attachment;' in schedule.headers['content-disposition']
    stats=c.get(f"/api/v1/exports/statistics.csv?period_id={period['id']}")
    assert stats.status_code==200
    assert b"'=HYPERLINK" in stats.content
    assert login(c,'worker1').status_code==200
    mine=c.get(f"/api/v1/me/exports/schedule.csv?period_id={period['id']}")
    assert mine.status_code==200 and mine.content.startswith(b'\xef\xbb\xbf')
    assert mine.content.count(b'2026-11-')==7
