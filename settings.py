from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
OPENAI_API_KEY = settings.openai_api_key
