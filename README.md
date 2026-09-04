# LitKG Assistant — 文献阅读知识图谱助手

> 📚 上传论文 PDF → 自动抽取实体/关系 → 构建知识图谱 → 跨论文智能问答（GraphRAG）

## 项目定位
面向科研人员的 **AI 文献阅读助手**：把非结构化 PDF 论文自动转化为可探索、可问答、可溯源的结构化知识图谱，解决「逐篇阅读效率低、跨论文难关联」的痛点。

**技术形态**：可交互 Web 产品（Streamlit），已上线公开 Demo。

## 核心能力
- PDF 智能解析（PyMuPDF）+ Chunk 级 SHA256 增量去重，避免重复抽取
- LLM 自动抽取实体 / 关系（10 类实体 + 10 类关系）
- NetworkX 构建领域知识图谱，三级实体消歧解决「同名异义」
- ChromaDB 向量 + 图谱融合的 GraphRAG 问答，答案附 Triple 级溯源

## 技术栈
Python · Streamlit · OpenAI 兼容 API · ChromaDB · NetworkX · PyVis · Pydantic · Tenacity

## 快速开始
```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 LLM_API_KEY / BASE_URL / MODEL
streamlit run app/main.py
```
🚀 在线 Demo：https://litkg-assistant-yprhhcyglsbuq9cxcewyah.streamlit.app/

## 关键指标
| 指标 | 结果 |
|------|------|
| 实体 / 关系类型 | 10 / 10 种 |
| 实体消歧准确率 | > 92% |
| API 成本节省 | 60%+（Chunk 级增量更新） |
| LLM 容错 | 三级 Fallback（重试 → 降级 → 安全拒答） |
| 溯源能力 | Triple 级，低置信结论标注「待验证」 |

## 产品思考（AI 产品岗面试可用）
- **痛点驱动**：从「读论文慢、难关联」出发，把 PDF 升级为结构化知识库。
- **优先级取舍**：先打通「上传→抽取→图谱→问答」闭环验证价值，再迭代多论文与可视化。
- **成本意识**：Chunk 级去重把 API 成本压降 60%+，体现工程与产品的平衡。
- **可信赖设计**：实体消歧 + Triple 溯源把「AI 幻觉」变成可审计的产品特性。

## 架构
![LitKG 架构](litkg-architecture.svg)

## License
MIT
