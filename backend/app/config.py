from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    db_host: str = 'localhost'
    db_port: int = 3306
    db_name: str = 'intelligent_dynamic_scheduling'
    db_user: str = 'root'
    db_password: SecretStr = SecretStr('')
    csrf_secret: SecretStr = SecretStr('')
    cookie_secure: bool = False
    allowed_origins: str = 'http://localhost:5174,http://127.0.0.1:5174'
    deepseek_api_key: SecretStr = SecretStr('')
    deepseek_base_url: str = 'https://api.deepseek.com'
    deepseek_model: str = 'deepseek-chat'
    ai_daily_user_limit: int = 30
    ai_daily_global_limit: int = 300
    ai_max_output_tokens: int = 800
    ai_explanation_max_output_tokens: int = 1600
    ai_timeout_seconds: int = 20
    ai_max_input_chars: int = 2000

    @property
    def url(self):
        return URL.create('mysql+pymysql', username=self.db_user,
            password=self.db_password.get_secret_value(), host=self.db_host,
            port=self.db_port, database=self.db_name, query={'charset':'utf8mb4'})
