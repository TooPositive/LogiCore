from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Provider toggles (Phase 6 -- air-gapped mode)
    llm_provider: str = "azure"  # azure | ollama
    embedding_provider: str = "azure_openai"  # azure_openai | ollama | mock

    # Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_deployment: str = "gpt-4o"

    # Ollama (local inference)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"  # generation model
    ollama_embed_model: str = "nomic-embed-text"  # embedding model

    # PostgreSQL
    postgres_user: str = "logicore"
    postgres_password: str = "changeme"
    postgres_db: str = "logicore"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3001"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
