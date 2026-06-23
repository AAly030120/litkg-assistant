"""
LitKG Assistant — LLM 实体与关系抽取模块
MVP-0: 仅抽取 3 种实体 + 2 种关系
支持三级重试、Pydantic 校验、tenacity 指数退避。
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings
from core.models import (
    Entity,
    ExtractionResult,
    TextChunk,
    Triple,
    normalize_relation_type,
)

logger = logging.getLogger(__name__)


# ============================================================
# LLM 抽取的原始 JSON Schema（用于 Pydantic 校验）
# ============================================================



class _PaperItem(BaseModel):
    title: str
    title_zh: str = ""
    year: Any = None
    venue: str = ""
    abstract: str = ""


class _AuthorItem(BaseModel):
    name: str
    name_zh: str = ""
    affiliation: str = ""


class _MethodItem(BaseModel):
    name: str
    name_zh: str = ""
    description: str = ""


class _ModelItem(BaseModel):
    name: str
    name_zh: str = ""
    param_count: Any = None


class _DatasetItem(BaseModel):
    name: str
    name_zh: str = ""
    size: Any = None
    domain: str = ""


class _TaskItem(BaseModel):
    name: str
    name_zh: str = ""
    description: str = ""


class _MetricItem(BaseModel):
    name: str
    name_zh: str = ""
    description: str = ""


class _ResultItem(BaseModel):
    method: str = ""
    dataset: str = ""
    metric: str = ""
    value: str = ""


class _RelationItem(BaseModel):
    type: str  # PROPOSES | USES | EVALUATED_ON | OUTPERFORMS | ACHIEVES | BELONGS_TO | EXTENDS | COMPARED_WITH | EVALUATED_BY | AUTHORED_BY
    source: str
    target: str


class _ExtractOutput(BaseModel):
    """LLM 输出的 JSON 结构校验（扩展版）"""
    paper: _PaperItem
    authors: List[_AuthorItem] = Field(default_factory=list)
    methods: List[_MethodItem] = Field(default_factory=list)
    models: List[_ModelItem] = Field(default_factory=list)
    datasets: List[_DatasetItem] = Field(default_factory=list)
    tasks: List[_TaskItem] = Field(default_factory=list)
    metrics: List[_MetricItem] = Field(default_factory=list)
    results: List[_ResultItem] = Field(default_factory=list)
    relations: List[_RelationItem] = Field(default_factory=list)


# ============================================================
# Prompt 加载
# ============================================================

def _load_prompt(filename: str) -> str:
    """从 core/prompts/ 目录加载 Prompt 模板"""
    prompt_path = settings.prompts_dir_abs_path / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


# ============================================================
# LLM 客户端
# ============================================================

def _get_client() -> OpenAI:
    """获取 OpenAI 兼容客户端"""
    return OpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        timeout=settings.LLM_TIMEOUT,
    )


# ============================================================
# LLM 调用（含 tenacity 重试）
# ============================================================

@retry(
    retry=retry_if_exception_type((Exception,)),
    stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _call_llm(
    messages: List[Dict[str, str]],
    temperature: float = None,
    force_json: bool = False,  # 默认关闭，很多兼容 API 不支持 json_object
) -> str:
    """
    调用 LLM API，带自动重试。
    处理 429 (Rate Limit) 和超时错误。

    参数:
        force_json: 是否启用 response_format json_object（默认 False）
    """
    client = _get_client()
    temp = temperature if temperature is not None else settings.LLM_EXTRACT_TEMPERATURE

    kwargs: Dict[str, Any] = {
        "model": settings.LLM_MODEL_NAME,
        "messages": messages,
        "temperature": temp,
    }
    if force_json:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content
    return content.strip() if content else ""


# ============================================================
# JSON 提取与清理
# ============================================================

def _extract_json(text: str) -> Optional[str]:
    """
    从 LLM 返回文本中提取 JSON 部分。
    处理 LLM 偶尔输出的 markdown code fences 或多余文字。
    """
    if not text:
        return None

    # 预处理：移除 BOM、零宽字符
    text = text.lstrip("\ufeff\u200b\u200c\u200d\u200e\u200f")

    # 尝试提取 ```json ... ``` 中的内容
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        return m.group(1).strip()

    # 尝试匹配第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start < end:
        json_str = text[start:end + 1]
        return json_str

    return None


def _clean_json(json_str: str) -> str:
    """
    对 LLM 产出 JSON 做常见修复：
    - 移除尾部逗号
    - 将中文引号替换为英文引号
    """
    # 移除 JSON 中可能的尾部逗号（在 } 或 ] 前）
    json_str = re.sub(r",\s*(\}|\])", r"\1", json_str)
    # 中文引号 → 英文
    json_str = json_str.replace("\u201c", '"').replace("\u201d", '"')
    json_str = json_str.replace("\u2018", "'").replace("\u2019", "'")
    return json_str


# ============================================================
# 三级重试：原 Prompt → 纠错 Prompt → 逐实体降级
# ============================================================

def _try_parse_json(json_str: str) -> Optional[_ExtractOutput]:
    """尝试将 JSON 字符串解析为 _ExtractOutput"""
    # 第一遍：直接解析
    try:
        data = json.loads(json_str)
        return _ExtractOutput.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        pass

    # 第二遍：清理后重试
    cleaned = _clean_json(json_str)
    if cleaned == json_str:
        # 已经和原始一样，不需要重复尝试
        logger.warning(
            "JSON 解析/校验失败: %s\n原始内容 (前 500 字符): %s",
            "已尝试清理但无效",
            json_str[:500],
        )
        return None

    try:
        data = json.loads(cleaned)
        logger.info("JSON 清理后解析成功")
        return _ExtractOutput.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(
            "JSON 解析/校验失败: %s\n原始内容 (前 500 字符): %s",
            str(e)[:200],
            json_str[:500],
        )
        return None


def _build_paper_text(chunks: List[TextChunk]) -> str:
    """
    将 chunks 拼接为 LLM 可处理的文本。
    MVP-0: 直接拼接所有 chunk 内容。
    后续可优化：按章节摘要、截断过长文本。
    """
    # 按 section_title 组织
    sections: Dict[str, List[str]] = {}
    for chunk in chunks:
        key = chunk.section_title or "正文"
        if key not in sections:
            sections[key] = []
        sections[key].append(chunk.content)

    lines = []
    for section, texts in sections.items():
        lines.append(f"\n## {section}")
        lines.append("\n".join(texts))

    full_text = "\n".join(lines)
    # 限制最大长度：更小的文本 = 更快的 LLM 响应和更低的 token 成本
    max_chars = 40000
    if len(full_text) > max_chars:
        logger.warning(f"论文全文过长 ({len(full_text)} 字符)，截断到 {max_chars}")
        full_text = full_text[:max_chars]

    return full_text


# API 致命错误类（不应重试，直接报告给用户）
_FATAL_ERROR_PREFIXES = ("401", "403", "404", "invalid api", "not found", "unauthorized")


def _is_fatal_error(error: Exception) -> bool:
    """判断是否为致命 API 错误（如认证失败、模型不存在）"""
    msg = str(error).lower()
    return any(pfx in msg for pfx in _FATAL_ERROR_PREFIXES)


def _safe_format_prompt(template: str, **kwargs) -> str:
    """
    安全地填充 Prompt 模板，避免论文文本中的 {} 被 .format() 误解析。
    先将所有占位符替换为唯一标记，然后填充。
    """
    result = template
    for key, value in kwargs.items():
        placeholder = "{" + key + "}"
        result = result.replace(placeholder, value)
    return result


def _extract_with_fallback(paper_text: str, chunks: List[TextChunk]) -> Tuple[
    Optional[_ExtractOutput], List[str], Dict[str, Any]
]:
    """
    三级 fallback 抽取流程：
    L1: 原 Prompt
    L2: 纠错 Prompt
    L3: 逐实体降级（提取 paper 基本信息，methods/datasets 留空）

    返回: (parsed_output, failed_chunk_ids, metadata)

    注意：API 致命错误（401/403/404）会直接抛出，不进入下一级。
    """
    failed_chunk_ids = [c.chunk_id for c in chunks]
    metadata = {
        "model": settings.LLM_MODEL_NAME,
        "prompt_version": settings.PROMPT_VERSION,
        "retry_level": 0,
        "latency_start": time.time(),
    }

    # --- L1: 原始 Prompt ---
    try:
        prompt_template = _load_prompt("extract_entities.txt")
        user_prompt = _safe_format_prompt(prompt_template, paper_content=paper_text)
        messages = [
            {"role": "system", "content": "You are an expert NLP research paper analyst. Always output valid JSON."},
            {"role": "user", "content": user_prompt},
        ]
        llm_output = _call_llm(messages)
        logger.info(f"L1 LLM 返回 {len(llm_output)} 字符")
        json_str = _extract_json(llm_output)
        if json_str:
            result = _try_parse_json(json_str)
            if result:
                metadata["retry_level"] = 0
                metadata["latency_ms"] = (time.time() - metadata["latency_start"]) * 1000
                logger.info("L1 抽取成功")
                return result, [], metadata
            else:
                logger.warning(f"L1 JSON 解析失败, _try_parse_json 返回 None")
        else:
            logger.warning(f"L1 未能从 LLM 输出中提取 JSON")
    except Exception as e:
        if _is_fatal_error(e):
            raise
        logger.warning(f"L1 抽取失败: {e}")

    logger.warning("L1 失败，进入 L2 纠错重试...")

    # --- L2: 纠错 Prompt ---
    try:
        correction_template = _load_prompt("extract_entities_correction.txt")
        user_prompt = _safe_format_prompt(
            correction_template,
            paper_content=paper_text,
            error_message="Previous output was not valid JSON or missing required fields.",
        )
        messages = [
            {"role": "system", "content": "You are an expert NLP research paper analyst. Output ONLY valid JSON."},
            {"role": "user", "content": user_prompt},
        ]
        llm_output = _call_llm(messages, temperature=0.0)
        logger.info(f"L2 LLM 返回 {len(llm_output)} 字符")
        json_str = _extract_json(llm_output)
        if json_str:
            result = _try_parse_json(json_str)
            if result:
                metadata["retry_level"] = 1
                metadata["latency_ms"] = (time.time() - metadata["latency_start"]) * 1000
                logger.info("L2 纠错抽取成功")
                return result, [], metadata
            else:
                logger.warning(f"L2 JSON 解析失败, _try_parse_json 返回 None")
        else:
            logger.warning(f"L2 未能从 LLM 输出中提取 JSON")
    except Exception as e:
        if _is_fatal_error(e):
            raise
        logger.warning(f"L2 抽取失败: {e}")

    logger.warning("L2 失败，进入 L3 降级抽取...")

    # --- L3: 逐实体降级 ---
    try:
        fallback_prompt = """Extract ONLY the paper's basic information from the text.
Output valid JSON:
{"paper": {"title": "...", "year": null, "venue": "...", "abstract": "..."}, "authors": [], "methods": [], "models": [], "datasets": [], "tasks": [], "metrics": [], "results": [], "relations": []}

Paper content:
{paper_content}"""
        user_prompt = _safe_format_prompt(fallback_prompt, paper_content=paper_text[:5000])
        messages = [
            {"role": "system", "content": "Output ONLY valid JSON. No extra text."},
            {"role": "user", "content": user_prompt},
        ]
        llm_output = _call_llm(messages, temperature=0.0, force_json=False)
        logger.info(f"L3 LLM 返回 {len(llm_output)} 字符")
        json_str = _extract_json(llm_output)
        if json_str:
            result = _try_parse_json(json_str)
            if result:
                metadata["retry_level"] = 2
                metadata["latency_ms"] = (time.time() - metadata["latency_start"]) * 1000
                logger.info("L3 降级抽取成功（仅提取 paper 基本信息）")
                return result, [], metadata
            else:
                logger.warning("L3 _try_parse_json 返回 None")
        else:
            logger.warning("L3 未能从 LLM 输出中提取 JSON")
    except Exception as e:
        if _is_fatal_error(e):
            raise
        logger.warning(f"L3 抽取失败: {e}")

    # 全失败
    metadata["latency_ms"] = (time.time() - metadata["latency_start"]) * 1000
    logger.error("三级抽取全部失败，返回空结果")
    return None, failed_chunk_ids, metadata


# ============================================================
# 主抽取函数
# ============================================================

def extract_entities(chunks: List[TextChunk]) -> ExtractionResult:
    """
    从文本 chunks 中抽取实体和关系。

    参数:
        chunks: 论文文本分块列表

    返回:
        ExtractionResult 包含 entities, triples, failed_chunk_ids, metadata
    """
    if not chunks:
        logger.warning("无 chunk 输入，返回空结果")
        return ExtractionResult(
            paper_id="",
            metadata={"error": "no_chunks"},
        )

    paper_id = chunks[0].paper_id
    logger.info(f"开始抽取实体和关系: paper_id={paper_id}, chunks={len(chunks)}")

    # 构建论文全文
    paper_text = _build_paper_text(chunks)

    # 三级 fallback 抽取
    output, failed_ids, meta = _extract_with_fallback(paper_text, chunks)

    if output is None:
        # 全失败
        return ExtractionResult(
            paper_id=paper_id,
            failed_chunk_ids=failed_ids,
            metadata=meta,
        )

    # ============================================================
    # 将 LLM 输出转换为 Entity 和 Triple 对象（扩展版）
    # ============================================================

    entities: List[Entity] = []
    triples: List[Triple] = []
    entity_map: Dict[str, str] = {}  # name -> entity_id

    paper_title = output.paper.title

    # Paper 实体
    if paper_title:
        props = {
            "title": paper_title,
            "year": output.paper.year,
            "venue": output.paper.venue,
            "abstract": output.paper.abstract,
        }
        if output.paper.title_zh:
            props["name_zh"] = output.paper.title_zh
        e = Entity(
            entity_type="Paper",
            name=paper_title,
            source_paper_id=paper_id,
            properties=props,
        )
        entities.append(e)
        entity_map[paper_title] = e.entity_id

    # Author 实体
    for a in output.authors:
        if a.name and a.name.strip():
            props = {"affiliation": a.affiliation}
            if a.name_zh:
                props["name_zh"] = a.name_zh
            e = Entity(
                entity_type="Author",
                name=a.name.strip(),
                source_paper_id=paper_id,
                properties=props,
            )
            entities.append(e)
            entity_map[a.name.strip()] = e.entity_id

    # Method 实体
    for m in output.methods:
        if m.name and m.name.strip():
            props = {"description": m.description}
            if m.name_zh:
                props["name_zh"] = m.name_zh
            e = Entity(
                entity_type="Method",
                name=m.name.strip(),
                source_paper_id=paper_id,
                properties=props,
            )
            entities.append(e)
            entity_map[m.name.strip()] = e.entity_id

    # Model 实体
    for m in output.models:
        if m.name and m.name.strip():
            props = {"param_count": m.param_count}
            if m.name_zh:
                props["name_zh"] = m.name_zh
            e = Entity(
                entity_type="Model",
                name=m.name.strip(),
                source_paper_id=paper_id,
                properties=props,
            )
            entities.append(e)
            entity_map[m.name.strip()] = e.entity_id

    # Dataset 实体
    for d in output.datasets:
        if d.name and d.name.strip():
            props = {"size": d.size, "domain": d.domain}
            if d.name_zh:
                props["name_zh"] = d.name_zh
            e = Entity(
                entity_type="Dataset",
                name=d.name.strip(),
                source_paper_id=paper_id,
                properties=props,
            )
            entities.append(e)
            entity_map[d.name.strip()] = e.entity_id

    # Task 实体
    for t in output.tasks:
        if t.name and t.name.strip():
            props = {"description": t.description}
            if t.name_zh:
                props["name_zh"] = t.name_zh
            e = Entity(
                entity_type="Task",
                name=t.name.strip(),
                source_paper_id=paper_id,
                properties=props,
            )
            entities.append(e)
            entity_map[t.name.strip()] = e.entity_id

    # Metric 实体
    for m in output.metrics:
        if m.name and m.name.strip():
            props = {"description": m.description}
            if m.name_zh:
                props["name_zh"] = m.name_zh
            e = Entity(
                entity_type="Metric",
                name=m.name.strip(),
                source_paper_id=paper_id,
                properties=props,
            )
            entities.append(e)
            entity_map[m.name.strip()] = e.entity_id

    # Result 实体
    for r in output.results:
        name = f"{r.method} on {r.dataset} ({r.metric})"
        if name.strip() and r.value:
            e = Entity(
                entity_type="Result",
                name=name.strip(),
                source_paper_id=paper_id,
                properties={
                    "method": r.method, "dataset": r.dataset,
                    "metric": r.metric, "value": r.value,
                },
            )
            entities.append(e)
            entity_map[name.strip()] = e.entity_id

    # Institution 实体（从作者 affiliation 推断）
    for a in output.authors:
        if a.affiliation and a.affiliation.strip():
            inst_name = a.affiliation.strip()
            if inst_name not in entity_map:
                e = Entity(
                    entity_type="Institution",
                    name=inst_name,
                    source_paper_id=paper_id,
                )
                entities.append(e)
                entity_map[inst_name] = e.entity_id

    # Domain 实体（从 Task 推断）
    known_domains = {
        "Knowledge Graph": True, "NLP": True, "Computer Vision": True,
        "Information Retrieval": True, "Graph Learning": True,
        "Temporal Reasoning": True, "Link Prediction": True,
        "Question Answering": True, "Text Classification": True,
    }
    for t in output.tasks:
        if t.name.strip() in known_domains and t.name.strip() not in entity_map:
            e = Entity(entity_type="Domain", name=t.name.strip(), source_paper_id=paper_id)
            entities.append(e)
            entity_map[t.name.strip()] = e.entity_id

    # Triple 关系 — 统一匹配逻辑
    def _find_entity_id(name: str) -> Optional[str]:
        if name in entity_map:
            return entity_map[name]
        for ename, eid in entity_map.items():
            if ename.lower().strip() == name.lower().strip():
                return eid
        return None

    for r in output.relations:
        relation_type = normalize_relation_type(r.type)
        source_id = _find_entity_id(r.source.strip())
        target_id = _find_entity_id(r.target.strip())

        if source_id and target_id:
            triple = Triple(
                relation_type=relation_type,
                source_entity_id=source_id,
                target_entity_id=target_id,
                source_entity_name=r.source.strip(),
                target_entity_name=r.target.strip(),
                source_paper_id=paper_id,
                llm_model=settings.LLM_MODEL_NAME,
                prompt_version=settings.PROMPT_VERSION,
            )
            triples.append(triple)
        else:
            logger.warning(
                f"无法匹配实体: src={r.source}(id={source_id}), "
                f"tgt={r.target}(id={target_id}), rel={relation_type}"
            )

    # 更新成功 chunk 的状态
    for chunk in chunks:
        chunk.extraction_status = "success"

    logger.info(
        f"抽取完成: {len(entities)} 个实体, {len(triples)} 个关系, "
        f"耗时 {meta.get('latency_ms', 0):.0f}ms"
    )

    return ExtractionResult(
        paper_id=paper_id,
        entities=entities,
        triples=triples,
        failed_chunk_ids=failed_ids,
        metadata=meta,
    )
