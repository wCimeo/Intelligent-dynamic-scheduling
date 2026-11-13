import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.ai_service import AIProviderError
from app.config import Settings
from app.main import create_app
from app.models import AIExplanationRecord,AuditEvent,Base,User
from app.security import passwords
from test_accounts import PASSWORD,login,post
from test_f10 import published_swap_context
from test_f11 import create_gap


class FakeExplanationProvider:
    model='fake-deepseek'
    def __init__(self,error=None):
        self.error=error
        self.calls=[]
    def explain(self,question,facts):
        self.calls.append((question,facts))
        if self.error:
            raise self.error
        return {
            'title':'班表安排事实说明',
            'conclusion':'当前安排依据已发布班表和规则事实生成。',
            'reasons':['当前版本满足岗位覆盖，并按规则优化偏好与公平性。'],
            'evidence':['解释只使用本次提供的事实数据。'],
            'limitations':['候选方案不因此证明为全局最优。'],
        },{'prompt_tokens':180,'completion_tokens':80,'total_tokens':260}


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


def test_manager_explains_current_published_schedule():
    provider=FakeExplanationProvider()
    engine,app=make_fixture(provider)
    try:
        with TestClient(app) as c:
            period,current,employee_a,employee_b,_=published_swap_context(c)
            assert login(c).status_code==200
            response=post(c,'/ai/schedule-explanations',{'period_id':int(period['id']),
                'question':'本周排班主要依据哪些事实？'})
            assert response.status_code==201,response.text
            data=response.json()['data']
            assert data['status']=='COMPLETED' and data['scope']=='PUBLISHED_SCHEDULE'
            assert data['facts']['data_scope']=='MANAGER_FULL_STORE'
            assert data['facts']['version']['id']==current['id']
            assert data['output']['title']=='班表安排事实说明'
            assert provider.calls and provider.calls[0][1]['summary']['shift_count']>0
            with Session(engine) as db:
                assert db.scalar(select(AIExplanationRecord)).status=='COMPLETED'
                assert db.scalar(select(AuditEvent).where(AuditEvent.action=='ai.schedule_explained')) is not None
    finally:
        engine.dispose()


def test_employee_explanation_is_filtered_to_self_and_cannot_read_candidate():
    provider=FakeExplanationProvider()
    engine,app=make_fixture(provider)
    try:
        with TestClient(app) as c:
            period,current,employee_a,employee_b,_=published_swap_context(c)
            assert login(c,'worker1').status_code==200
            response=post(c,'/ai/schedule-explanations',{'period_id':int(period['id']),
                'question':'为什么给我安排这些班次？'})
            assert response.status_code==201,response.text
            data=response.json()['data']
            assert data['scope']=='PERSONAL_SCHEDULE'
            assert data['facts']['data_scope']=='EMPLOYEE_SELF_ONLY'
            assert data['facts']['employee']['employee_no']=='E601'
            assert data['facts']['summary']['employee_count']==1
            facts_text=json.dumps(data['facts'],ensure_ascii=False)
            assert employee_b['name'] not in facts_text
            forbidden=post(c,'/ai/schedule-explanations',{'period_id':int(period['id']),
                'candidate_id':1,'question':'解释一下这个管理端候选方案'})
            assert forbidden.status_code==403
            history=c.get('/api/v1/ai/schedule-explanations').json()['data']
            assert history['total']==1
            detail=c.get(f"/api/v1/ai/schedule-explanations/{data['id']}")
            assert detail.status_code==200 and detail.json()['data']['id']==data['id']
    finally:
        engine.dispose()


def test_manager_explains_adjustment_candidate_without_source_reason():
    provider=FakeExplanationProvider()
    engine,app=make_fixture(provider)
    try:
        with TestClient(app) as c:
            period,current,employee_a,employee_b,source,event,locked=create_gap(c)
            generated=post(c,'/adjustment-candidates/generate',{
                'event_ids':[int(event['id'])],'time_limit_seconds':10})
            assert generated.status_code==201,generated.text
            candidate=generated.json()['data']['candidates'][0]
            response=post(c,'/ai/schedule-explanations',{
                'period_id':int(period['id']),'candidate_id':int(candidate['id']),
                'question':'为什么这个调班方案改动了这些人？'})
            assert response.status_code==201,response.text
            data=response.json()['data']
            assert data['scope']=='ADJUSTMENT_CANDIDATE'
            assert data['facts']['candidate']['id']==candidate['id']
            assert data['facts']['constraints']['optimality_proven'] is False
            facts_text=json.dumps(data['facts'],ensure_ascii=False)
            assert '临时课程冲突' not in facts_text
    finally:
        engine.dispose()


def test_explanation_falls_back_to_fixed_facts_and_consumes_limit():
    provider=FakeExplanationProvider(AIProviderError('AI_UNAVAILABLE','模型服务连接超时'))
    engine,app=make_fixture(provider,user_limit=1)
    try:
        with TestClient(app) as c:
            period,current,employee_a,employee_b,_=published_swap_context(c)
            assert login(c).status_code==200
            response=post(c,'/ai/schedule-explanations',{'period_id':int(period['id']),
                'question':'本周缺口和确认进度如何？'})
            assert response.status_code==201,response.text
            data=response.json()['data']
            assert data['status']=='FALLBACK'
            assert data['output']['title']=='当前发布班表事实摘要'
            assert data['fallback_reason']=='模型服务连接超时'
            limited=post(c,'/ai/schedule-explanations',{'period_id':int(period['id']),
                'question':'再解释一次本周排班'})
            assert limited.status_code==429
            assert limited.json()['code']=='AI_USER_LIMIT'
    finally:
        engine.dispose()
