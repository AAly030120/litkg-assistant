"""
LitKG Assistant — GraphRAG 问答模块（MVP-1 完整版）
支持：
1. 问题类型分类 + 实体优先级匹配
2. 混合检索（KG 图谱 + ChromaDB 向量）— MVP-1 新增
3. 跨论文对比问答 — MVP-1 新增
4. 结构化 JSON 输出（answer/evidence/source_chapter）
"""

import json
import logging
import re
import time
from typing import Any, Dict, List

from config.settings import settings
from core.kg_store import KGStore
from core.models import Answer, Entity, Triple

logger = logging.getLogger(__name__)

# MVP-1: 导入向量存储
try:
    from core.vector_store import VectorStore, get_vector_store
    _HAS_VECTOR_STORE = True
except ImportError:
    _HAS_VECTOR_STORE = False
    logger.warning("VectorStore 不可用，将禁用向量检索")


# ============================================================
# 问题类型分类与关键词扩展
# ============================================================

# 问题类型定义（扩展版）
QUESTION_TYPE_METHOD = "method"           # 方法类问题
QUESTION_TYPE_LIMITATION = "limitation"   # 不足类问题
QUESTION_TYPE_SUMMARY = "summary"         # 总结类问题
QUESTION_TYPE_COMPARISON = "comparison"   # 比较类问题
QUESTION_TYPE_FACTUAL = "factual"         # 事实类问题
QUESTION_TYPE_STATISTICAL = "statistical" # 统计类问题
QUESTION_TYPE_GRAPH = "graph"             # 图谱遍历问题
QUESTION_TYPE_GENERAL = "general"         # 通用问题

# 问题类型关键词映射（用于分类）— 扩展版
QUESTION_TYPE_KEYWORDS = {
    QUESTION_TYPE_METHOD: [
        "方法", "method", "approach", "算法", "algorithm", "模型", "model",
        "提出", "propose", "设计", "design", "实现", "implement",
        "什么方法", "哪些方法", "how does", "what method",
    ],
    QUESTION_TYPE_LIMITATION: [
        "不足", "局限", "缺点", "缺陷", "limitation", "shortcoming", "drawback",
        "问题", "problem", "缺陷", "弱点", "weakness",
        "有什么问题", "有哪些不足", "what are the limitations",
    ],
    QUESTION_TYPE_SUMMARY: [
        "摘要", "总结", "概述", "summary", "abstract", "概述", "介绍",
        "这篇论文", "this paper", "这篇文章", "主要内容", "main contribution",
    ],
    QUESTION_TYPE_COMPARISON: [
        "区别", "比较", "vs", "versus", "difference", "对比", "不同",
        "比较一下", "compare", "哪种更好", "which is better",
        "哪个", "哪些", "优劣", "优劣对比", "优缺点",
    ],
    QUESTION_TYPE_FACTUAL: [
        "什么是", "什么是", "what is", "定义", "define", "概念",
        "解释", "explain", "描述", "describe",
    ],
    QUESTION_TYPE_STATISTICAL: [
        "多少", "how many", "几篇", "几个", "数量", "count",
        "统计", "statistics", "一共", "总共有",
    ],
    QUESTION_TYPE_GRAPH: [
        "关联", "相关", "关系", "related", "connected", "linked",
        "使用哪些", "使用了什么", "哪些实体", "图谱",
    ],
}

# 实体类型优先级映射 — 扩展版（包含新实体类型）
ENTITY_TYPE_PRIORITY = {
    QUESTION_TYPE_METHOD: ["Method", "Model", "Task", "Paper"],
    QUESTION_TYPE_LIMITATION: ["Result", "Dataset", "Method", "Paper"],
    QUESTION_TYPE_SUMMARY: ["Paper", "Method", "Task", "Domain"],
    QUESTION_TYPE_COMPARISON: ["Method", "Result", "Dataset", "Metric", "Paper"],
    QUESTION_TYPE_FACTUAL: ["Method", "Model", "Task", "Paper", "Domain"],
    QUESTION_TYPE_STATISTICAL: ["Dataset", "Metric", "Result", "Paper"],
    QUESTION_TYPE_GRAPH: ["Paper", "Method", "Dataset", "Model", "Author", "Institution", "Domain"],
    QUESTION_TYPE_GENERAL: ["Paper", "Method", "Dataset", "Task", "Model", "Author"],
}

# 关键词扩展映射（中文 → 英文同义词）
KEYWORD_EXPANSION = {
    "方法": ["method", "approach", "algorithm", "model", "technique"],
    "模型": ["model", "architecture", "network", "framework"],
    "数据集": ["dataset", "benchmark", "corpus", "data"],
    "实验": ["experiment", "evaluation", "evaluation", "result"],
    "结果": ["result", "performance", "accuracy", "F1", "BLEU"],
    "提出": ["propose", "introduce", "present", "develop"],
}


def _classify_question_type(question: str) -> str:
    """根据问题内容分类问题类型"""
    q_lower = question.lower()
    scores = {qt: 0 for qt in QUESTION_TYPE_KEYWORDS}

    for q_type, keywords in QUESTION_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in q_lower:
                scores[q_type] += 1

    # 返回得分最高的问题类型，如果全部为0则返回 general
    max_type = max(scores, key=scores.get)
    return max_type if scores[max_type] > 0 else QUESTION_TYPE_GENERAL


def _expand_keywords(keywords: List[str]) -> List[str]:
    """扩展关键词（添加同义词）"""
    expanded = []
    for kw in keywords:
        expanded.append(kw)
        # 检查是否需要扩展
        for cn, en_list in KEYWORD_EXPANSION.items():
            if cn in kw or any(en in kw.lower() for en in en_list):
                expanded.extend(en_list)
    return list(set(expanded))  # 去重


# ============================================================
# Prompt 加载
# ============================================================

def _load_prompt(filename: str) -> str:
    prompt_path = settings.prompts_dir_abs_path / filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


# ============================================================
# 关键词提取
# ============================================================

_KEYWORD_EXTRACT_PROMPT = """Extract key named entities from the following question about research papers.
Focus on extracting SPECIFIC entity names (method names, dataset names, paper titles, etc.), NOT generic terms.

Return ONLY a JSON object with the format:
{{"keywords": ["specific_entity_name1", "specific_entity_name2", ...], "question_type": "method|limitation|summary|comparison|general"}}

Examples:
- Question: "这篇论文提出了什么方法" → keywords: ["RAG", "Retrieval-Augmented Generation"]
- Question: "RAG 在哪些数据集上测试" → keywords: ["RAG", "dataset"]
- Question: "这篇论文的摘要" → keywords: ["paper", "abstract"]

Question: {question}"""


def _extract_keywords(question: str) -> Dict[str, Any]:
    """
    使用 LLM 从问题中提取关键词和意图。
    如果 LLM 不可用，回退到基于规则的分类。
    """
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT,
        )
        messages = [
            {"role": "system", "content": "You extract keywords from questions. Output ONLY JSON."},
            {"role": "user", "content": _KEYWORD_EXTRACT_PROMPT.format(question=question)},
        ]
        response = client.chat.completions.create(
            model=settings.LLM_MODEL_NAME,
            messages=messages,
            temperature=0.0,
        )
        content = response.choices[0].message.content
        if content:
            # 提取 JSON
            m = re.search(r"\{[\s\S]*\}", content.strip())
            if m:
                data = json.loads(m.group(0))
                keywords = data.get("keywords", [])
                question_type = data.get("question_type", "general")
                # 关键词扩展
                keywords = _expand_keywords(keywords)
                return {
                    "keywords": keywords,
                    "question_type": question_type,
                }
    except Exception as e:
        logger.warning(f"关键词提取 LLM 调用失败: {e}")

    # 回退：基于规则的分类 + 简单分词
    question_type = _classify_question_type(question)
    fallback = _fallback_keyword_extract(question)
    fallback["question_type"] = question_type
    return fallback


def _fallback_keyword_extract(question: str) -> Dict[str, Any]:
    """
    基于规则的简单关键词提取（LLM 不可用时的回退方案）。
    """
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
        "to", "for", "of", "with", "by", "from", "as", "and", "or", "not",
        "what", "which", "how", "when", "where", "who", "why", "does", "do",
        "this", "that", "these", "those", "have", "has", "been", "can",
        "will", "would", "could", "should", "may", "论文", "什么", "哪些",
        "有什么", "怎么", "如何", "的", "了", "是", "吗", "呢", "吧", "这", "那",
    }

    # 分词
    tokens = re.findall(r"[a-zA-Z]+|[^\x00-\x7F]+", question)
    keywords = []
    for t in tokens:
        t_lower = t.lower()
        if t_lower not in stopwords and len(t) >= 3:
            keywords.append(t)

    return {"keywords": keywords}


# ============================================================
# 图谱检索（优化版）
# ============================================================

_MIN_MATCH_THRESHOLD = 1  # 最小匹配实体数阈值


def _search_graph(question: str, keywords: List[str], question_type: str, kg: KGStore) -> Dict[str, Any]:
    """
    在知识图谱中检索与问题相关的实体和子图。
    优化策略：
    1. 根据问题类型优先匹配特定实体类型
    2. 关键词扩展提升匹配率
    3. 至少匹配1个实体才使用图谱，否则返回空
    4. 新增：关键词匹配失败后，按类型全量检索（fallback）
    """
    matched_entity_ids: set[str] = set()
    matched_entities: List[Entity] = []

    # 获取实体类型优先级
    priority_types = ENTITY_TYPE_PRIORITY.get(question_type, ["Paper", "Method", "Dataset"])

    # 第一遍：按优先级匹配实体类型（关键词匹配）
    for entity_type in priority_types:
        for kw in keywords:
            entities = kg.search_by_name(kw, entity_type=entity_type)
            for e in entities:
                if e.entity_id not in matched_entity_ids:
                    matched_entity_ids.add(e.entity_id)
                    matched_entities.append(e)

    # 第二遍：不限制类型，匹配所有实体
    if len(matched_entity_ids) < _MIN_MATCH_THRESHOLD:
        for kw in keywords:
            entities = kg.search_by_name(kw)
            for e in entities:
                if e.entity_id not in matched_entity_ids:
                    matched_entity_ids.add(e.entity_id)
                    matched_entities.append(e)

    # 第三遍（Fallback）：关键词匹配失败，按类型全量检索
    if len(matched_entity_ids) < _MIN_MATCH_THRESHOLD:
        logger.info(f"关键词匹配失败，回退到按类型全量检索（类型: {priority_types[0]}）")
        for entity_type in priority_types:
            entities = kg.search_by_type(entity_type)
            for e in entities:
                if e.entity_id not in matched_entity_ids:
                    matched_entity_ids.add(e.entity_id)
                    matched_entities.append(e)

    if not matched_entity_ids:
        logger.info(f"图谱检索未找到匹配实体（问题类型: {question_type}, 关键词: {keywords}）")
        return {"entities": [], "triples": [], "question_type": question_type}

    # 对每个匹配实体获取邻居
    all_entities: Dict[str, Entity] = {}
    all_triples: List[Triple] = []

    for eid in matched_entity_ids:
        neighbors = kg.get_neighbors(eid, hops=settings.KG_HOPS)
        for ent in neighbors["entities"]:
            all_entities[ent.entity_id] = ent
        for tri in neighbors["triples"]:
            # 去重
            key = (tri.source_entity_id, tri.target_entity_id, tri.relation_type)
            if not any(
                (t.source_entity_id, t.target_entity_id, t.relation_type) == key
                for t in all_triples
            ):
                all_triples.append(tri)

    logger.info(
        f"图谱检索（类型={question_type}）: {len(matched_entity_ids)} 个匹配实体 → "
        f"{len(all_entities)} 个邻居实体, {len(all_triples)} 条关系"
    )

    return {
        "entities": list(all_entities.values()),
        "triples": all_triples,
        "question_type": question_type,
    }


# ============================================================
# 混合检索（KG + 向量）— MVP-1 新增
# ============================================================

def retrieve_context(question: str, kg: KGStore, vector_store: Any = None,
                     paper_ids: List[str] = None) -> Dict[str, Any]:
    """
    融合检索：KG 图谱检索 + ChromaDB 向量检索。

    参数:
        question: 用户问题
        kg: 知识图谱存储对象
        vector_store: 向量存储对象（可选，默认使用全局单例）
        paper_ids: 可选，限定检索的论文 ID 列表（用于定向问答）

    返回:
        {
            "kg_context": "图谱信息：...",  # KG 检索结果（文本格式）
            "vector_context": "论文片段：...",  # 向量检索结果（文本格式）
            "merged_context": "融合后的上下文",  # 融合后的完整上下文
            "kg_entities": [...],  # KG 检索到的实体
            "kg_triples": [...],  # KG 检索到的关系
            "vector_chunks": [...],  # 向量检索到的 chunks
            "question_type": "...",  # 问题类型
            "keywords": [...],  # 关键词
        }
    """
    # Step 1: 提取关键词和问题类型
    kw_info = _extract_keywords(question)
    keywords = kw_info["keywords"]
    question_type = kw_info.get("question_type", QUESTION_TYPE_GENERAL)

    # Step 2: KG 图谱检索
    kg_result = _search_graph(question, keywords, question_type, kg)

    # ── 论文过滤 ──
    if paper_ids:
        paper_ids_lower = {pid.lower().strip() for pid in paper_ids}
        kg_result["entities"] = [
            e for e in kg_result["entities"]
            if e.source_paper_id.lower().strip() in paper_ids_lower
        ]
        kg_result["triples"] = [
            t for t in kg_result["triples"]
            if t.source_paper_id.lower().strip() in paper_ids_lower
        ]
        # 确保相关实体的 id 集合同步
        valid_eids = {e.entity_id for e in kg_result["entities"]}
        kg_result["triples"] = [
            t for t in kg_result["triples"]
            if t.source_entity_id in valid_eids and t.target_entity_id in valid_eids
        ]

    kg_context = ""
    if kg_result["entities"]:
        kg_context = kg._graph_to_text(kg_result)
        logger.info(f"KG 检索成功: {len(kg_result['entities'])} 个实体, {len(kg_result['triples'])} 条关系"
                     + (f" (限定论文: {paper_ids})" if paper_ids else ""))
    else:
        logger.info("KG 检索未找到匹配实体")

    # Step 3: 向量检索（ChromaDB）
    vector_context = ""
    vector_chunks = []
    if settings.HYBRID_RETRIEVAL and _HAS_VECTOR_STORE:
        try:
            if vector_store is None:
                vector_store = get_vector_store()
            vector_results = vector_store.search(
                query=question,
                k=settings.TOP_K_CHUNKS,
            )
            if vector_results:
                vector_chunks = vector_results
                # 格式化向量检索结果
                lines = []
                lines.append(f"## 相关论文片段（{len(vector_results)} 个）:")
                for i, chunk in enumerate(vector_results, 1):
                    metadata = chunk.get("metadata", {})
                    paper_title = metadata.get("paper_title", "") or metadata.get("paper_id", "Unknown")
                    section = metadata.get("section_title", "")
                    text = chunk.get("text", "")
                    # 截断过长文本
                    text_preview = text[:300] + "..." if len(text) > 300 else text
                    line = f"{i}. 【{paper_title}】"
                    if section:
                        line += f"（{section}）"
                    line += f"\n   {text_preview}"
                    lines.append(line)
                vector_context = "\n".join(lines)
                logger.info(f"向量检索成功: {len(vector_results)} 个 chunks")
        except Exception as e:
            logger.warning(f"向量检索失败: {e}")
    else:
        if not settings.HYBRID_RETRIEVAL:
            logger.info("混合检索已禁用（HYBRID_RETRIEVAL=false）")
        if not _HAS_VECTOR_STORE:
            logger.info("VectorStore 不可用，跳过向量检索")

    # Step 4: 融合上下文
    merged_lines = []
    if kg_context:
        merged_lines.append("=== 知识图谱信息 ===")
        merged_lines.append(kg_context)
    if vector_context:
        merged_lines.append("\n=== 论文原文片段 ===")
        merged_lines.append(vector_context)
    if not kg_context and not vector_context:
        # 即使没有精确匹配，也把 KG 中所有 Paper 实体列出来供 LLM 参考
        all_papers = kg.search_by_type("Paper")
        if all_papers:
            paper_info = ["以下系统中已处理的论文（但未检索到与问题直接相关的内容）:"]
            for p in all_papers:
                paper_info.append(f"  - {p.name}")
            # 也列出所有 Method 实体作为参考
            all_methods = kg.search_by_type("Method")
            if all_methods:
                paper_info.append("\n已知方法:")
                for m in all_methods[:20]:
                    paper_info.append(f"  - {m.name} (来自论文: {m.source_paper_id[:8]})")
            merged_lines.append("\n".join(paper_info))
            logger.info(f"无精确匹配，提供 {len(all_papers)} 篇论文概览作为上下文")
        else:
            merged_lines.append("（知识图谱为空，暂无任何论文数据。请先上传并处理论文。）")

    merged_context = "\n".join(merged_lines)

    return {
        "kg_context": kg_context,
        "vector_context": vector_context,
        "merged_context": merged_context,
        "kg_entities": kg_result["entities"],
        "kg_triples": kg_result["triples"],
        "vector_chunks": vector_chunks,
        "question_type": question_type,
        "keywords": keywords,
    }


# ============================================================
# 回答生成（MVP-1 优化：支持混合上下文 + 跨论文对比）
# ============================================================

def _is_cross_paper_question(question: str, retrieval_result: Dict, kg: KGStore = None) -> bool:
    """判断是否是跨论文对比问题"""
    # 检查 vector_chunks 是否来自多篇论文
    vector_chunks = retrieval_result.get("vector_chunks", [])
    paper_titles = set()
    for chunk in vector_chunks:
        metadata = chunk.get("metadata", {})
        paper_title = metadata.get("paper_title", "")
        if paper_title:
            paper_titles.add(paper_title)

    # 检查 KG 实体中是否包含多个 Paper 类型实体
    kg_has_multiple_papers = False
    if kg is not None:
        papers = kg.search_by_type("Paper")
        if len(papers) >= 2:
            # 进一步检查：这些论文名是否出现在问题中
            q_lower = question.lower()
            matched_papers_in_q = sum(
                1 for p in papers
                if p.name.lower()[:30] in q_lower or any(word in q_lower for word in p.name.lower().split()[:5])
            )
            if matched_papers_in_q >= 2:
                kg_has_multiple_papers = True

    # 问题中包含对比关键词
    cross_kw = ["对比", "compare", "vs", "区别", "不同论文", "哪些论文", "多论文",
                "共同点", "分别讲", "三篇论文", "两篇论文"]
    q_lower = question.lower()
    has_cross_keyword = any(kw in q_lower for kw in cross_kw)

    return (len(paper_titles) > 1) or has_cross_keyword or kg_has_multiple_papers


def _generate_answer(
    question: str,
    merged_context: str,
    question_type: str,
    is_cross_paper: bool = False,
) -> Dict[str, Any]:
    """
    使用 LLM 生成回答，支持混合上下文（KG + 向量）。

    参数:
        question: 用户问题
        merged_context: 融合后的上下文（KG 信息 + 论文片段）
        question_type: 问题类型
        is_cross_paper: 是否是跨论文对比问题

    返回:
        解析后的 dict，包含 answer/evidence/source_chapter 或
        cross_paper_result（跨论文对比结果）
    """
    from openai import OpenAI

    try:
        # 根据问题类型选择 Prompt 模板
        if is_cross_paper:
            prompt_template = _load_prompt("qa_cross_paper.txt")
        else:
            prompt_template = _load_prompt("qa_system.txt")

        # 填充 Prompt（qa_system.txt 新增 {question_type} 占位符）
        user_prompt = prompt_template.replace("{context}", merged_context).replace(
            "{question}", question
        ).replace("{question_type}", question_type)

        messages = [
            {"role": "system", "content": "You are a helpful research assistant."},
            {"role": "user", "content": user_prompt},
        ]

        client = OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT,
        )
        response = client.chat.completions.create(
            model=settings.LLM_MODEL_NAME,
            messages=messages,
            temperature=settings.LLM_QA_TEMPERATURE,
        )
        content = response.choices[0].message.content.strip()

        # 提取 JSON
        m = re.search(r"\{[\s\S]*\}", content)
        if m:
            data = json.loads(m.group(0))
            return data
        else:
            logger.warning(f"LLM 输出不是有效 JSON: {content[:200]}")
            return {
                "answer": content,
                "evidence": [],
                "source_chapter": "",
            }
    except Exception as e:
        logger.error(f"回答生成失败: {e}")
        return {
            "answer": f"抱歉，生成回答时出错：{str(e)}",
            "evidence": [],
            "source_chapter": "",
        }


def _format_cross_paper_answer(result: Dict) -> str:
    """
    格式化跨论文对比回答（仅保留核心内容）。
    MVP-1 前端优化：隐藏 evidence、source_entity 等非核心字段。
    支持新增的 missing_papers 字段。
    """
    # 兼容多种返回格式
    if "answer" not in result:
        return str(result.get("answer", result))

    answer = result.get("answer", {})
    if isinstance(answer, str):
        return answer

    summary = answer.get("summary", "")
    details = answer.get("details", [])
    missing_papers = answer.get("missing_papers", [])

    lines = []
    lines.append(summary)
    lines.append("")

    for i, detail in enumerate(details, 1):
        method = detail.get("method", "")
        description = detail.get("description", "")
        advantage = detail.get("advantage", "")

        lines.append(f"{i}. **{method}**")
        if description:
            lines.append(f"   - 描述：{description}")

        experiments = detail.get("experiments", [])
        if experiments:
            lines.append("   - 实验：")
            for exp in experiments:
                paper = exp.get("paper", "")
                dataset = exp.get("dataset", "")
                metric = exp.get("metric", "")
                res = exp.get("result", "")
                lines.append(f"     · 在 {paper} 中，使用 {dataset} 数据集，{metric}={res}")

        if advantage:
            lines.append(f"   - 优势：{advantage}")
        lines.append("")

    # 标注缺失的论文
    if missing_papers:
        lines.append('> ⚠️ **以下论文暂无数据**（请先在「论文管理」页处理）：')
        for mp in missing_papers:
            lines.append(f"> - {mp}")

    return "\n".join(lines)


# ============================================================
# 主问答函数（MVP-1 优化：混合检索）
# ============================================================

def ask(question: str, kg: KGStore, vector_store: Any = None,
        paper_ids: List[str] = None) -> Answer:
    """
    基于知识图谱和向量存储回答问题（MVP-1 混合检索）。

    参数:
        question: 用户问题
        kg: 知识图谱存储对象
        vector_store: 向量存储对象（可选，默认使用全局单例）
        paper_ids: 可选，限定检索的论文 ID 列表（用于定向问答）

    返回:
        Answer 对象
    """
    start_time = time.time()

    # Step 1: 混合检索（KG + 向量）
    retrieval_result = retrieve_context(question, kg, vector_store, paper_ids=paper_ids)
    merged_context = retrieval_result["merged_context"]
    question_type = retrieval_result["question_type"]
    keywords = retrieval_result["keywords"]

    # 判断是否是跨论文对比问题
    is_cross_paper = _is_cross_paper_question(question, retrieval_result, kg)

    logger.info(
        f"问答 - 关键词: {keywords}, 问题类型: {question_type}, "
        f"跨论文: {is_cross_paper}"
    )

    # Step 2: 生成回答
    result = _generate_answer(question, merged_context, question_type, is_cross_paper)

    # Step 3: 格式化输出（MVP-1：仅保留核心内容）
    answer_text = result.get("answer", "")
    if is_cross_paper:
        # 跨论文对比：使用专用格式化函数
        answer_text = _format_cross_paper_answer(result)
    elif isinstance(answer_text, dict):
        # 普通问题：提取 answer 字段
        answer_text = answer_text.get("answer", str(answer_text))

    # Step 4: 构建返回结果
    latency = (time.time() - start_time) * 1000

    return Answer(
        question=question,
        answer=answer_text,
        question_type=question_type,
        source_entities=retrieval_result["kg_entities"],
        source_triples=retrieval_result["kg_triples"],
        latency_ms=latency,
        hits_entities=len(retrieval_result["kg_entities"]),
        hits_relations=len(retrieval_result["kg_triples"]),
        hits_chunks=len(retrieval_result.get("vector_chunks", [])),
    )
