import copy
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login,register


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


def positions(c):
    barista=post(c,'/positions',{'code':'barista','name':'咖啡师'}).json()['data']
    cashier=post(c,'/positions',{'code':'cashier','name':'收银'}).json()['data']
    return barista,cashier


def template_body(barista,cashier):
    return {'code':'morning','name':'早班','start_time':'08:00','end_time':'14:00','demands':[{'position_id':int(barista['id']),'required_count':2},{'position_id':int(cashier['id']),'required_count':1}]}


def test_shift_template_validation_and_period_creation(fixture):
    c,_=fixture
    assert login(c).status_code==200
    barista,cashier=positions(c)
    invalid_time=post(c,'/shift-templates',{'code':'bad','name':'错误班次','start_time':'14:00','end_time':'08:00','demands':[{'position_id':int(barista['id']),'required_count':1}]})
    assert invalid_time.status_code==422
    duplicate_position=post(c,'/shift-templates',{'code':'dup','name':'重复岗位','start_time':'08:00','end_time':'12:00','demands':[{'position_id':int(barista['id']),'required_count':1},{'position_id':int(barista['id']),'required_count':2}]})
    assert duplicate_position.status_code==422
    template=post(c,'/shift-templates',template_body(barista,cashier))
    assert template.status_code==201,template.text
    assert template.json()['data']['demands'][0]['required_count'] in {1,2}
    period=post(c,'/periods',{'week_start':'2026-11-09'})
    assert period.status_code==201,period.text
    assert period.json()['data']['week_end']=='2026-11-15'
    assert post(c,'/periods',{'week_start':'2026-11-09'}).status_code==409
    assert post(c,'/periods',{'week_start':'2026-11-10'}).status_code==422


def test_draft_generation_overrides_metrics_and_cross_week_copy(fixture):
    c,_=fixture
    assert login(c).status_code==200
    barista,cashier=positions(c)
    template=post(c,'/shift-templates',template_body(barista,cashier)).json()['data']
    period=post(c,'/periods',{'week_start':'2026-11-09'}).json()['data']
    draft=post(c,f"/periods/{period['id']}/drafts",{})
    assert draft.status_code==201,draft.text
    version=draft.json()['data']
    assert version['version_no']==1 and len(version['shifts'])==7
    assert version['metrics']=={'enabled_shifts':7,'total_positions':21,'required_minutes':7560,'required_hours':126.0}
    assert {shift['work_date'] for shift in version['shifts']}=={'2026-11-09','2026-11-10','2026-11-11','2026-11-12','2026-11-13','2026-11-14','2026-11-15'}
    template_update={'code':template['code'],'name':'早班新版','start_time':'09:00','end_time':'15:00','active':True,'expected_revision':template['revision'],'demands':[{'position_id':int(barista['id']),'required_count':4},{'position_id':int(cashier['id']),'required_count':0}]}
    assert mutate(c,'PATCH',f"/shift-templates/{template['id']}",template_update).status_code==200
    unchanged_response=c.get(f"/api/v1/versions/{version['id']}")
    assert unchanged_response.status_code==200,unchanged_response.text
    unchanged=unchanged_response.json()['data']
    assert {shift['name'] for shift in unchanged['shifts']}=={'早班'}
    assert unchanged['metrics']['total_positions']==21
    shifts=[{
        'shift_key':shift['shift_key'],'template_id':int(shift['template_id']) if shift['template_id'] else None,
        'work_date':shift['work_date'],'name':shift['name'],'start_time':shift['start_time'],'end_time':shift['end_time'],
        'enabled':shift['enabled'],
        'demands':[{'position_id':int(demand['position_id']),'required_count':demand['required_count']} for demand in shift['demands']]
    } for shift in copy.deepcopy(unchanged['shifts'])]
    shifts[0]['enabled']=False
    cashier_demand=next(item for item in shifts[1]['demands'] if item['position_id']==int(cashier['id']))
    cashier_demand['required_count']=3
    payload={'expected_revision':unchanged['revision'],'shifts':shifts}
    updated=mutate(c,'PUT',f"/versions/{version['id']}/shifts",payload)
    assert updated.status_code==200,updated.text
    assert updated.json()['data']['metrics']=={'enabled_shifts':6,'total_positions':20,'required_minutes':7200,'required_hours':120.0}
    stale=mutate(c,'PUT',f"/versions/{version['id']}/shifts",payload)
    assert stale.status_code==409 and stale.json()['code']=='VERSION_CONFLICT'
    next_period=post(c,'/periods',{'week_start':'2026-11-16'}).json()['data']
    copied=post(c,f"/periods/{next_period['id']}/drafts",{'source_period_id':int(period['id'])})
    assert copied.status_code==201,copied.text
    copied_data=copied.json()['data']
    assert min(shift['work_date'] for shift in copied_data['shifts'])=='2026-11-16'
    assert copied_data['metrics']==updated.json()['data']['metrics']
    detail=c.get(f"/api/v1/periods/{next_period['id']}").json()['data']
    assert detail['latest_draft']['id']==copied_data['id']


def test_f3_permissions_versions_and_empty_sources(fixture):
    c,_=fixture
    registered=register(c)
    uid=registered.json()['data']['user_id']
    assert login(c).status_code==200
    assert post(c,f'/admin/accounts/{uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'E300','name':'排班员工'}}).status_code==200
    period=post(c,'/periods',{'week_start':'2026-11-23'}).json()['data']
    empty=post(c,f"/periods/{period['id']}/drafts",{})
    assert empty.status_code==409 and empty.json()['code']=='TEMPLATES_REQUIRED'
    assert login(c,'worker').status_code==200
    assert c.get('/api/v1/shift-templates').status_code==403
    assert mutate(c,'POST','/periods',{'week_start':'2026-11-30'}).status_code==403
