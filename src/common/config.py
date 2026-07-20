from pydantic_settings import BaseSettings, SettingsConfigDict


class WindsorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WINDSOR_", env_file=".env", extra="ignore")
    api_key: str
    base_url: str = "https://connectors.windsor.ai"
    requests_per_minute: int = 30
    timeout_seconds: int = 60
    lookback_days: int = 7
