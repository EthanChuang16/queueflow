from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    celery_concurrency: int = 4
    secret_key: str
    debug: bool = False


settings = Settings()