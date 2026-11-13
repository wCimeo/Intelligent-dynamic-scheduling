from alembic import context
from sqlalchemy import create_engine
from app.config import Settings
from app.models import Base
settings=Settings()
if context.is_offline_mode():
    context.configure(url=settings.url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction(): context.run_migrations()
else:
    if not settings.db_password.get_secret_value():
        raise RuntimeError('请先在项目根目录 .env 填写数据库密码')
    engine=create_engine(settings.url)
    with engine.connect() as connection:
        context.configure(connection=connection,target_metadata=Base.metadata)
        with context.begin_transaction(): context.run_migrations()
