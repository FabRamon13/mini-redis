from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    redis_host: str = "127.0.0.1"
    redis_port: int = 31337
    cache_ttl: int = 30
    app_name: str = "FastAPI Cache Demo"
    max_queue_size: int = 100
    demo_db_delay_seconds: float = 0.0
