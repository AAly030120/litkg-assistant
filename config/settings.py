"""
LitKG Assistant — 全局配置管理

配置读取优先级：
  1. Streamlit Cloud Secrets（st.secrets）  ← 生产环境
  2. .env 文件                               ← 本地开发
  3. 代码默认值                               ← 兜底
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录（litkg-assistant/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env 文件（本地开发用，st.secrets 优先级更高）
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get_secret(key: str, default: str = "") -> str:
    """尝试从 st.secrets 读取，失败则回退到 .env / 默认值"""
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val is not None:
            return str(val)
    except Exception:
        pass
    return os.getenv(key, default)


class Settings:
    """
    全局配置单例。
    使用方式：from config.settings import settings
    敏感配置（LLM_API_KEY 等）在 Streamlit Cloud 上通过 Secrets 注入。
    """

    # ========== LLM API（优先 st.secrets）==========
    LLM_BASE_URL: str = _get_secret("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_API_KEY: str = _get_secret("LLM_API_KEY", "")
    LLM_MODEL_NAME: str = _get_secret("LLM_MODEL_NAME", "gpt-4o-mini")
    LLM_EXTRACT_TEMPERATURE: float = float(_get_secret("LLM_EXTRACT_TEMPERATURE", "0.1"))
    LLM_QA_TEMPERATURE: float = float(_get_secret("LLM_QA_TEMPERATURE", "0.3"))
    LLM_TIMEOUT: int = int(_get_secret("LLM_TIMEOUT", "120"))
    LLM_MAX_RETRIES: int = int(_get_secret("LLM_MAX_RETRIES", "3"))
    LLM_MAX_CONCURRENCY: int = int(_get_secret("LLM_MAX_CONCURRENCY", "3"))

    # ========== 文件路径 ==========
    KG_JSON_PATH: str = os.getenv("KG_JSON_PATH", "data/kg.json")
    PAPERS_INDEX_PATH: str = os.getenv("PAPERS_INDEX_PATH", "data/papers_index.json")
    PAPERS_DIR: str = os.getenv("PAPERS_DIR", "data/papers")
    CHUNKS_DIR: str = os.getenv("CHUNKS_DIR", "data/chunks")

    # ========== PDF 解析 ==========
    CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "800"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "100"))
    HEADER_RATIO: float = float(os.getenv("HEADER_RATIO", "0.12"))
    FOOTER_RATIO: float = float(os.getenv("FOOTER_RATIO", "0.88"))

    # ========== 日志 ==========
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "litkg.log")

    # ========== Prompt 版本 ==========
    PROMPT_VERSION: str = "v0"  # MVP-0 专用

    # ========== Embedding 模型（MVP-1 ChromaDB）==========
    EMBEDDING_MODEL: str = os.getenv(
        "EMBEDDING_MODEL", "text-embedding-ada-002"
    )  # OpenAI 兼容的 embedding 模型
    EMBEDDING_DIM: int = int(os.getenv("EMBEDDING_DIM", "1536"))  # embedding 维度

    # ========== 向量检索（MVP-1 ChromaDB）==========
    VECTOR_DB_DIR: str = os.getenv("VECTOR_DB_DIR", "data/vector_db")
    TOP_K_CHUNKS: int = int(os.getenv("TOP_K_CHUNKS", "3"))  # 向量检索返回 top-k 个 chunk

    # ========== GraphRAG 融合检索（MVP-1）==========
    HYBRID_RETRIEVAL: bool = os.getenv("HYBRID_RETRIEVAL", "true").lower() == "true"
    KG_HOPS: int = int(os.getenv("KG_HOPS", "2"))  # KG 检索跳数
    VECTOR_WEIGHT: float = float(os.getenv("VECTOR_WEIGHT", "0.5"))  # 向量检索权重（0~1）

    @property
    def kg_json_abs_path(self) -> Path:
        """KG JSON 的绝对路径"""
        return PROJECT_ROOT / self.KG_JSON_PATH

    @property
    def papers_dir_abs_path(self) -> Path:
        """论文存储目录的绝对路径"""
        return PROJECT_ROOT / self.PAPERS_DIR

    @property
    def chunks_dir_abs_path(self) -> Path:
        """Chunk 缓存目录的绝对路径"""
        return PROJECT_ROOT / self.CHUNKS_DIR

    @property
    def prompts_dir_abs_path(self) -> Path:
        """Prompt 模板目录的绝对路径"""
        return PROJECT_ROOT / "core" / "prompts"

    @property
    def data_dir_abs_path(self) -> Path:
        """数据目录的绝对路径"""
        return PROJECT_ROOT / "data"

    @property
    def vector_db_dir_abs_path(self) -> Path:
        """向量数据库目录的绝对路径"""
        return PROJECT_ROOT / self.VECTOR_DB_DIR

    def validate(self) -> list[str]:
        """
        启动时的配置校验。
        返回所有校验失败的错误信息列表，空列表表示一切正常。
        """
        errors = []
        if not self.LLM_API_KEY or self.LLM_API_KEY == "sk-your-api-key-here":
            errors.append(
                "LLM_API_KEY 未配置或为默认值。请编辑 .env 文件填入真实 API Key。"
            )
        if not self.LLM_BASE_URL:
            errors.append("LLM_BASE_URL 未配置。")
        return errors


# 全局单例
settings = Settings()
