from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Micro-Knowledge Atlas API"
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/mka", alias="DATABASE_URL")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_llm_model: str = Field(default="gpt-4o-mini", alias="OPENAI_LLM_MODEL")
    openai_embed_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBED_MODEL")

    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")
    cluster_similarity_threshold: float = Field(default=0.78, alias="CLUSTER_SIMILARITY_THRESHOLD")
    edge_similarity_threshold: float = Field(default=0.72, alias="EDGE_SIMILARITY_THRESHOLD")
    fallback_similarity_floor: float = Field(default=0.33, alias="FALLBACK_SIMILARITY_FLOOR")
    cluster_ema_alpha: float = Field(default=0.25, alias="CLUSTER_EMA_ALPHA")
    max_edges_per_node: int = Field(default=12, alias="MAX_EDGES_PER_NODE")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:5174", alias="CORS_ORIGINS")


settings = Settings()
