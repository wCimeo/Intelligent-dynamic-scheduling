import secrets
from datetime import timedelta
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.config import Settings
from app.models import Base,User,AuthSession,Employee,ResetRequest,AuditEvent,IdempotencyRecord,now
from app.security import passwords,digest
from app.main import create_app

PASSWORD='test-password-12345'
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

def mutate(client,method,path,body=None,key=None):
    token=client.get('/api/v1/auth/csrf').json()['data']['token']
    headers={'Origin':'http://localhost:5174','X-CSRF-Token':token}
    if key: headers['Idempotency-Key']=key
    return client.request(method,'/api/v1'+path,json=body,headers=headers)

def post(client,path,body=None,key=None):
    return mutate(client,'POST',path,body,key or secrets.token_hex(16))

def login(client,name='manager',password=PASSWORD):
    return post(client,'/auth/login',{'username':name,'password':password})

def register(client):
    return post(client,'/auth/register',{'username':'worker','name':'小林','password':PASSWORD,'password_confirmation':PASSWORD})

def test_csrf_and_privilege_injection(fixture):
    c,_=fixture
    assert c.post('/api/v1/auth/login',json={'username':'manager','password':PASSWORD}).status_code==403
    result=post(c,'/auth/register',{'username':'hacker','name':'员工','password':PASSWORD,'password_confirmation':PASSWORD,'role':'MANAGER'})
    assert result.status_code==422
    assert c.get('/api/v1/employees').status_code==401

def test_register_review_idempotency_and_access(fixture):
    c,engine=fixture
    registered=register(c); assert registered.status_code==201
    uid=registered.json()['data']['user_id']
    assert register(c).status_code==409
    assert login(c,'worker').json()['data']['session_scope']=='ACCOUNT_STATUS'
    assert c.get('/api/v1/employees').status_code==403
    assert c.get('/api/v1/me/profile').status_code==403
    assert login(c).status_code==200
    body={'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'E001','name':'小林'}}
    key=secrets.token_hex(16)
    first=post(c,f'/admin/accounts/{uid}/review',body,key)
    assert first.status_code==200,first.text
    assert post(c,f'/admin/accounts/{uid}/review',body,key).json()['data']==first.json()['data']
    assert post(c,f'/admin/accounts/{uid}/review',body).status_code==409
    assert login(c,'worker').json()['data']['session_scope']=='BUSINESS'
    assert c.get('/api/v1/employees').status_code==403
    assert c.get('/api/v1/me/profile').json()['data']['employee_no']=='E001'
    with Session(engine) as db: assert len(db.scalars(select(Employee)).all())==1

def test_password_change_revokes_sessions(fixture):
    c,engine=fixture
    login(c)
    token=c.cookies.get('schedule_session')
    assert post(c,'/auth/change-password',{'old_password':PASSWORD,'new_password':'new-password-12345','confirmation':'new-password-12345'}).status_code==200
    c.cookies.set('schedule_session',token)
    assert c.get('/api/v1/auth/me').status_code==401
    assert login(c).status_code==401

def test_temporary_password_scope(fixture):
    c,engine=fixture
    with Session(engine) as db:
        user=db.scalar(select(User));user.must_change_password=True;db.commit()
    assert login(c).json()['data']['session_scope']=='PASSWORD_CHANGE'
    assert c.get('/api/v1/employees').status_code==403

def test_employee_conflict_and_reset_privacy(fixture):
    c,engine=fixture
    a=post(c,'/auth/password-reset-requests',{'username':'manager'})
    b=post(c,'/auth/password-reset-requests',{'username':'unknown'})
    assert a.json()['message']==b.json()['message']
    post(c,'/auth/password-reset-requests',{'username':'manager'})
    with Session(engine) as db: assert len(db.scalars(select(ResetRequest)).all())==1
    login(c)
    employee={'employee_no':'E002','name':'陈悦'}
    assert post(c,'/employees',employee).status_code==201
    assert post(c,'/employees',employee).status_code==409
    assert c.get('/api/v1/employees').json()['data']['total']==1

def test_no_password_disclosure(fixture):
    c,_=fixture
    login(c)
    data=c.get('/api/v1/admin/accounts').text
    assert PASSWORD not in data and 'password_hash' not in data
    assert post(c,'/auth/logout').status_code==200
    assert c.get('/api/v1/auth/me').status_code==401

def test_admin_reset_approval_is_one_time_and_revokes_sessions(fixture):
    c,engine=fixture
    registered=register(c)
    uid=registered.json()['data']['user_id']
    assert login(c).status_code==200
    reviewed=post(c,f'/admin/accounts/{uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'E010','name':'小林'}})
    assert reviewed.status_code==200,reviewed.text
    assert post(c,'/auth/password-reset-requests',{'username':'worker'}).status_code==200
    with Session(engine) as db:
        worker=db.scalar(select(User).where(User.username=='worker'))
        db.add(AuthSession(user_id=worker.id,token_hash=digest('known-worker-session'),scope='BUSINESS',expires_at=now()+timedelta(hours=1)))
        db.commit()
    listing=c.get('/api/v1/admin/password-reset-requests').json()['data']
    assert listing['total']==1
    item=listing['items'][0]
    assert item['username']=='worker' and item['status']=='PENDING'
    assert 'password' not in c.get('/api/v1/admin/password-reset-requests').text.lower()
    body={'request_id':int(item['id']),'expected_revision':item['account_revision'],'verification_note':'已在门店当面核对员工编号与姓名'}
    key=secrets.token_hex(16)
    first=post(c,f'/admin/accounts/{uid}/reset-password',body,key)
    assert first.status_code==200,first.text
    data=first.json()['data']
    temporary_password=data['temporary_password']
    assert len(temporary_password)>=12 and data['already_processed'] is False
    replay=post(c,f'/admin/accounts/{uid}/reset-password',body,key)
    assert replay.status_code==200
    assert replay.json()['data']['temporary_password'] is None
    assert replay.json()['data']['already_processed'] is True
    with Session(engine) as db:
        worker=db.scalar(select(User).where(User.username=='worker'))
        request=db.scalar(select(ResetRequest))
        assert worker.must_change_password is True
        assert worker.temporary_password_expires_at is not None
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash==digest('known-worker-session'))).revoked_at is not None
        assert request.status=='PROCESSED' and request.processed_by is not None and request.note
        assert db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key.like('%:reset-password:%'))) is not None
        assert db.scalar(select(AuditEvent).where(AuditEvent.action=='account.password_reset')) is not None
    assert login(c,'worker',temporary_password).json()['data']['session_scope']=='PASSWORD_CHANGE'
    assert post(c,'/auth/login',{'username':'worker','password':PASSWORD}).status_code==401

def test_reset_requires_manager_idempotency_and_current_revision(fixture):
    c,engine=fixture
    registered=register(c)
    uid=registered.json()['data']['user_id']
    logged=login(c)
    review=post(c,f'/admin/accounts/{uid}/review',{'decision':'APPROVE','expected_revision':1,'new_employee':{'employee_no':'E011','name':'小周'}})
    assert review.status_code==200
    with Session(engine) as db:
        old_hash=db.scalar(select(User.password_hash).where(User.id==int(uid)))
    token=c.get('/api/v1/auth/csrf').json()['data']['token']
    no_key=c.post(f'/api/v1/admin/accounts/{uid}/reset-password',json={'expected_revision':review.json()['data']['revision'],'verification_note':'现场核实'},headers={'Origin':'http://localhost:5174','X-CSRF-Token':token})
    assert no_key.status_code==422
    stale=post(c,f'/admin/accounts/{uid}/reset-password',{'expected_revision':1,'verification_note':'现场核实'})
    assert stale.status_code==409 and stale.json()['code']=='VERSION_CONFLICT'
    with Session(engine) as db:
        worker=db.scalar(select(User).where(User.username=='worker'))
        assert worker.must_change_password is False
        assert worker.password_hash==old_hash

def test_password_reset_list_requires_manager(fixture):
    c,_=fixture
    register(c)
    assert login(c,'worker').status_code==200
    response=c.get('/api/v1/admin/password-reset-requests')
    assert response.status_code==403

def test_manager_creates_account_with_one_time_password_and_employee_binding(fixture):
    c,engine=fixture
    assert login(c).status_code==200
    employee_created=post(c,'/employees',{'employee_no':'E020','name':'新的员工','employment_type':'FULL_TIME'})
    assert employee_created.status_code==201
    employee_id=employee_created.json()['data']['id']
    body={'username':'guided_worker','name':'新的员工','employee_id':int(employee_id)}
    key=secrets.token_hex(16)
    created=post(c,'/admin/accounts',body,key)
    assert created.status_code==201,created.text
    data=created.json()['data']
    temporary_password=data['temporary_password']
    assert data['status']=='ACTIVE' and data['role']=='EMPLOYEE' and temporary_password
    replay=post(c,'/admin/accounts',body,key)
    assert replay.status_code==201
    assert replay.json()['data']['temporary_password'] is None
    with Session(engine) as db:
        worker=db.scalar(select(User).where(User.username=='guided_worker'))
        employee=db.get(Employee,int(employee_id))
        assert worker.must_change_password is True
        assert employee.user_id==worker.id
        assert db.scalar(select(AuditEvent).where(AuditEvent.action=='account.created_by_manager')) is not None
        assert db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key.like('%:create-account:%'))) is not None
    assert login(c,'guided_worker',temporary_password).json()['data']['session_scope']=='PASSWORD_CHANGE'
    changed=post(c,'/auth/change-password',{'old_password':temporary_password,'new_password':'guided-password-12345','confirmation':'guided-password-12345'})
    assert changed.status_code==200
    assert login(c,'guided_worker','guided-password-12345').json()['data']['session_scope']=='BUSINESS'
    assert c.get('/api/v1/me/profile').json()['data']['employee_no']=='E020'

def test_account_status_change_revokes_sessions_and_protects_last_manager(fixture):
    c,engine=fixture
    assert login(c).status_code==200
    last_admin=mutate(c,'PATCH','/admin/accounts/1/status',{'status':'DISABLED','expected_revision':1})
    assert last_admin.status_code==409 and last_admin.json()['code']=='LAST_MANAGER'
    with Session(engine) as db:
        second=User(username='manager2',display_name='第二管理员',password_hash=passwords.hash(PASSWORD),role='MANAGER',status='ACTIVE')
        db.add(second); db.flush()
        db.add(AuthSession(user_id=second.id,token_hash=digest('second-manager-session'),scope='BUSINESS',expires_at=now()+timedelta(hours=1)))
        second_id=second.id
        db.commit()
    disabled=mutate(c,'PATCH',f'/admin/accounts/{second_id}/status',{'status':'DISABLED','expected_revision':1})
    assert disabled.status_code==200,disabled.text
    assert disabled.json()['data']['status']=='DISABLED' and disabled.json()['data']['revision']==2
    with Session(engine) as db:
        second=db.get(User,second_id)
        assert second.status=='DISABLED'
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash==digest('second-manager-session'))).revoked_at is not None
    stale=mutate(c,'PATCH',f'/admin/accounts/{second_id}/status',{'status':'ACTIVE','expected_revision':1})
    assert stale.status_code==409 and stale.json()['code']=='VERSION_CONFLICT'
    enabled=mutate(c,'PATCH',f'/admin/accounts/{second_id}/status',{'status':'ACTIVE','expected_revision':2})
    assert enabled.status_code==200
    assert enabled.json()['data']['status']=='ACTIVE' and enabled.json()['data']['revision']==3
    filtered=c.get('/api/v1/admin/accounts?status=ACTIVE').json()['data']
    assert filtered['total']==2

def test_pending_account_cannot_be_status_changed(fixture):
    c,_=fixture
    registered=register(c)
    uid=registered.json()['data']['user_id']
    assert login(c).status_code==200
    result=mutate(c,'PATCH',f'/admin/accounts/{uid}/status',{'status':'ACTIVE','expected_revision':1})
    assert result.status_code==409 and result.json()['code']=='ACCOUNT_STATE_CONFLICT'
