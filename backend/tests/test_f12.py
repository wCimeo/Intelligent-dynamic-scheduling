import pytest
from datetime import date,timedelta
from sqlalchemy import create_engine,select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import AIParseRecord,AuditEvent,AvailabilityOverride,Base,PreferenceSubmission,User
from app.security import passwords
from app.main import create_app
from test_accounts import PASSWORD,post,mutate,login
from test_f6 import setup_inputs,future_week_start


class FakeProvider:
    model='fake-deepseek'
    def __init__(self,output=None,error=None):
        self.output=output
        self.error=error
        self.calls=[]
    def parse(self,text,context):
        self.calls.append((text,context))
        if self.error: raise self.error
        return self.output,{'prompt_tokens':120,'completion_tokens':40,'total_tokens':160}


def make_fixture(provider,user_limit=30):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    settings=Settings(_env_file=None,csrf_secret='test-only-secret-12345678901234567890',
        ai_daily_user_limit=user_limit,ai_daily_global_limit=100,ai_max_input_chars=2000)
    with Session(engine) as db:
        db.add(User(username='manager',display_name='管理员',password_hash=passwords.hash(PASSWORD),role='MANAGER',status='ACTIVE'))
        db.commit()
    app=create_app(settings,engine,provider)
    return engine,app


def parsed_output(week_start):
    request_date=(date.fromisoformat(week_start)+timedelta(days=2)).isoformat()
    preference_date=(date.fromisoformat(week_start)+timedelta(days=5)).isoformat()
    return {'summary':'周三中午不可用，周六希望早班','overrides':[{'date':request_date,'mode':'BLOCK',
        'windows':[{'start_time':'12:00','end_time':'13:00'}],'needs_confirmation':False,'note':'课程'}],
        'preferences':[{'date':preference_date,'template_code':'morning','kind':'PREFER',
            'weight':5,'needs_confirmation':False,'note':''}],'clarifications':[]}


def test_ai_parse_confirm_writes_availability_and_preference():
    week_start=future_week_start().isoformat()
    request_date=(date.fromisoformat(week_start)+timedelta(days=2)).isoformat()
    preference_date=(date.fromisoformat(week_start)+timedelta(days=5)).isoformat()
    provider=FakeProvider(parsed_output(week_start))
    engine,app=make_fixture(provider)
    try:
        with TestClient(app) as c:
            _,period,_=setup_inputs(c,2,week_start=week_start)
            assert login(c,'worker1').status_code==200
            parsed=post(c,'/me/ai/availability/parse',{'text':'周三中午有课不能上班，周六希望早班'})
            assert parsed.status_code==201,parsed.text
            data=parsed.json()['data']
            assert data['status']=='PENDING_CONFIRMATION'
            assert data['usage']['total_tokens']==160
            assert data['preferences'][0]['template_id']
            confirm=post(c,f"/me/ai/availability/parses/{data['id']}/confirm",{'expected_revision':1,
                'overrides':[{'date':request_date,'mode':'BLOCK','windows':[{'start_time':'12:00','end_time':'13:00'}]}],
                'preferences':[{'date':preference_date,'template_id':int(data['preferences'][0]['template_id']),'kind':'PREFER','weight':5}]})
            assert confirm.status_code==200,confirm.text
            assert confirm.json()['data']['override_count']==1
            availability=c.get(f'/api/v1/me/availability?from={request_date}&to={request_date}').json()['data']['days'][0]
            assert availability['override_mode']=='BLOCK'
            preferences=c.get(f"/api/v1/me/preferences/{period['id']}").json()['data']
            assert preferences['status']=='DRAFT'
            assert any(item['kind']=='PREFER' and item['template_name']=='早班' for item in preferences['items'])
            with Session(engine) as db:
                assert db.scalar(select(AIParseRecord)).status=='CONFIRMED'
                assert db.scalar(select(AuditEvent).where(AuditEvent.action=='ai.availability_confirmed')) is not None
    finally:
        engine.dispose()


def test_ai_failure_fallback_and_daily_limit():
    from app.ai_service import AIProviderError
    week_start=future_week_start().isoformat()
    provider=FakeProvider(error=AIProviderError('AI_INVALID_RESPONSE','模型返回结构无法使用'))
    engine,app=make_fixture(provider,user_limit=1)
    try:
        with TestClient(app) as c:
            setup_inputs(c,2,week_start=week_start)
            assert login(c,'worker1').status_code==200
            failed=post(c,'/me/ai/availability/parse',{'text':'下周的时间不太方便'})
            assert failed.status_code==503
            assert failed.json()['code']=='AI_INVALID_RESPONSE'
            assert failed.json()['data']['fallback_url']=='/availability'
            second=post(c,'/me/ai/availability/parse',{'text':'周末希望早班'})
            assert second.status_code==429 and second.json()['code']=='AI_USER_LIMIT'
            with Session(engine) as db:
                record=db.scalar(select(AIParseRecord))
                assert record.status=='FAILED' and record.raw_text=='下周的时间不太方便'
    finally:
        engine.dispose()


def test_ai_parse_can_be_rejected():
    week_start=future_week_start().isoformat()
    provider=FakeProvider(parsed_output(week_start))
    engine,app=make_fixture(provider)
    try:
        with TestClient(app) as c:
            setup_inputs(c,2,week_start=week_start)
            assert login(c,'worker1').status_code==200
            data=post(c,'/me/ai/availability/parse',{'text':'周三中午有课，周六希望早班'}).json()['data']
            rejected=post(c,f"/me/ai/availability/parses/{data['id']}/reject",{'expected_revision':1})
            assert rejected.status_code==200 and rejected.json()['data']['status']=='REJECTED'
            detail=c.get(f"/api/v1/me/ai/availability/parses/{data['id']}")
            assert detail.status_code==200,detail.text
            assert detail.json()['data']['status']=='REJECTED'
    finally:
        engine.dispose()


def test_ai_confirmation_rejects_duplicate_or_out_of_range_edits():
    week_start=future_week_start().isoformat()
    request_date=(date.fromisoformat(week_start)+timedelta(days=2)).isoformat()
    provider=FakeProvider(parsed_output(week_start))
    engine,app=make_fixture(provider)
    try:
        with TestClient(app) as c:
            setup_inputs(c,2,week_start=week_start)
            assert login(c,'worker1').status_code==200
            data=post(c,'/me/ai/availability/parse',{'text':'周三中午有课，周六希望早班'}).json()['data']
            duplicate=post(c,f"/me/ai/availability/parses/{data['id']}/confirm",{
                'expected_revision':1,
                'overrides':[
                    {'date':request_date,'mode':'BLOCK','windows':[{'start_time':'12:00','end_time':'13:00'}]},
                    {'date':request_date,'mode':'BLOCK','windows':[{'start_time':'14:00','end_time':'15:00'}]},
                ],
                'preferences':[],
            })
            assert duplicate.status_code==422
            past=post(c,f"/me/ai/availability/parses/{data['id']}/confirm",{
                'expected_revision':1,
                'overrides':[{'date':'2020-01-01','mode':'REPLACE','windows':[]}],
                'preferences':[],
            })
            assert past.status_code==422
            assert past.json()['code']=='VALIDATION_FAILED'
            assert c.get(f"/api/v1/me/ai/availability/parses/{data['id']}").json()['data']['status']=='PENDING_CONFIRMATION'
    finally:
        engine.dispose()


def test_invalid_ai_business_output_consumes_daily_limit():
    week_start=future_week_start().isoformat()
    output=parsed_output(week_start)
    output['overrides'][0]['date']='2020-01-01'
    provider=FakeProvider(output)
    engine,app=make_fixture(provider,user_limit=1)
    try:
        with TestClient(app) as c:
            setup_inputs(c,2,week_start=week_start)
            assert login(c,'worker1').status_code==200
            invalid=post(c,'/me/ai/availability/parse',{'text':'过去某天不能上班'})
            assert invalid.status_code==422
            assert invalid.json()['code']=='AI_INVALID_RESPONSE'
            limited=post(c,'/me/ai/availability/parse',{'text':'周六希望早班'})
            assert limited.status_code==429
            assert limited.json()['code']=='AI_USER_LIMIT'
            with Session(engine) as db:
                record=db.scalar(select(AIParseRecord))
                assert record.status=='FAILED'
                assert record.error_code=='AI_INVALID_RESPONSE'
    finally:
        engine.dispose()
