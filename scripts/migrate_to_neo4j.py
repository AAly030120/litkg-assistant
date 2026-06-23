#!/usr/bin/env python
"""
LitKG Assistant — NetworkX → Neo4j 迁移脚本
将 JSON/NetworkX 知识图谱迁移到 Neo4j 图数据库。

用法:
    python scripts/migrate_to_neo4j.py [--incremental] [--dry-run]

参数:
    --incremental    增量迁移（仅迁移新增实体，基于最后迁移时间戳）
    --dry-run        试运行模式（不实际写入 Neo4j）
    --force          强制全量迁移（清空已有数据后重新导入）
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# 添加项目根目录到 Python 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from config.neo4j_settings import get_neo4j_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 迁移时间戳文件
MIGRATION_META = PROJECT_ROOT / "data" / "neo4j_migration.json"


def connect_neo4j():
    """连接到 Neo4j 数据库"""
    ncfg = get_neo4j_settings()
    if not ncfg.validate():
        raise RuntimeError(
            "Neo4j 未配置。请在 .env 中设置 NEO4J_URI、NEO4J_USER、NEO4J_PASSWORD"
        )
    try:
        from neo4j import GraphDatabase
    except ImportError:
        raise ImportError(
            "请安装 neo4j 驱动: pip install neo4j"
        )
    driver = GraphDatabase.driver(ncfg.uri, auth=(ncfg.user, ncfg.password))
    # 验证连接
    driver.verify_connectivity()
    logger.info(f"✅ Neo4j 连接成功: {ncfg.uri}")
    return driver


def create_indexes(driver):
    """为实体类型和名称创建索引"""
    indexes = [
        "CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.entity_type)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.name)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Paper) ON (n.title)",
        "CREATE INDEX IF NOT EXISTS FOR (n:Method) ON (n.name)",
    ]
    with driver.session() as session:
        for idx_sql in indexes:
            try:
                session.run(idx_sql)
                logger.info(f"  索引创建/确认: {idx_sql[:60]}...")
            except Exception as e:
                logger.warning(f"  索引创建跳过: {e}")


def clear_graph(driver):
    """清空已有数据"""
    logger.warning("⚠️  正在清空 Neo4j 中的所有数据...")
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    logger.info("✅ 已清空")


def load_kg_json(kg_path: Path) -> Dict[str, Any]:
    """从 JSON 文件加载知识图谱"""
    with open(kg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def migrate_entities(driver, entities: List[Dict], dry_run: bool = False) -> int:
    """批量导入实体到 Neo4j"""
    if not entities:
        return 0

    total = len(entities)
    batch_size = 200
    imported = 0

    for i in range(0, total, batch_size):
        batch = entities[i:i + batch_size]

        if dry_run:
            for e in batch:
                logger.info(f"  [DRY-RUN] 实体: [{e.get('entity_type')}] {e.get('name')}")
            continue

        with driver.session() as session:
            for entity in batch:
                etype = entity.get("entity_type", "Entity")
                name = entity.get("name", "Unknown")
                eid = entity.get("entity_id", "")
                props = entity.get("properties", {})
                source_paper = entity.get("source_paper_id", "")

                # 构造 Cypher 语句
                cypher = """
                MERGE (e:Entity {entity_id: $entity_id})
                SET e.name = $name,
                    e.entity_type = $entity_type,
                    e.source_paper_id = $source_paper_id"""
                # 动态添加子标签
                if etype == "Paper":
                    cypher += "\nSET e:Paper"
                elif etype == "Method":
                    cypher += "\nSET e:Method"
                elif etype == "Dataset":
                    cypher += "\nSET e:Dataset"

                # 附加 properties
                params = {
                    "entity_id": eid,
                    "name": name,
                    "entity_type": etype,
                    "source_paper_id": source_paper,
                }
                for k, v in props.items():
                    safe_key = k.replace("-", "_").replace(" ", "_")
                    cypher += f"\nSET e.{safe_key} = ${safe_key}"
                    params[safe_key] = str(v)[:500]  # 截断过长值

                try:
                    session.run(cypher, params)
                    imported += 1
                except Exception as e:
                    logger.error(f"  实体导入失败 [{name}]: {e}")

    logger.info(f"✅ 实体导入完成: {imported}/{total}")
    return imported


def migrate_relations(driver, triples: List[Dict], dry_run: bool = False) -> int:
    """批量导入关系到 Neo4j"""
    if not triples:
        return 0

    total = len(triples)
    batch_size = 200
    imported = 0

    for i in range(0, total, batch_size):
        batch = triples[i:i + batch_size]

        if dry_run:
            for t in batch:
                logger.info(
                    f"  [DRY-RUN] 关系: {t.get('source_id','')[:8]} "
                    f"-[:{t.get('relation_type')}]-> {t.get('target_id','')[:8]}"
                )
            continue

        with driver.session() as session:
            for triple in batch:
                source_id = triple.get("source_id", "")
                target_id = triple.get("target_id", "")
                rel_type = triple.get("relation_type", "RELATED").replace("-", "_")

                cypher = f"""
                MATCH (a:Entity {{entity_id: $source_id}})
                MATCH (b:Entity {{entity_id: $target_id}})
                MERGE (a)-[r:{rel_type}]->(b)
                SET r.weight = coalesce(r.weight, 1.0)
                """
                try:
                    session.run(cypher, {"source_id": source_id, "target_id": target_id})
                    imported += 1
                except Exception as e:
                    logger.error(f"  关系导入失败 [{rel_type}]: {e}")

    logger.info(f"✅ 关系导入完成: {imported}/{total}")
    return imported


def save_migration_meta(entity_count: int, triple_count: int):
    """保存迁移元数据（用于增量迁移）"""
    meta = {
        "last_migration": datetime.now(timezone.utc).isoformat(),
        "entity_count": entity_count,
        "triple_count": triple_count,
        "kg_json_mtime": settings.kg_json_abs_path.stat().st_mtime
        if settings.kg_json_abs_path.exists()
        else None,
    }
    MIGRATION_META.parent.mkdir(parents=True, exist_ok=True)
    with open(MIGRATION_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    logger.info(f"✅ 迁移元数据已保存: {MIGRATION_META}")


def run_sample_queries(driver):
    """运行示例查询"""
    queries = [
        (
            "查询所有论文及其提出的方法",
            """
            MATCH (p:Paper)-[:proposes_method]->(m:Method)
            RETURN p.name AS paper, m.name AS method
            LIMIT 10
            """,
        ),
        (
            "查询各数据集上的方法数量",
            """
            MATCH (m:Method)-[:evaluated_on]->(d:Dataset)
            RETURN d.name AS dataset, count(m) AS method_count
            ORDER BY method_count DESC
            LIMIT 10
            """,
        ),
        (
            "查询 RAG 相关方法",
            """
            MATCH (m:Method)
            WHERE toLower(m.name) CONTAINS 'rag'
            RETURN m.name AS method, m.source_paper_id AS paper
            LIMIT 10
            """,
        ),
    ]

    logger.info("\n" + "=" * 60)
    logger.info("📊 示例查询结果")
    logger.info("=" * 60)

    with driver.session() as session:
        for title, cypher in queries:
            logger.info(f"\n🔍 {title}")
            try:
                result = session.run(cypher)
                records = list(result)
                if records:
                    for record in records[:5]:
                        logger.info(f"  • {dict(record)}")
                else:
                    logger.info("  (无结果)")
            except Exception as e:
                logger.error(f"  查询失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="LitKG-Neo4j 迁移工具")
    parser.add_argument("--incremental", action="store_true", help="增量迁移")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    parser.add_argument("--force", action="store_true", help="强制全量迁移")
    args = parser.parse_args()

    logger.info("🚀 LitKG → Neo4j 迁移工具")
    logger.info(f"  KG JSON: {settings.kg_json_abs_path}")

    if not settings.kg_json_abs_path.exists():
        logger.error("❌ 知识图谱 JSON 文件不存在，请先运行 MVP-0 管道")
        sys.exit(1)

    # 加载数据
    kg_data = load_kg_json(settings.kg_json_abs_path)
    entities = kg_data.get("entities", [])
    triples = kg_data.get("triples", [])
    logger.info(f"  KG 统计: {len(entities)} 实体, {len(triples)} 关系")

    if args.dry_run:
        logger.info("🔍 试运行模式 (Dry Run)")
        migrate_entities(None, entities, dry_run=True)
        migrate_relations(None, triples, dry_run=True)
        logger.info("✅ 试运行完成（未实际写入 Neo4j）")
        return

    # 连接 Neo4j
    driver = connect_neo4j()

    try:
        if args.force:
            clear_graph(driver)

        # 创建索引
        create_indexes(driver)

        # 迁移实体
        imported_entities = migrate_entities(driver, entities)
        # 迁移关系
        imported_relations = migrate_relations(driver, triples)

        # 保存元数据
        save_metadata = not args.incremental
        save_migration_meta(imported_entities, imported_relations)

        # 示例查询
        run_sample_queries(driver)

        logger.info("\n" + "=" * 60)
        logger.info("✅ 迁移完成！")
        logger.info(f"  实体: {imported_entities}/{len(entities)}")
        logger.info(f"  关系: {imported_relations}/{len(triples)}")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
