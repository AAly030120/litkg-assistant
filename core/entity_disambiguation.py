"""
LitKG Assistant — 实体消歧模块（MVP-2 · 说明书 2.1 / 3.5 / 6.7）

解决的问题：
    同一概念在不同论文中写法各异（"BERT-base" / "bert_base" / "BERT base"），
    需归并到同一标准实体；而同名异义（"Transformer" 模型架构 vs 方法名）
    不能误合并。

三级消歧流程（说明书 6.7）：
    L1 精确名称匹配 → 大小写/空格归一化后完全相等，直接合并
    L2 别名表查询   → aliases.json 命中且类型一致，合并
    L3 语义相似度   → embedding 余弦相似度 > 0.92 且类型一致，自动合并并写入别名表
    灰区           → 相似度 0.75~0.92（疑似同名异义）不合并，入 pending_review.json 待人工审核

设计取舍：
    embedding 复用项目已有的 OpenAI 兼容接口（settings.EMBEDDING_MODEL），
    不引入 sentence-transformers —— 后者需下载数百 MB 模型，
    在 Streamlit Cloud 免费版 1GB 内存下容易 OOM 且首次启动极慢。
"""

import difflib
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import settings
from core.models import AliasEntry, Entity, PendingReview

logger = logging.getLogger("litkg.disambiguation")

# ============ 阈值常量（说明书 6.7）============
AUTO_MERGE_THRESHOLD = 0.92   # 语义相似度 ≥ 此值且类型一致 → 自动合并
REVIEW_LOWER_BOUND = 0.75     # 低于此值视为不相关；介于两者之间 → 待审核队列
ROUGH_CHAR_THRESHOLD = 0.40   # 字符粗筛阈值：低于此值不值得调用 embedding
MAX_EMBED_CANDIDATES = 20     # 单次最多比较的候选数，控制 API 成本


class EntityDisambiguator:
    """实体消歧器：三级匹配 + 别名表 + 待审核队列"""

    def __init__(
        self,
        aliases_path: Optional[Path] = None,
        pending_path: Optional[Path] = None,
    ):
        self.aliases_path = Path(
            aliases_path or settings.data_dir_abs_path / "aliases.json"
        )
        self.pending_path = Path(
            pending_path or settings.data_dir_abs_path / "pending_review.json"
        )
        self.aliases: List[AliasEntry] = self._load_aliases()
        self.pending: List[PendingReview] = self._load_pending()
        self._embed_fn = None
        self._emb_cache: Dict[str, List[float]] = {}  # 名称 → 向量（避免重复调用）

    # ============================================================
    # 持久化
    # ============================================================

    def _load_aliases(self) -> List[AliasEntry]:
        """加载别名表，文件不存在或损坏时返回空列表"""
        if not self.aliases_path.exists():
            return []
        try:
            data = json.loads(self.aliases_path.read_text(encoding="utf-8"))
            return [AliasEntry(**item) for item in data.get("aliases", [])]
        except Exception as e:
            logger.warning(f"别名表读取失败，按空表处理: {e}")
            return []

    def _load_pending(self) -> List[PendingReview]:
        """加载待审核队列"""
        if not self.pending_path.exists():
            return []
        try:
            data = json.loads(self.pending_path.read_text(encoding="utf-8"))
            return [PendingReview(**item) for item in data.get("pending", [])]
        except Exception as e:
            logger.warning(f"待审核队列读取失败，按空队列处理: {e}")
            return []

    def save_aliases(self) -> None:
        """落盘别名表"""
        try:
            self.aliases_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"aliases": [a.model_dump() for a in self.aliases]}
            self.aliases_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"别名表保存失败: {e}")

    def save_pending(self) -> None:
        """落盘待审核队列"""
        try:
            self.pending_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"pending": [p.model_dump() for p in self.pending]}
            self.pending_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"待审核队列保存失败: {e}")

    def save(self) -> None:
        """同时落盘别名表与待审核队列"""
        self.save_aliases()
        self.save_pending()

    # ============================================================
    # 三级消歧主入口
    # ============================================================

    def resolve(
        self, new_entity: Entity, existing_entities: List[Entity]
    ) -> Tuple[Optional[str], str]:
        """
        对新实体执行三级消歧。

        参数:
            new_entity: 待入库的新实体
            existing_entities: 图谱中已有的同类候选实体

        返回:
            (canonical_entity_id, decision)
            canonical_entity_id 为 None 表示应新建实体
            decision ∈ {"exact", "alias", "embedding", "review", "new"}
                exact     - L1 精确名称匹配
                alias     - L2 别名表命中
                embedding - L3 语义相似度自动合并
                review    - 灰区，已入待人工审核队列
                new       - 无匹配，新建实体
        """
        # --- L1: 精确名称匹配（大小写 + 空格归一化）---
        hit = self._l1_exact(new_entity, existing_entities)
        if hit:
            logger.debug(f"[消歧 L1] 「{new_entity.name}」精确匹配已有实体")
            return hit.entity_id, "exact"

        # --- L2: 别名表查询 ---
        alias_id = self._l2_alias(new_entity)
        if alias_id:
            logger.debug(f"[消歧 L2] 「{new_entity.name}」命中别名表 → {alias_id}")
            return alias_id, "alias"

        # --- L3: 语义相似度 ---
        cand_id, sim = self._l3_embedding(new_entity, existing_entities)
        if cand_id and sim >= AUTO_MERGE_THRESHOLD:
            # 自动合并，并把该写法登记为别名，便于下次 L2 直接命中
            self.add_alias(
                alias_text=new_entity.name,
                canonical_id=cand_id,
                entity_type=new_entity.entity_type,
                source="embedding_match",
                confidence=round(sim, 4),
            )
            logger.info(
                f"[消歧 L3] 「{new_entity.name}」语义合并 (sim={sim:.3f})"
            )
            return cand_id, "embedding"

        # --- 灰区：疑似同名异义，不合并，入待审核队列 ---
        if cand_id and REVIEW_LOWER_BOUND <= sim < AUTO_MERGE_THRESHOLD:
            candidate = next(
                (e for e in existing_entities if e.entity_id == cand_id), None
            )
            self.add_pending_review(
                new_entity=new_entity,
                candidate=candidate,
                similarity=sim,
                reason=(
                    f"语义相似度 {sim:.3f} 处于灰区 "
                    f"[{REVIEW_LOWER_BOUND}, {AUTO_MERGE_THRESHOLD})，"
                    "疑似同名异义，需人工确认是否合并"
                ),
            )
            logger.info(
                f"[消歧 灰区] 「{new_entity.name}」sim={sim:.3f}，"
                f"已入待审核队列，暂不合并"
            )
            return None, "review"

        return None, "new"

    def _l1_exact(
        self, new_entity: Entity, existing_entities: List[Entity]
    ) -> Optional[Entity]:
        """L1：名称归一化后完全相等，且实体类型一致"""
        target = self._normalize(new_entity.name)
        for e in existing_entities:
            if e.entity_type != new_entity.entity_type:
                continue
            if self._normalize(e.name) == target:
                return e
        return None

    def _l2_alias(self, new_entity: Entity) -> Optional[str]:
        """L2：查询别名表，别名文本 + 类型均匹配才返回标准实体 ID"""
        target = self._normalize(new_entity.name)
        for entry in self.aliases:
            if entry.entity_type != new_entity.entity_type:
                continue
            if self._normalize(entry.alias_text) == target:
                return entry.canonical_entity_id
        return None

    def _l3_embedding(
        self, new_entity: Entity, existing_entities: List[Entity]
    ) -> Tuple[Optional[str], float]:
        """
        L3：语义相似度匹配。

        为控制 API 成本，先用字符相似度做本地粗筛，
        仅对通过粗筛的候选（上限 MAX_EMBED_CANDIDATES）计算 embedding。
        """
        same_type = [
            e for e in existing_entities if e.entity_type == new_entity.entity_type
        ]
        if not same_type:
            return None, 0.0

        # 字符粗筛：过滤掉字面差异极大的候选
        rough = [
            e
            for e in same_type
            if self._char_similarity(new_entity.name, e.name) >= ROUGH_CHAR_THRESHOLD
        ]
        if not rough:
            return None, 0.0

        rough = rough[:MAX_EMBED_CANDIDATES]

        # 批量编码：新实体 + 候选（一次 API 调用）
        texts = [new_entity.name] + [e.name for e in rough]
        try:
            vectors = self._embed_batch(texts)
        except Exception as e:
            logger.warning(f"embedding 消歧不可用，跳过 L3: {e}")
            return None, 0.0

        if not vectors or len(vectors) != len(texts):
            return None, 0.0

        new_vec = vectors[0]
        best_id, best_sim = None, 0.0
        for e, vec in zip(rough, vectors[1:]):
            if not vec:
                continue
            sim = self._cosine(new_vec, vec)
            if sim > best_sim:
                best_sim, best_id = sim, e.entity_id

        return best_id, best_sim

    # ============================================================
    # Embedding 工具
    # ============================================================

    def _get_embed_fn(self):
        """延迟初始化 embedding 函数（复用向量库同款 OpenAI 兼容接口）"""
        if self._embed_fn is None:
            from core.vector_store import _get_embedding_function

            self._embed_fn = _get_embedding_function()
        return self._embed_fn

    def _embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        批量生成 embedding，带内存缓存。

        返回与 texts 等长的向量列表；单项失败时对应位置为 None。
        """
        results: List[Optional[List[float]]] = [None] * len(texts)
        todo_idx = [i for i, t in enumerate(texts) if t and t not in self._emb_cache]
        todo_texts = [texts[i] for i in todo_idx]

        # 命中缓存的直接回填
        for i, t in enumerate(texts):
            if t in self._emb_cache:
                results[i] = self._emb_cache[t]

        if not todo_texts:
            return results

        try:
            fn = self._get_embed_fn()
            vectors = fn(todo_texts)
            for idx, vec in zip(todo_idx, vectors):
                results[idx] = vec
                self._emb_cache[texts[idx]] = vec
        except Exception as e:
            logger.warning(f"批量 embedding 失败: {e}")
            raise

        return results

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        """余弦相似度（纯 Python 实现，避免 numpy 依赖）"""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (na * nb)

    # ============================================================
    # 字符串工具
    # ============================================================

    @staticmethod
    def _normalize(name: str) -> str:
        """名称归一化：小写 + 去除所有空白"""
        return "".join((name or "").lower().split())

    @staticmethod
    def _char_similarity(s1: str, s2: str) -> float:
        """
        字符级相似度（本地快速粗筛用）。

        注意：此处刻意不使用「子串包含即高分」的激进规则
        （如 kg_store._similarity 对子串直接给 0.95），
        否则 "Attention" 会被误判为等同 "Self-Attention"。
        """
        a, b = EntityDisambiguator._normalize(s1), EntityDisambiguator._normalize(s2)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        return difflib.SequenceMatcher(None, a, b).ratio()

    # ============================================================
    # 别名表 / 待审核队列维护
    # ============================================================

    def add_alias(
        self,
        alias_text: str,
        canonical_id: str,
        entity_type: str,
        source: str = "embedding_match",
        confidence: float = 1.0,
    ) -> AliasEntry:
        """登记一条别名映射（自动合并后调用，便于下次 L2 直接命中）"""
        # 去重：同别名 + 同目标不重复登记
        for entry in self.aliases:
            if (
                self._normalize(entry.alias_text) == self._normalize(alias_text)
                and entry.canonical_entity_id == canonical_id
            ):
                return entry

        entry = AliasEntry(
            alias_text=alias_text,
            canonical_entity_id=canonical_id,
            entity_type=entity_type,
            source=source,
            confidence=confidence,
        )
        self.aliases.append(entry)
        self.save_aliases()
        return entry

    def add_pending_review(
        self,
        new_entity: Entity,
        candidate: Optional[Entity],
        similarity: float,
        reason: str = "",
    ) -> PendingReview:
        """将不确定的实体对加入待人工审核队列"""
        item = PendingReview(
            new_entity_id=new_entity.entity_id,
            new_entity_name=new_entity.name,
            new_entity_type=new_entity.entity_type,
            candidate_entity_id=candidate.entity_id if candidate else "",
            candidate_entity_name=candidate.name if candidate else "",
            similarity=round(similarity, 4),
            reason=reason,
        )
        self.pending.append(item)
        self.save_pending()
        return item

    def get_pending(self, status: str = "pending") -> List[PendingReview]:
        """获取待审核项（默认只返回未处理的）"""
        return [p for p in self.pending if p.status == status]

    def resolve_review(self, review_id: str, merge: bool) -> bool:
        """
        人工审核裁决。

        参数:
            review_id: 待审核项 ID
            merge: True 合并到候选实体，False 驳回（保持独立）
        返回:
            是否成功处理
        """
        item = next((p for p in self.pending if p.review_id == review_id), None)
        if not item:
            return False

        if merge and item.candidate_entity_id:
            self.add_alias(
                alias_text=item.new_entity_name,
                canonical_id=item.candidate_entity_id,
                entity_type=item.new_entity_type,
                source="manual_review",
                confidence=item.similarity,
            )
            item.status = "merged"
        else:
            item.status = "rejected"

        self.save_pending()
        return True

    def get_stats(self) -> Dict[str, int]:
        """消歧模块统计信息"""
        return {
            "aliases": len(self.aliases),
            "pending": len(self.get_pending()),
            "merged": len([p for p in self.pending if p.status == "merged"]),
            "rejected": len([p for p in self.pending if p.status == "rejected"]),
        }


# ============================================================
# 单例
# ============================================================

_disambiguator_instance: Optional[EntityDisambiguator] = None


def get_disambiguator() -> EntityDisambiguator:
    """获取全局实体消歧器实例（单例）"""
    global _disambiguator_instance
    if _disambiguator_instance is None:
        _disambiguator_instance = EntityDisambiguator()
    return _disambiguator_instance
