"""
LitKG Assistant — 共享数据模型（Pydantic v2）
所有核心模块共用这些数据结构。
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ============================================================
# 工具函数
# ============================================================

def gen_id() -> str:
    """生成 12 位短 UUID"""
    return uuid4().hex[:12]


def compute_hash(content: str) -> str:
    """计算文本内容的 SHA256 哈希"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ============================================================
# 实体类型与关系类型
# ============================================================

# MVP-2 扩展实体类型（10 种）
EntityType = Literal[
    "Paper", "Author", "Institution",
    "Method", "Task", "Dataset",
    "Model", "Metric", "Result", "Domain"
]

# MVP-2 标准化关系类型
RelationType = Literal[
    "PROPOSES",        # Paper/Author -> Method/Model
    "USES",            # Method/Model -> Dataset/Method
    "EVALUATED_ON",    # Method/Model -> Dataset
    "OUTPERFORMS",     # Method/Model -> Method/Model
    "ACHIEVES",        # Method/Model -> Result
    "BELONGS_TO",      # Author -> Institution / Method -> Domain
    "EXTENDS",         # Method/Model -> Method/Model
    "COMPARED_WITH",   # Method -> Method
    "EVALUATED_BY",    # Method -> Metric
    "AUTHORED_BY",     # Paper -> Author
]

# 关系类型归一化映射（LLM 可能返回带后缀的变体，如 proposes_method → PROPOSES）
_RELATION_NORMALIZE_MAP: Dict[str, str] = {
    "PROPOSES_METHOD": "PROPOSES",
    "PROPOSES_MODEL": "PROPOSES",
    "PROPOSES_APPROACH": "PROPOSES",
    "PROPOSES_FRAMEWORK": "PROPOSES",
    "USES_DATASET": "USES",
    "USES_METHOD": "USES",
    "USES_MODEL": "USES",
    "EVALUATED_ON_DATASET": "EVALUATED_ON",
    "EVALUATED_ON_BENCHMARK": "EVALUATED_ON",
    "OUTPERFORMS_MODEL": "OUTPERFORMS",
    "OUTPERFORMS_METHOD": "OUTPERFORMS",
    "OUTPERFORMS_BASELINE": "OUTPERFORMS",
    "ACHIEVES_RESULT": "ACHIEVES",
    "ACHIEVES_PERFORMANCE": "ACHIEVES",
    "BELONGS_TO_INSTITUTION": "BELONGS_TO",
    "BELONGS_TO_DOMAIN": "BELONGS_TO",
    "EXTENDS_METHOD": "EXTENDS",
    "EXTENDS_MODEL": "EXTENDS",
    "COMPARED_WITH_METHOD": "COMPARED_WITH",
    "COMPARED_WITH_MODEL": "COMPARED_WITH",
    "EVALUATED_BY_METRIC": "EVALUATED_BY",
    "AUTHORED_BY_AUTHOR": "AUTHORED_BY",
}


def normalize_relation_type(raw: str) -> str:
    """
    将 LLM 输出的关系类型字符串归一化为标准 RelationType 枚举值。

    处理逻辑：
    1. strip + upper
    2. 直接匹配映射表（处理 PROPOSES_METHOD → PROPOSES）
    3. 如果不在映射表但去掉 _后缀 后匹配，则使用基类
    4. 否则返回原值（让 Pydantic 报错，以便调试）

    示例:
        "proposes_method" → "PROPOSES"
        "USES_DATASET"    → "USES"
        "OUTPERFORMS"     → "OUTPERFORMS"
        "outperforms_baseline" → "OUTPERFORMS"
    """
    if not raw:
        return ""
    upper = raw.strip().upper()

    # 1) 直接映射匹配
    if upper in _RELATION_NORMALIZE_MAP:
        return _RELATION_NORMALIZE_MAP[upper]

    # 2) 检查是否直接是标准值
    _VALID = {"PROPOSES", "USES", "EVALUATED_ON", "OUTPERFORMS", "ACHIEVES",
              "BELONGS_TO", "EXTENDS", "COMPARED_WITH", "EVALUATED_BY", "AUTHORED_BY"}
    if upper in _VALID:
        return upper

    # 3) 尝试去掉后缀（取第一个 _ 前的部分）
    base = upper.split("_")[0] if "_" in upper else upper
    if base in _VALID:
        return base

    # 4) 模糊匹配：检查是否包含标准键
    for key in sorted(_VALID, key=len, reverse=True):
        if key in upper:
            return key

    # 5) 无法归一化，返回原值（让 Pydantic 报详细错误）
    return upper


# Chunk 抽取状态
ExtractionStatus = Literal["pending", "success", "partial", "failed"]


# ============================================================
# PDF 解析相关模型
# ============================================================

@dataclass
class TextBlock:
    """PDF 页面上的一个文本块（原始位置信息）"""
    text: str
    x0: float          # 左边距
    y0: float          # 顶部坐标
    x1: float          # 右边距
    y1: float          # 底部坐标
    block_no: int = 0  # 块序号
    page_num: int = 1  # 所在页码


@dataclass
class Section:
    """论文的一个章节"""
    heading: str = ""      # 章节标题，如 "3. Method"
    content: str = ""      # 章节正文
    page_start: int = 0
    page_end: int = 0


class PaperMeta(BaseModel):
    """论文解析后的元信息"""
    paper_id: str = Field(default_factory=gen_id)
    title: str = ""
    authors_text: str = ""    # 作者全文字符串
    abstract: str = ""
    full_text: str = ""       # 全文（去页眉页脚和参考文献后）
    references_raw: str = ""  # 参考文献原文
    total_pages: int = 0
    sections: List[Any] = Field(default_factory=list)  # List[Section]
    # 注意: sections 为 Section dataclass 列表，类型标注设为 Any 以避免循环引用


class TextChunk(BaseModel):
    """论文文本分块"""
    chunk_id: str = Field(default_factory=gen_id)
    paper_id: str
    content: str                           # 文本内容（500~1000 字符）
    chunk_hash: str = ""                   # content 的 SHA256 哈希
    page_num: int = 0                      # 所在页码（从 1 开始）
    char_start: int = 0                    # 在全文字符中的起始位置
    char_end: int = 0                      # 在全文字符中的结束位置
    section_title: str = ""                # 所属章节标题（尽量识别）
    extraction_status: ExtractionStatus = "pending"  # 抽取处理状态
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 知识图谱相关模型
# ============================================================

class Entity(BaseModel):
    """知识图谱中的实体"""
    entity_id: str = Field(default_factory=gen_id)
    entity_type: EntityType
    name: str
    description: str = ""  # 实体语义描述（GraphRAG/LightRAG 核心：让节点可理解、问答有语义）
    properties: Dict[str, Any] = Field(default_factory=dict)  # 如 year, venue, abstract
    source_paper_id: str = ""
    source_chunk_ids: List[str] = Field(default_factory=list)
    source_section: str = ""  # 实体来源的论文章节（如 "第3章 方法"）
    community_id: int = -1    # 所属社区 ID（社区发现后填充，默认未分配）


class Triple(BaseModel):
    """知识图谱中的关系三元组"""
    triple_id: str = Field(default_factory=gen_id)
    relation_type: RelationType
    source_entity_id: str       # 头实体
    target_entity_id: str       # 尾实体
    source_entity_name: str = ""  # 头实体名称（便于展示）
    target_entity_name: str = ""  # 尾实体名称（便于展示）
    description: str = ""       # 关系语义描述（如 "A 提出方法 B，用于解决 X"）
    source_paper_id: str = ""
    source_chunk_ids: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    llm_model: str = ""
    prompt_version: str = "v0"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AliasEntry(BaseModel):
    """
    实体别名表条目（MVP-2 实体消歧，说明书 3.5）。

    记录「别名文本 → 标准实体」的映射，用于 L2 级消歧，
    同时保留合并来源与置信度，便于追溯审计。
    """
    alias_id: str = Field(default_factory=gen_id)
    alias_text: str                      # 别名文本（如 "BERT_base"）
    canonical_entity_id: str             # 指向标准实体 ID
    entity_type: EntityType              # 实体类型（与 canonical 一致）
    source: Literal["llm_extraction", "manual_review", "embedding_match"]
    confidence: float = 1.0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PendingReview(BaseModel):
    """
    待人工审核的消歧候选（说明书 6.7 待审核队列）。

    同名异义、或相似度处于灰区（未达自动合并阈值）的实体对，
    不自动合并，入队等待人工在 UI 上决定合并或新建。
    """
    review_id: str = Field(default_factory=gen_id)
    new_entity_id: str = ""
    new_entity_name: str = ""
    new_entity_type: str = ""
    candidate_entity_id: str = ""
    candidate_entity_name: str = ""
    similarity: float = 0.0              # 语义相似度
    reason: str = ""                     # 入队原因
    status: Literal["pending", "merged", "rejected"] = "pending"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ============================================================
# LLM 抽取相关模型
# ============================================================

class ExtractionResult(BaseModel):
    """LLM 抽取的完整结果"""
    paper_id: str
    entities: List[Entity] = Field(default_factory=list)
    triples: List[Triple] = Field(default_factory=list)
    failed_chunk_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)  # model, prompt_version, latency


# ============================================================
# GraphRAG 问答相关模型
# ============================================================

class SourceInfo(BaseModel):
    """回答中的来源引用"""
    source_type: str            # "entity" | "triple"
    entity_name: str = ""
    relation_description: str = ""
    paper_title: str = ""


class Citation(BaseModel):
    """回答中的单个引用"""
    paper_title: str = ""
    page_num: int = 0
    chunk_text: str = ""
    relevance: str = ""  # "direct" | "related" | "background"

class Answer(BaseModel):
    """GraphRAG 问答输出"""
    question: str
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    comparison_table: List[Dict[str, Any]] = Field(default_factory=list)
    question_type: str = "general"  # "factual" | "comparison" | "statistical" | "graph"
    source_entities: List[Entity] = Field(default_factory=list)
    source_triples: List[Triple] = Field(default_factory=list)
    latency_ms: float = 0.0
    hits_entities: int = 0
    hits_relations: int = 0
    hits_chunks: int = 0
