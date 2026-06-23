"""
LitKG Assistant — ChromaDB 向量存储模块
MVP-1: 集成 ChromaDB，实现论文 chunk 的向量化存储和相似度检索。

功能:
1. 为每个论文 chunk 生成 embedding 并存储到 ChromaDB
2. 支持相似度检索，返回最相关的 top-k 个 chunk
3. chunk 包含论文来源信息（标题、章节），用于回答中的引用
"""

import logging
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings
from core.models import TextChunk, PaperMeta

logger = logging.getLogger(__name__)

# ChromaDB 集合名称
COLLECTION_NAME = "litkg_chunks"


def _get_embedding_function():
    """获取 embedding 函数（支持多种后端）"""
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT,
        )

        def embed(texts: List[str]) -> List[List[float]]:
            """使用 OpenAI 兼容 API 生成 embedding"""
            response = client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=texts,
            )
            return [item.embedding for item in response.data]

        return embed
    except Exception as e:
        logger.error(f"初始化 embedding 函数失败: {e}")
        raise


class VectorStore:
    """ChromaDB 向量存储封装"""

    def __init__(self, persist_directory: Optional[str] = None):
        """
        初始化向量存储。

        参数:
            persist_directory: ChromaDB 持久化目录，默认为 data/vector_db
        """
        self.persist_directory = (
            Path(persist_directory)
            if persist_directory
            else settings.vector_db_dir_abs_path
        )
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None
        self._embedding_function = None

    def _init_chromadb(self):
        """延迟初始化 ChromaDB"""
        if self._client is not None:
            return

        try:
            import chromadb

            self._client = chromadb.PersistentClient(
                path=str(self.persist_directory),
            )
            logger.info(f"ChromaDB 初始化成功: {self.persist_directory}")
        except ImportError:
            logger.error(
                "ChromaDB 未安装，请运行: pip install chromadb"
            )
            raise

    def _init_embedding(self):
        """延迟初始化 embedding 函数"""
        if self._embedding_function is not None:
            return

        try:
            self._embedding_function = _get_embedding_function()
            logger.info(f"Embedding 模型初始化成功: {settings.EMBEDDING_MODEL}")
        except Exception as e:
            logger.error(f"Embedding 模型初始化失败: {e}")
            raise

    def _get_collection(self):
        """获取或创建 ChromaDB 集合"""
        self._init_chromadb()

        try:
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},  # 使用余弦相似度
            )
            return self._collection
        except Exception as e:
            logger.error(f"获取 ChromaDB 集合失败: {e}")
            raise

    def add_chunks(self, chunks: List[TextChunk], paper_meta: PaperMeta) -> int:
        """
        将论文 chunks 添加到向量存储。

        参数:
            chunks: 论文文本分块列表
            paper_meta: 论文元数据（用于添加来源信息）

        返回:
            成功添加的 chunk 数量
        """
        if not chunks:
            logger.warning("无 chunks 输入，跳过向量存储")
            return 0

        self._init_embedding()
        collection = self._get_collection()

        # 准备批量添加的数据
        ids = []
        documents = []
        metadatas = []
        embeddings = []

        for chunk in chunks:
            # 生成唯一 ID（基于 chunk_id 或内容哈希）
            chunk_id = chunk.chunk_id or self._hash_content(chunk.content)
            ids.append(chunk_id)

            # 文档内容
            documents.append(chunk.content)

            # 元数据（包含论文来源信息）
            paper_title = paper_meta.title or chunk.paper_id or "Untitled"
            metadata = {
                "paper_id": chunk.paper_id,
                "paper_title": paper_title,
                "page_num": chunk.page_num,
                "section_title": chunk.section_title or "",
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
            }
            metadatas.append(metadata)

        # 批量生成 embedding
        try:
            logger.info(f"正在为 {len(documents)} 个 chunk 生成 embedding...")
            embedding_list = self._embedding_function(documents)
            embeddings.extend(embedding_list)
        except Exception as e:
            logger.error(f"生成 embedding 失败: {e}")
            raise

        # 批量添加到 ChromaDB
        try:
            collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            logger.info(
                f"成功添加 {len(ids)} 个 chunk 到向量存储"
            )
            return len(ids)
        except Exception as e:
            logger.error(f"添加到 ChromaDB 失败: {e}")
            raise

    def search(
        self, query: str, k: int = 3, filter_metadata: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        相似度检索。

        参数:
            query: 查询文本
            k: 返回最相似的 k 个结果
            filter_metadata: 可选的元数据过滤条件（如 {"paper_id": "xxx"}）

        返回:
            检索结果列表，每个结果包含:
            - id: chunk ID
            - text: chunk 文本
            - metadata: 元数据（论文标题、章节等）
            - distance: 距离（越小越相似）
        """
        self._init_embedding()
        collection = self._get_collection()

        # 生成查询 embedding
        try:
            query_embedding = self._embedding_function([query])[0]
        except Exception as e:
            logger.error(f"生成查询 embedding 失败: {e}")
            raise

        # 执行检索
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=filter_metadata,
            )

            # 格式化结果
            formatted_results = []
            if results and results.get("ids"):
                for i in range(len(results["ids"][0])):
                    formatted_results.append(
                        {
                            "id": results["ids"][0][i],
                            "text": results["documents"][0][i],
                            "metadata": results["metadatas"][0][i],
                            "distance": (
                                results["distances"][0][i]
                                if results.get("distances")
                                else None
                            ),
                        }
                    )

            logger.info(
                f"向量检索成功: query='{query[:50]}...', "
                f"返回 {len(formatted_results)} 个结果"
            )
            return formatted_results
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            raise

    def delete_by_paper_id(self, paper_id: str) -> int:
        """
        删除指定论文的所有 chunks。

        参数:
            paper_id: 论文 ID

        返回:
            删除的 chunk 数量
        """
        collection = self._get_collection()

        try:
            # 查询要删除的 chunks
            results = collection.get(where={"paper_id": paper_id})
            if not results or not results.get("ids"):
                logger.info(f"未找到 paper_id={paper_id} 的 chunks")
                return 0

            # 删除
            collection.delete(ids=results["ids"])
            logger.info(
                f"成功删除 paper_id={paper_id} 的 {len(results['ids'])} 个 chunks"
            )
            return len(results["ids"])
        except Exception as e:
            logger.error(f"删除 chunks 失败: {e}")
            raise

    def get_stats(self) -> Dict[str, Any]:
        """获取向量存储统计信息"""
        collection = self._get_collection()

        try:
            count = collection.count()
            return {
                "total_chunks": count,
                "collection_name": COLLECTION_NAME,
                "persist_directory": str(self.persist_directory),
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {"error": str(e)}

    @staticmethod
    def _hash_content(content: str) -> str:
        """计算内容哈希值作为 ID"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()


def get_vector_store() -> VectorStore:
    """获取全局向量存储实例（单例模式）"""
    if not hasattr(get_vector_store, "_instance"):
        get_vector_store._instance = VectorStore()
    return get_vector_store._instance
