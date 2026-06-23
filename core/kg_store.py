"""
LitKG Assistant — 知识图谱存储模块
基于 NetworkX 内存图 + JSON 文件持久化（MVP-0）。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from config.settings import settings
from core.models import Entity, Triple, normalize_relation_type

logger = logging.getLogger(__name__)


class KGStore:
    """
    知识图谱存储管理器。
    - 底层使用 networkx.DiGraph 有向图
    - 节点 = Entity（entity_id 作为 node id）
    - 边 = Triple 关系
    - 持久化到 JSON 文件
    """

    def __init__(self, json_path: str = None):
        """
        初始化 KG 存储。

        参数:
            json_path: JSON 持久化文件路径，默认从 settings 读取
        """
        self.graph = nx.DiGraph()
        self._json_path = Path(json_path or settings.kg_json_abs_path)
        self._loaded = False

    # ============================================================
    # 持久化
    # ============================================================

    def save_to_json(self) -> None:
        """
        将当前图序列化为 JSON 保存到文件。
        格式:
        {
            "entities": [ {entity dict}, ... ],
            "triples": [ {triple dict}, ... ],
            "stats": { ... }
        }
        """
        self._json_path.parent.mkdir(parents=True, exist_ok=True)

        entities_data = []
        for node_id, attrs in self.graph.nodes(data=True):
            ent = {
                "entity_id": node_id,
                "entity_type": attrs.get("entity_type", ""),
                "name": attrs.get("name", ""),
                "properties": attrs.get("properties", {}),
                "source_paper_id": attrs.get("source_paper_id", ""),
                "source_chunk_ids": attrs.get("source_chunk_ids", []),
                "source_section": attrs.get("source_section", ""),
            }
            entities_data.append(ent)

        triples_data = []
        for u, v, attrs in self.graph.edges(data=True):
            triple = {
                "triple_id": attrs.get("triple_id", ""),
                "relation_type": normalize_relation_type(attrs.get("relation_type", "")),
                "source_entity_id": u,
                "target_entity_id": v,
                "source_entity_name": attrs.get("source_entity_name", ""),
                "target_entity_name": attrs.get("target_entity_name", ""),
                "source_paper_id": attrs.get("source_paper_id", ""),
                "source_chunk_ids": attrs.get("source_chunk_ids", []),
                "confidence": attrs.get("confidence", 1.0),
                "llm_model": attrs.get("llm_model", ""),
                "prompt_version": attrs.get("prompt_version", "v0"),
                "created_at": attrs.get("created_at", ""),
            }
            triples_data.append(triple)

        data = {
            "entities": entities_data,
            "triples": triples_data,
            "stats": self.get_stats(),
        }

        with open(self._json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(
            f"KG 已保存到 {self._json_path}: "
            f"{len(entities_data)} 实体, {len(triples_data)} 关系"
        )

    def load_from_json(self) -> None:
        """
        从 JSON 文件加载图数据。
        如果文件不存在，静默跳过（初始状态为空图）。
        """
        if not self._json_path.exists():
            logger.info(f"KG JSON 文件不存在 ({self._json_path})，使用空图")
            self._loaded = True
            return

        with open(self._json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entities_data = data.get("entities", [])
        triples_data = data.get("triples", [])

        # 重建节点
        for ent in entities_data:
            self.graph.add_node(
                ent["entity_id"],
                entity_type=ent.get("entity_type", ""),
                name=ent.get("name", ""),
                properties=ent.get("properties", {}),
                source_paper_id=ent.get("source_paper_id", ""),
                source_chunk_ids=ent.get("source_chunk_ids", []),
                source_section=ent.get("source_section", ""),
            )

        # 重建边
        for triple in triples_data:
            self.graph.add_edge(
                triple["source_entity_id"],
                triple["target_entity_id"],
                triple_id=triple.get("triple_id", ""),
                relation_type=normalize_relation_type(triple.get("relation_type", "")),
                source_entity_name=triple.get("source_entity_name", ""),
                target_entity_name=triple.get("target_entity_name", ""),
                source_paper_id=triple.get("source_paper_id", ""),
                source_chunk_ids=triple.get("source_chunk_ids", []),
                confidence=triple.get("confidence", 1.0),
                llm_model=triple.get("llm_model", ""),
                prompt_version=triple.get("prompt_version", "v0"),
                created_at=triple.get("created_at", ""),
            )

        self._loaded = True
        logger.info(
            f"从 {self._json_path} 加载 KG: "
            f"{len(entities_data)} 实体, {len(triples_data)} 关系"
        )

    # ============================================================
    # 实体去重消歧
    # ============================================================

    @staticmethod
    def _similarity(s1: str, s2: str) -> float:
        """计算两个实体名称的相似度（基于 Jaccard 字符集）"""
        import difflib
        # 归一化：小写、去空格
        a = "".join(s1.lower().split())
        b = "".join(s2.lower().split())

        # 快速判等
        if a == b:
            return 1.0

        # 子串包含
        if a in b or b in a:
            return 0.95

        # difflib 序列匹配
        return difflib.SequenceMatcher(None, a, b).ratio()

    def _find_duplicate_entity(self, entity: Entity, threshold: float = 0.80) -> Optional[Entity]:
        """
        在当前 KG 中查找与给定实体高度相似的已有实体。
        返回匹配的 Entity 或 None。
        """
        self._ensure_loaded()
        # 仅在同类实体中比对
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("entity_type") != entity.entity_type:
                continue
            existing_name = attrs.get("name", "")
            sim = self._similarity(entity.name, existing_name)
            if sim >= threshold:
                return Entity(
                    entity_id=node_id,
                    entity_type=attrs.get("entity_type", ""),
                    name=existing_name,
                    properties=attrs.get("properties", {}),
                    source_paper_id=attrs.get("source_paper_id", ""),
                    source_chunk_ids=attrs.get("source_chunk_ids", []),
                )
        return None

    def _merge_entities(self, keep_id: str, new_entity: Entity) -> None:
        """
        合并实体：将 new_entity 的信息合并到 keep_id 对应的实体上。
        策略：保留更长的名称、合并 properties、追记来源论文。
        """
        self._ensure_loaded()
        existing = self.graph.nodes[keep_id]

        # 名称：保留更长的（通常更全）
        if len(new_entity.name) > len(existing.get("name", "")):
            existing["name"] = new_entity.name

        # 合并 properties
        merged_props = dict(existing.get("properties", {}))
        if new_entity.properties:
            for k, v in new_entity.properties.items():
                if k not in merged_props or not merged_props[k]:
                    merged_props[k] = v
                elif v and v != merged_props[k]:
                    # 不同属性值追加
                    merged_props[k] = f"{merged_props[k]}; {v}"
        existing["properties"] = merged_props

        # 追记来源论文
        if new_entity.source_paper_id and new_entity.source_paper_id not in existing.get("source_paper_id", ""):
            existing["source_paper_id"] = f"{existing.get('source_paper_id', '')}|{new_entity.source_paper_id}".strip("|")

        # 追记 chunk IDs
        existing_chunks = set(existing.get("source_chunk_ids", []))
        for cid in new_entity.source_chunk_ids:
            existing_chunks.add(cid)
        existing["source_chunk_ids"] = list(existing_chunks)

        logger.debug(f"实体合并完成: keep={keep_id[:8]}, name={existing['name']}")

    def _ensure_loaded(self) -> None:
        """懒加载：首次操作时自动从 JSON 加载"""
        if not self._loaded:
            self.load_from_json()

    # ============================================================
    # 添加
    # ============================================================

    def add_entity(self, entity: Entity) -> None:
        """添加单个实体到图中（含去重检查）"""
        self._ensure_loaded()

        # 去重检查：如果已有同名或高度相似的实体，合并而非新增
        existing = self._find_duplicate_entity(entity)
        if existing:
            logger.info(
                f"发现重复实体，「{entity.name}」将与「{existing.name}」合并 "
                f"(相似度: {self._similarity(entity.name, existing.name):.2f})"
            )
            self._merge_entities(existing.entity_id, entity)
            return

        self.graph.add_node(
            entity.entity_id,
            entity_type=entity.entity_type,
            name=entity.name,
            properties=entity.properties,
            source_paper_id=entity.source_paper_id,
            source_chunk_ids=entity.source_chunk_ids,
            source_section=entity.source_section,
        )

    def add_relation(self, triple: Triple) -> None:
        """添加单个关系到图中"""
        self._ensure_loaded()
        # 检查两端节点是否存在
        if triple.source_entity_id not in self.graph:
            logger.warning(f"源实体不存在: {triple.source_entity_id}")
            return
        if triple.target_entity_id not in self.graph:
            logger.warning(f"目标实体不存在: {triple.target_entity_id}")
            return

        self.graph.add_edge(
            triple.source_entity_id,
            triple.target_entity_id,
            triple_id=triple.triple_id,
            relation_type=normalize_relation_type(triple.relation_type),
            source_entity_name=triple.source_entity_name,
            target_entity_name=triple.target_entity_name,
            source_paper_id=triple.source_paper_id,
            source_chunk_ids=triple.source_chunk_ids,
            confidence=triple.confidence,
            llm_model=triple.llm_model,
            prompt_version=triple.prompt_version,
            created_at=triple.created_at,
        )

    def add_paper_batch(self, entities: List[Entity], triples: List[Triple]) -> None:
        """
        批量添加一篇论文的全部实体和关系。
        先添加所有实体，再添加所有关系（保证关系两端节点已存在）。
        """
        self._ensure_loaded()

        for entity in entities:
            self.add_entity(entity)

        for triple in triples:
            self.add_relation(triple)

        logger.info(f"批量添加: {len(entities)} 实体, {len(triples)} 关系")

    # ============================================================
    # 查询
    # ============================================================

    def get_entity_by_id(self, entity_id: str) -> Optional[Entity]:
        """根据 ID 获取实体"""
        self._ensure_loaded()
        if entity_id not in self.graph:
            return None
        attrs = self.graph.nodes[entity_id]
        return Entity(
            entity_id=entity_id,
            entity_type=attrs.get("entity_type", ""),
            name=attrs.get("name", ""),
            properties=attrs.get("properties", {}),
            source_paper_id=attrs.get("source_paper_id", ""),
            source_chunk_ids=attrs.get("source_chunk_ids", []),
        )

    def search_by_name(self, keyword: str, entity_type: str = None) -> List[Entity]:
        """
        按关键词模糊搜索实体。
        大小写不敏感，匹配 entity name 中包含 keyword 的所有实体。

        参数:
            keyword: 搜索关键词
            entity_type: 可选，限定实体类型
        """
        self._ensure_loaded()
        kw = keyword.lower().strip()
        results = []

        for node_id, attrs in self.graph.nodes(data=True):
            name = attrs.get("name", "")
            etype = attrs.get("entity_type", "")

            # 类型过滤
            if entity_type and etype != entity_type:
                continue

            # 模糊匹配
            if kw in name.lower():
                results.append(Entity(
                    entity_id=node_id,
                    entity_type=etype,
                    name=name,
                    properties=attrs.get("properties", {}),
                    source_paper_id=attrs.get("source_paper_id", ""),
                    source_chunk_ids=attrs.get("source_chunk_ids", []),
                ))

        return results

    def search_by_type(self, entity_type: str) -> List[Entity]:
        """按实体类型获取所有实体"""
        self._ensure_loaded()
        results = []
        for node_id, attrs in self.graph.nodes(data=True):
            if attrs.get("entity_type") == entity_type:
                results.append(Entity(
                    entity_id=node_id,
                    entity_type=entity_type,
                    name=attrs.get("name", ""),
                    properties=attrs.get("properties", {}),
                    source_paper_id=attrs.get("source_paper_id", ""),
                    source_chunk_ids=attrs.get("source_chunk_ids", []),
                ))
        return results

    def get_neighbors(self, entity_id: str, hops: int = 1) -> Dict[str, Any]:
        """
        获取实体的 N 跳邻居子图。

        参数:
            entity_id: 中心实体 ID
            hops: 跳数（1 或 2）

        返回:
            {"entities": [...], "triples": [...]}
        """
        self._ensure_loaded()

        if entity_id not in self.graph:
            return {"entities": [], "triples": []}

        # 使用 networkx 的 ego_graph 获取子图
        if hops == 1:
            subgraph = nx.ego_graph(self.graph, entity_id, radius=1, undirected=False)
        else:
            subgraph = nx.ego_graph(self.graph, entity_id, radius=hops, undirected=False)

        entities = []
        for nid in subgraph.nodes():
            attrs = self.graph.nodes[nid]
            entities.append(Entity(
                entity_id=nid,
                entity_type=attrs.get("entity_type", ""),
                name=attrs.get("name", ""),
                properties=attrs.get("properties", {}),
                source_paper_id=attrs.get("source_paper_id", ""),
                source_chunk_ids=attrs.get("source_chunk_ids", []),
            ))

        triples = []
        for u, v in subgraph.edges():
            attrs = self.graph.edges[u, v]
            triples.append(Triple(
                source_entity_id=u,
                target_entity_id=v,
                relation_type=normalize_relation_type(attrs.get("relation_type", "")),
                source_entity_name=attrs.get("source_entity_name", ""),
                target_entity_name=attrs.get("target_entity_name", ""),
                source_paper_id=attrs.get("source_paper_id", ""),
                source_chunk_ids=attrs.get("source_chunk_ids", []),
                confidence=attrs.get("confidence", 1.0),
                llm_model=attrs.get("llm_model", ""),
                prompt_version=attrs.get("prompt_version", "v0"),
            ))

        return {"entities": entities, "triples": triples}

    def get_all_entities(self) -> List[Entity]:
        """获取图中所有实体"""
        self._ensure_loaded()
        results = []
        for node_id, attrs in self.graph.nodes(data=True):
            results.append(Entity(
                entity_id=node_id,
                entity_type=attrs.get("entity_type", ""),
                name=attrs.get("name", ""),
                properties=attrs.get("properties", {}),
                source_paper_id=attrs.get("source_paper_id", ""),
                source_chunk_ids=attrs.get("source_chunk_ids", []),
            ))
        return results

    def get_all_triples(self) -> List[Dict[str, Any]]:
        """
        获取图中所有关系（三元组）。
        返回字典列表，每项包含 subject_id, relation, object_id 等。
        """
        self._ensure_loaded()
        triples = []
        for u, v, attrs in self.graph.edges(data=True):
            triples.append({
                "subject_id": u,
                "object_id": v,
                "relation": normalize_relation_type(attrs.get("relation_type", "")),
                "triple_id": attrs.get("triple_id", ""),
                "source_entity_name": attrs.get("source_entity_name", ""),
                "target_entity_name": attrs.get("target_entity_name", ""),
            })
        return triples

    # ============================================================
    # 删除
    # ============================================================

    def delete_entity(self, entity_id: str) -> bool:
        """删除单个实体及其关联关系"""
        self._ensure_loaded()
        if entity_id not in self.graph:
            return False
        self.graph.remove_node(entity_id)
        return True

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取图谱统计信息。

        返回:
            {
                "total_entities": int,
                "total_triples": int,
                "entity_type_distribution": {"Paper": 3, "Method": 5, ...},
                "relation_type_distribution": {"proposes_method": 2, ...}
            }
        """
        self._ensure_loaded()

        entity_type_dist = {}
        for _, attrs in self.graph.nodes(data=True):
            etype = attrs.get("entity_type", "Unknown")
            entity_type_dist[etype] = entity_type_dist.get(etype, 0) + 1

        relation_type_dist = {}
        for _, _, attrs in self.graph.edges(data=True):
            rtype = attrs.get("relation_type", "Unknown")
            relation_type_dist[rtype] = relation_type_dist.get(rtype, 0) + 1

        return {
            "total_entities": self.graph.number_of_nodes(),
            "total_triples": self.graph.number_of_edges(),
            "entity_type_distribution": entity_type_dist,
            "relation_type_distribution": relation_type_dist,
        }

    # ============================================================
    # 辅助
    # ============================================================

    def _graph_to_text(self, subgraph_data: Dict[str, Any]) -> str:
        """
        将邻居子图序列化为 LLM 可理解的文本。
        用于 GraphRAG 问答的上下文构建。
        """
        lines = []
        entities = subgraph_data.get("entities", [])
        triples = subgraph_data.get("triples", [])

        if entities:
            lines.append(f"## 相关知识图谱实体 ({len(entities)} 个):")
            for e in entities:
                attrs = self.graph.nodes.get(e.entity_id, {})
                source_section = attrs.get("source_section", "")
                props = ", ".join(
                    f"{k}={v}" for k, v in e.properties.items()
                    if v and k in ("year", "venue", "description", "domain")
                )
                line = f"- [{e.entity_type}] {e.name}"
                if props:
                    line += f" ({props})"
                if source_section:
                    line += f" [来源: {source_section}]"
                lines.append(line)

        if triples:
            lines.append(f"\n## 相关关系 ({len(triples)} 条):")
            for t in triples:
                lines.append(
                    f"- {t.source_entity_name} --[{t.relation_type}]--> {t.target_entity_name}"
                )

        return "\n".join(lines)

    def merge_entities(self, primary_id: str, duplicate_ids: List[str]) -> int:
        """
        手动合并实体：将多个重复实体的属性和关系合并到主实体。
        
        参数:
            primary_id: 保留的主实体 ID
            duplicate_ids: 要合并（删除）的重复实体 ID 列表
        
        返回:
            合并的关系数量
        """
        self._ensure_loaded()

        if primary_id not in self.graph:
            raise ValueError(f"主实体不存在: {primary_id}")

        primary = self.graph.nodes[primary_id]
        merged_count = 0

        for dup_id in duplicate_ids:
            if dup_id not in self.graph:
                continue
            if dup_id == primary_id:
                continue

            # 合并属性（保留非空的）
            dup_attrs = self.graph.nodes[dup_id]
            for key, val in dup_attrs.items():
                if key == "name" or key == "entity_type":
                    continue  # 不覆盖核心属性
                if val and not primary.get(key):
                    primary[key] = val

            # 合并关系：将原指向 dup_id 的边重定向到 primary_id
            # 入边
            for pred in list(self.graph.predecessors(dup_id)):
                edge_data = self.graph[pred][dup_id]
                # 如果 pred -> primary 的边已存在，跳过
                if self.graph.has_edge(pred, primary_id):
                    continue
                # 添加 pred -> primary，复制边属性
                attrs = dict(edge_data)
                self.graph.add_edge(pred, primary_id, **attrs)
                merged_count += 1

            # 出边
            for succ in list(self.graph.successors(dup_id)):
                edge_data = self.graph[dup_id][succ]
                if self.graph.has_edge(primary_id, succ):
                    continue
                attrs = dict(edge_data)
                self.graph.add_edge(primary_id, succ, **attrs)
                merged_count += 1

            # 删除重复实体节点
            self.graph.remove_node(dup_id)
            merged_count += 1  # 计数删除的节点

        self._dirty = True
        logger.info(f"合并实体完成: {primary_id} <- {duplicate_ids}, 影响 {merged_count} 条边/节点")
        return merged_count

    def find_similar_entities(self, threshold: float = 0.8) -> List[Dict]:
        """
        查找图谱中名称相似的实体对（用于手动合并且推荐）。
        
        返回:
            [{"entity1": {...}, "entity2": {...}, "similarity": 0.85}, ...]
        """
        self._ensure_loaded()
        from difflib import SequenceMatcher

        entities = list(self.get_all_entities())
        results = []

        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                e1 = entities[i]
                e2 = entities[j]
                # 同类型才比较
                if e1.entity_type != e2.entity_type:
                    continue
                ratio = SequenceMatcher(None, e1.name.lower(), e2.name.lower()).ratio()
                if ratio >= threshold:
                    results.append({
                        "entity1": e1,
                        "entity2": e2,
                        "similarity": round(ratio, 3),
                    })

        return results

    @property
    def entity_count(self) -> int:
        self._ensure_loaded()
        return self.graph.number_of_nodes()

    @property
    def triple_count(self) -> int:
        self._ensure_loaded()
        return self.graph.number_of_edges()


# ============================================================
# 全局单例
# ============================================================

_kg_store_instance = None


def get_kg_store() -> "KGStore":
    """获取全局 KG 存储实例（单例模式）"""
    global _kg_store_instance
    if _kg_store_instance is None:
        _kg_store_instance = KGStore()
    return _kg_store_instance
