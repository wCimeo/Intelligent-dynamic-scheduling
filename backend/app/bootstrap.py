"""Explicit local initialization. No automatic schema changes during app startup."""
import argparse, getpass
from datetime import timedelta
from sqlalchemy import create_engine, select, text, URL
from sqlalchemy.orm import Session
from .config import Settings
from .models import User, Employee, AuthSession, now
from .security import passwords

def main():
    parser=argparse.ArgumentParser(description='项目数据库与账号初始化')
    parser.add_argument('action',choices=['create-db','admin','admin-local','demo','reset-password'])
    args=parser.parse_args()
    settings=Settings()
    if not settings.db_password.get_secret_value(): raise SystemExit('请先填写根目录 .env 的 DB_PASSWORD')
    if settings.db_name!='intelligent_dynamic_scheduling': raise SystemExit('初始化仅允许操作约定的项目数据库')
    if args.action=='create-db':
        engine=create_engine(URL.create('mysql+pymysql', username=settings.db_user, password=settings.db_password.get_secret_value(), host=settings.db_host, port=settings.db_port, query={'charset':'utf8mb4'}))
        with engine.begin() as conn:
            conn.execute(text('CREATE DATABASE IF NOT EXISTS intelligent_dynamic_scheduling CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci'))
        print('项目数据库已就绪，下一步执行 alembic upgrade head。'); return
    engine=create_engine(settings.url)
    with Session(engine) as session:
        if args.action=='admin-local':
            # Random local bootstrap credential, never printed or shipped as a default.
            import secrets
            from dotenv import set_key
            from .config import ROOT
            if session.scalar(select(User).where(User.role=='MANAGER')):
                print('管理员已存在，不覆盖其凭据。'); return
            if session.scalar(select(User).where(User.username=='admin')):
                raise SystemExit('admin 名称已被使用，请通过交互命令选择其他账号。')
            password=secrets.token_urlsafe(24)
            set_key(str(ROOT/'.env'),'INITIAL_ADMIN_USERNAME','admin')
            set_key(str(ROOT/'.env'),'INITIAL_ADMIN_PASSWORD',password)
            session.add(User(username='admin',display_name='门店管理员',role='MANAGER',status='ACTIVE',
                password_hash=passwords.hash(password),must_change_password=True,
                temporary_password_expires_at=now()+timedelta(hours=24)))
            session.commit()
            print('管理员已初始化。临时密码仅保存在本机 .env 的 INITIAL_ADMIN_PASSWORD；首次登录需修改。'); return
        if args.action=='demo':
            for i,name in enumerate(['林晓','陈悦','周宁','许晨','苏禾'],1):
                number=f'DEMO{i:03}'
                if not session.scalar(select(Employee).where(Employee.employee_no==number)):
                    session.add(Employee(employee_no=number,name=name))
            session.commit(); print('已添加明确标记为 DEMO 的未绑定员工档案；没有创建默认密码账号。'); return
        username=input('账号（字母/数字/下划线，4—32位）：').strip().lower()
        import re
        if not re.fullmatch(r'[a-z0-9_]{4,32}',username): raise SystemExit('账号格式不正确')
        user=session.scalar(select(User).where(User.username==username))
        if args.action=='admin' and user: raise SystemExit('账号已存在，不会覆盖')
        if args.action=='reset-password' and not user: raise SystemExit('账号不存在')
        password=getpass.getpass('临时密码（12—128字符，输入不回显）：')
        if password!=getpass.getpass('再次输入：') or not 12<=len(password)<=128: raise SystemExit('密码长度或确认不正确')
        if not user:
            user=User(username=username,display_name='门店管理员',role='MANAGER',status='ACTIVE'); session.add(user)
        user.password_hash=passwords.hash(password); user.must_change_password=True
        user.temporary_password_expires_at=now()+timedelta(hours=24)
        if user.id:
            from sqlalchemy import update
            session.execute(update(AuthSession).where(AuthSession.user_id==user.id).values(revoked_at=now()))
            user.row_version+=1
        session.commit(); print('已保存。首次登录必须修改密码，临时密码24小时有效。')

if __name__=='__main__': main()
