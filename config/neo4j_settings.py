"""
LitKG Assistant — Neo4j 连接配置
用于将知识图谱从 NetworkX/JSON 迁移到 Neo4j 图数据库。
MVP-2 存储升级组件。
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Neo4jSettings:
    """Neo4j 连接配置，从环境变量读取"""

    uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    user: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", ""))

    # 批量写入参数
    batch_size: int = 500
    index_fields: list = field(default_factory=lambda: ["title", "name", "entity_type"])

    # 是否启用 Neo4j（未配置密码则自动降级到 NetworkX）
    @property
    def enabled(self) -> bool:
        return bool(self.password)

    def validate(self) -> bool:
        """验证连接参数是否完整"""
        if not self.enabled:
            return False
        if not self.uri or not self.user:
            return False
        return True


# 全局单例
_neo4j_settings: Optional[Neo4jSettings] = None


def get_neo4j_settings() -> Neo4jSettings:
    global _neo4j_settings
    if _neo4j_settings is None:
        _neo4j_settings = Neo4jSettings()
    return _neo4j_settings
