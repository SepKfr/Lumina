from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Micro-Knowledge Atlas API"
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/mka", alias="DATABASE_URL")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_llm_model: str = Field(default="gpt-4o-mini", alias="OPENAI_LLM_MODEL")
    openai_embed_model: str = Field(default="text-embedding-3-large", alias="OPENAI_EMBED_MODEL")

    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")
    cluster_similarity_threshold: float = Field(default=0.78, alias="CLUSTER_SIMILARITY_THRESHOLD")
    edge_similarity_threshold: float = Field(default=0.72, alias="EDGE_SIMILARITY_THRESHOLD")
    edge_similarity_fallback: float = Field(default=0.52, alias="EDGE_SIMILARITY_FALLBACK")
    fallback_similarity_floor: float = Field(default=0.33, alias="FALLBACK_SIMILARITY_FLOOR")
    cluster_ema_alpha: float = Field(default=0.25, alias="CLUSTER_EMA_ALPHA")
    max_edges_per_node: int = Field(default=12, alias="MAX_EDGES_PER_NODE")
    topic_similarity_threshold: float = Field(default=0.62, alias="TOPIC_SIMILARITY_THRESHOLD")
    subtopic_similarity_threshold: float = Field(default=0.70, alias="SUBTOPIC_SIMILARITY_THRESHOLD")
    topic_neighbor_top_k: int = Field(default=8, alias="TOPIC_NEIGHBOR_TOP_K")
    stance_confidence_margin: float = Field(default=0.04, alias="STANCE_CONFIDENCE_MARGIN")
    opposing_alpha: float = Field(default=0.65, alias="OPPOSING_ALPHA")
    retrieval_candidate_pool: int = Field(default=600, alias="RETRIEVAL_CANDIDATE_POOL")
    recluster_min_points: int = Field(default=24, alias="RECLUSTER_MIN_POINTS")
    recluster_entropy_threshold: float = Field(default=1.05, alias="RECLUSTER_ENTROPY_THRESHOLD")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:5174", alias="CORS_ORIGINS")


settings = Settings()
