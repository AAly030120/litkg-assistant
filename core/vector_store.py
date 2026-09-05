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
from typing import Any, Dict, List, Optional, Set

from config.settings import settings
from core.models import TextChunk, PaperMeta, compute_hash

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

        for idx, chunk in enumerate(chunks):
            # 稳定 ID（说明书 3.4: "paper_id::chunk_index"），保证重复写入幂等
            chunk_id = chunk.chunk_id or f"{chunk.paper_id}::{idx}"
            ids.append(chunk_id)

            # 文档内容
            documents.append(chunk.content)

            # 元数据（补全 chunk_hash / extraction_status，支撑增量去重与失败重试）
            paper_title = paper_meta.title or chunk.paper_id or "Untitled"
            chunk_hash = chunk.chunk_hash or compute_hash(chunk.content)
            metadata = {
                "paper_id": chunk.paper_id,
                "title": paper_title,            # 说明书 3.4 字段名
                "paper_title": paper_title,      # 向后兼容：graphrag 检索读此字段
                "page_num": chunk.page_num,
                "section_title": chunk.section_title or "",
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "chunk_hash": chunk_hash,                       # 增量去重依据（任务 2.2）
                "extraction_status": chunk.extraction_status,   # 失败重试面板（任务 2.3）
                "chunk_index": idx,
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

        # 批量写入 ChromaDB（upsert 幂等：同 ID 覆盖更新，重复上传不产生重复记录）
        try:
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            logger.info(
                f"成功写入 {len(ids)} 个 chunk 到向量存储（upsert 幂等）"
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

    def get_existing_chunk_hashes(self, paper_id: str) -> Set[str]:
        """
        获取某论文已入库的 chunk_hash 集合（供增量去重判断，任务 2.2）。

        重复上传同一论文时，内容未变的 chunk 其 SHA256 不变，
        据此可跳过 LLM 抽取，直接复用已有结果。
        """
        collection = self._get_collection()
        try:
            results = collection.get(where={"paper_id": paper_id})
            if not results or not results.get("metadatas"):
                return set()
            return {
                m.get("chunk_hash")
                for m in results["metadatas"]
                if m and m.get("chunk_hash")
            }
        except Exception as e:
            logger.warning(f"读取已有 chunk_hash 失败（按无存量处理）: {e}")
            return set()

    def get_chunks_by_paper(self, paper_id: str) -> List[Dict[str, Any]]:
        """
        获取某论文全部 chunk 及抽取状态（供失败重试面板展示，任务 2.3）。

        返回字段: chunk_id / content / preview / page_num / section_title /
                  extraction_status / chunk_hash / metadata
        """
        collection = self._get_collection()
        try:
            results = collection.get(where={"paper_id": paper_id})
            if not results or not results.get("ids"):
                return []
            chunks = []
            for i, cid in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                doc = results["documents"][i] if results.get("documents") else ""
                meta = meta or {}
                chunks.append(
                    {
                        "chunk_id": cid,
                        "content": doc or "",
                        "preview": (doc or "").strip().replace("\n", " ")[:120],
                        "page_num": meta.get("page_num", 0),
                        "section_title": meta.get("section_title", ""),
                        "extraction_status": meta.get("extraction_status", "pending"),
                        "chunk_hash": meta.get("chunk_hash", ""),
                        "metadata": meta,
                    }
                )
            # 按 chunk_index 排序，保证展示顺序与原文一致
            chunks.sort(key=lambda c: c["metadata"].get("chunk_index", 0))
            return chunks
        except Exception as e:
            logger.error(f"获取论文 chunks 失败: {e}")
            return []

    def update_chunk_status(self, chunk_ids: List[str], status: str) -> int:
        """
        批量更新 chunk 的抽取状态（重试成功后调用，任务 2.3）。

        参数:
            chunk_ids: 待更新的 chunk ID 列表
            status: 目标状态 success / partial / failed / pending
        返回:
            成功更新的数量
        """
        if not chunk_ids:
            return 0
        collection = self._get_collection()
        try:
            results = collection.get(
                ids=chunk_ids,
                include=["embeddings", "documents", "metadatas"],
            )
            if not results or not results.get("ids"):
                return 0

            keep_ids, keep_docs, keep_metas, keep_embeds = [], [], [], []
            for i, cid in enumerate(results["ids"]):
                emb = results["embeddings"][i] if results.get("embeddings") else None
                if emb is None:
                    logger.warning(f"chunk {cid} 缺少 embedding，跳过状态更新")
                    continue
                meta = dict(results["metadatas"][i] or {})
                meta["extraction_status"] = status
                keep_ids.append(cid)
                keep_docs.append(results["documents"][i])
                keep_metas.append(meta)
                keep_embeds.append(emb)

            if not keep_ids:
                return 0

            collection.upsert(
                ids=keep_ids,
                documents=keep_docs,
                metadatas=keep_metas,
                embeddings=keep_embeds,
            )
            logger.info(f"更新 {len(keep_ids)} 个 chunk 状态为 {status}")
            return len(keep_ids)
        except Exception as e:
            logger.error(f"更新 chunk 状态失败: {e}")
            return 0

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
