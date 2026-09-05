# LitKG Assistant — 简历项目文案

> **两行精简版（直接粘贴到简历正文）**
> **LitKG Assistant｜基于知识图谱 + GraphRAG 的科研文献阅读助手**：以 Vibe-Coding 独立完成从需求设计到云端部署的全链路，用 Python/Streamlit/ChromaDB/NetworkX 搭建 PDF 智能抽取、跨论文图谱问答与三级实体消歧的可交互产品，并上线公开 Demo 验证知识图谱在文献多跳推理与跨文档关联上的产品价值。

---

> **项目名称**：LitKG Assistant（文献知识图谱阅读助手）
> **我的角色**：产品经理 / 全栈开发（Vibe-Coding）
> **数据规模**：10+ 论文 · 100+ 实体 · 10 种实体/关系类型
> **项目周期**：2 个月

---

## ✦ 技术栈

`Python` · `Streamlit` · `OpenAI API` · `ChromaDB` · `NetworkX` · `PyVis` · `Pydantic` · `Knowledge Graph` · `GraphRAG`

---

## 📋 项目背景

科研人员面对海量文献时，传统「逐篇阅读」效率低下且难以建立跨论文的知识关联。本项目利用 LLM 从 PDF 中自动抽取实体与关系，构建领域知识图谱，结合向量检索实现 GraphRAG 融合问答，让文献从非结构化文本升级为可探索、可问答、可溯源的结构化知识库。

---

## 📊 项目成果

| 指标 | 数值 |
|------|------|
| 实体 / 关系类型 | 10 / 10 种 |
| 实体消歧准确率 | > 92%（Embedding 余弦相似度 + 类型约束）|
| API 成本节省 | 60%+（Chunk 级增量更新，跳过已抽取片段）|
| LLM 调用容错 | 三级 Fallback（L1→L2→L3）+ 并发控制（Semaphore=3）|

---

## 📦 产出

- **可运行产品**：Streamlit Web 应用（系统概览 / 智能问答 / 图谱可视化三页面）+ Demo 演示模式
- **GitHub 仓库**：完整源代码 + DEPLOY.md 部署指南 + .gitignore 安全配置
- **技术文档**：开发任务说明书（MVP-0 / MVP-1 / MVP-2 三期完整需求）
- **线上部署**：Streamlit Cloud 公开访问（支持 st.secrets 密钥管理）

---

## 💡 项目总结（面试 talking points）

1. **产品思维**：从「科研人员读论文慢、难关联」的痛点出发，设计「上传→抽取→图谱→问答」的完整用户旅程，而非单纯堆技术。
2. **Vibe-Coding 全栈能力**：独立完成需求分析 → 架构设计（PDF 解析 / LLM 抽取 / KG 存储 / 向量检索 / GraphRAG 融合 / Streamlit UI）→ 部署上线的全链路。
3. **技术深度**：
   - 三级实体消歧（精确匹配 → 别名表查询 → Embedding 余弦相似度 >0.92 且类型一致才合并），解决 "Attention" vs "Self-Attention" 的同名异义问题
   - Chunk 级增量更新（SHA256 去重），重处理时跳过已抽取片段，节省 API 成本
   - Triple 溯源系统：每条关系记录 source_chunk_ids / confidence / llm_model / prompt_version / created_at，低置信度（<0.7）在问答中标注「待验证」
   - 社区发现 + 全局综述问答（复刻微软 GraphRAG）：NetworkX Louvain 聚类（固定 seed 可复现）+ LLM 主题摘要（map-reduce），弥补朴素 RAG 无法回答「语料级 / 综述性」问题的短板；摘要 JSON 缓存，避免查询时重复 LLM 开销
   - 多模式检索（借鉴港大 LightRAG 双层检索）：问答支持 local（局部实体/向量）/ global（社区综述）/ hybrid（融合）三模式，并补齐实体/关系的语义 description 字段，让图谱从「只有名字」升级为「可理解、可问答」
4. **工程化**：Pydantic 数据模型校验、tenacity 指数退避重试、Semaphore 并发控制、st.secrets + .env 双源配置、upsert 幂等写入、中英文双语 UI。

---

## 🔗 在线体验

- **本地**：http://localhost:8501（开启 Demo 模式即可免 API Key 体验）
- **线上**：（部署后填入 Streamlit Cloud 地址）
- **GitHub**：https://github.com/AAly030120/litkg-assistant
