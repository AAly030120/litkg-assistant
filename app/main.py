"""
LitKG Assistant V4 — ChatGPT 风格对话 · 知识证据面板 · 浅色图谱
"""
import sys, hashlib, json, logging, traceback, time as _t
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

# ── Windows 编码 ──
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 日志配置（写文件，不污染用户界面） ──
log_dir = PROJECT_ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(log_dir / "app.log", encoding="utf-8"), logging.NullHandler()]
)
app_logger = logging.getLogger("litkg.ui")

# ═══════════════════════════════════════════════
# 启动自检：云端首次启动时自动创建必要目录
# ═══════════════════════════════════════════════
for _dir_name in ["data", "data/papers", "data/chunks", "data/vector_db"]:
    (PROJECT_ROOT / _dir_name).mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="LitKG Assistant", page_icon="📚", layout="wide",
                   initial_sidebar_state="collapsed")

# ═══════════════════════════════════════════════
# 全局 CSS
# ═══════════════════════════════════════════════
st.markdown("""
<style>
:root {
    --primary: #2563EB; --primary-light: #3B82F6; --primary-bg: #EFF6FF;
    --bg: #F8FAFC; --card-bg: #FFFFFF; --text: #1E293B;
    --text-secondary: #64748B; --border: #E2E8F0;
    --success: #10B981; --warning: #F59E0B; --danger: #EF4444;
    --shadow: 0 4px 12px rgba(0,0,0,0.08); --radius: 16px; --spacing: 24px;
}
.main .block-container { padding: 0.5rem 1.5rem 1.5rem 1.5rem; max-width: 1500px; }
.stApp { background: var(--bg); }
footer, #MainMenu { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }

/* ── 顶部全局栏 ── */
.top-bar {
    background: var(--card-bg); border-bottom: 1px solid var(--border);
    padding: 10px 20px; margin: -0.5rem -1.5rem 16px -1.5rem;
    display: flex; align-items: center; gap: 16px;
}
.top-bar-logo { font-size: 20px; font-weight: 800; color: var(--primary); }
.top-bar-search { flex: 1; max-width: 400px; }
.top-bar-actions { display: flex; gap: 8px; font-size: 13px; color: var(--text-secondary); }

/* ── 统计卡片 ── */
.dashboard-title { font-size: 28px; font-weight: 700; color: var(--text); margin-bottom: 2px; }
.dashboard-subtitle { font-size: 15px; color: var(--text-secondary); margin-bottom: 16px; }
.stat-card { background: var(--card-bg); border-radius: var(--radius); padding: 22px 18px;
    text-align: center; box-shadow: var(--shadow); border: 1px solid var(--border);
    transition: transform 0.2s; }
.stat-card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
.stat-card .icon { font-size: 30px; margin-bottom: 6px; }
.stat-card .num { font-size: 38px; font-weight: 800; color: var(--primary); line-height: 1.1; }
.stat-card .label { font-size: 13px; color: var(--text-secondary); font-weight: 500; }

/* ── 上传区 ── */
.upload-zone { background: var(--card-bg); border: 2px dashed var(--primary-light);
    border-radius: var(--radius); text-align: center; height: 160px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    transition: all 0.3s; position: relative; overflow: hidden; }
.upload-zone:hover { border-color: var(--primary); background: #EFF6FF; }
.upload-zone .uz-icon { font-size: 38px; color: var(--primary); }
.upload-zone .uz-text { font-size: 17px; font-weight: 600; color: var(--text); }
.upload-zone .uz-hint { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }

/* ── 论文卡片 ── */
.paper-card { background: var(--card-bg); border-radius: var(--radius); padding: 16px;
    box-shadow: var(--shadow); border: 1px solid var(--border); margin-bottom: 12px;
    transition: transform 0.2s; }
.paper-card:hover { transform: translateY(-2px); }
.paper-card .pc-icon { font-size: 26px; float: left; margin-right: 10px; }
.paper-card .pc-title { font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 3px; }
.paper-card .pc-meta { font-size: 11px; color: var(--text-secondary); margin-bottom: 8px; }
.status-badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; }
.sb-done { background: #D1FAE5; color: #065F46; }
.sb-pending { background: #FEF3C7; color: #92400E; }

/* ── 分段 ── */
.section-title { font-size: 18px; font-weight: 700; color: var(--text);
    margin: 20px 0 10px 0; padding-bottom: 6px; border-bottom: 2px solid var(--primary-light); }

/* ── 活动项 ── */
.activity-item { padding: 8px 12px; background: var(--card-bg); border-radius: 10px; margin-bottom: 6px;
    font-size: 12px; color: var(--text); border: 1px solid var(--border); }

/* ── 热门实体 ── */
.trend-card { background: var(--card-bg); border-radius: var(--radius); padding: 16px;
    box-shadow: var(--shadow); border: 1px solid var(--border); }
.trend-card h4 { font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 10px; }
.trend-item { display: flex; justify-content: space-between; align-items: center;
    padding: 5px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.trend-item:last-child { border-bottom: none; }
.trend-rank { color: var(--primary); font-weight: 700; font-size: 12px; }
.trend-count { color: var(--text-secondary); font-size: 11px; }

/* ── QA 页面 ── */
.chat-container { max-width: 900px; margin: 0 auto; }
.chat-welcome { text-align: center; padding: 40px 20px 20px; }
.chat-welcome h1 { font-size: 32px; font-weight: 700; color: var(--text); }
.chat-welcome p { font-size: 15px; color: var(--text-secondary); }

/* 提问 chips */
.question-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 20px 0 16px; justify-content: center; }
.question-chip { display: inline-block; padding: 8px 16px; background: var(--primary-bg);
    border: 1px solid var(--primary-light); border-radius: 20px; font-size: 13px;
    color: var(--primary); cursor: pointer; transition: all 0.2s; font-weight: 500; }
.question-chip:hover { background: var(--primary); color: white; border-color: var(--primary); }

/* ── 知识证据面板 ── */
.evidence-panel { background: var(--card-bg); border-radius: var(--radius); padding: 16px;
    box-shadow: var(--shadow); border: 1px solid var(--border); }
.evidence-panel h4 { font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 10px;
    padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.evidence-item { padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
.evidence-item:last-child { border-bottom: none; }
.evidence-paper { color: var(--primary); font-weight: 500; }
.evidence-entity { color: var(--text-secondary); }
.evidence-path { padding: 6px; background: var(--bg); border-radius: 8px; margin: 4px 0; font-size: 11px; }
.evidence-stat { display: inline-block; padding: 4px 10px; background: var(--primary-bg);
    border-radius: 12px; font-size: 11px; color: var(--primary); margin: 3px; }

/* ── 图谱 ── */
.graph-control-panel { background: var(--card-bg); border-radius: var(--radius); padding: 14px;
    box-shadow: var(--shadow); border: 1px solid var(--border); }
.graph-control-panel h4 { font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 10px; }

/* ── 按钮 ── */
div.stButton > button { border-radius: 10px; font-weight: 500; transition: all 0.2s; }
div.stButton > button:hover { transform: translateY(-1px); }

/* file_uploader 融入上传区 */
.upload-zone [data-testid="stFileUploader"] { position: absolute; top:0; left:0;
    width:100%; height:100%; opacity:0; }
.upload-zone [data-testid="stFileUploader"] section { width:100%; height:100%; }

/* ── 聊天优化 ── */
[data-testid="stChatMessage"] { border-radius: 14px; }

/* ── 聊天文字大小统一 ── */
[data-testid="stChatMessage"] h1 { font-size: 16px !important; font-weight: 700 !important; }
[data-testid="stChatMessage"] h2 { font-size: 15px !important; font-weight: 700 !important; }
[data-testid="stChatMessage"] h3 { font-size: 15px !important; font-weight: 600 !important; }
[data-testid="stChatMessage"] h4 { font-size: 14px !important; font-weight: 600 !important; }
[data-testid="stChatMessage"] h5, [data-testid="stChatMessage"] h6 { font-size: 14px !important; font-weight: 600 !important; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] td, [data-testid="stChatMessage"] th { font-size: 14px !important; }
[data-testid="stChatMessage"] strong { font-weight: 700 !important; }

/* ── 来源引用样式 ── */
.source-citation { padding: 8px 12px; background: var(--bg); border-left: 3px solid var(--primary);
    border-radius: 0 8px 8px 0; margin: 6px 0; font-size: 13px; }
.source-citation .sc-paper { font-weight: 600; color: var(--primary); }
.source-citation .sc-text { color: var(--text-secondary); }

/* ── Hero 项目介绍卡（简历/Portfolio 呈现优化）── */
.hero-card { background: linear-gradient(135deg, #1E40AF 0%, #2563EB 50%, #3B82F6 100%);
    border-radius: var(--radius); padding: 28px 32px; color: white;
    box-shadow: 0 8px 30px rgba(37,99,235,0.25); margin-bottom: 20px;
    position: relative; overflow: hidden; }
.hero-card::after { content: ""; position: absolute; top:-40px; right:-40px;
    width:180px; height:180px; background:rgba(255,255,255,0.08); border-radius:50%; }
.hero-card .hero-badge { display:inline-block; background:rgba(255,255,255,0.2);
    padding:3px 12px; border-radius:20px; font-size:11px; font-weight:600; letter-spacing:0.5px;
    margin-bottom:10px; backdrop-filter:blur(4px); }
.hero-card h1 { font-size:26px; font-weight:800; margin:0 0 6px 0; line-height:1.2; }
.hero-card p { font-size:14px; opacity:0.9; margin:0 0 16px 0; line-height:1.6; max-width:700px; }
.hero-tags { display:flex; flex-wrap:wrap; gap:6px; }
.hero-tag { background:rgba(255,255,255,0.18); padding:4px 12px; border-radius:20px;
    font-size:11px; font-weight:500; backdrop-filter:blur(4px); border:1px solid rgba(255,255,255,0.25); }

/* ── Demo 模式提示 ── */
.demo-banner { background:#FEF3C7; border:1px solid #F59E0B; border-radius:10px;
    padding:10px 16px; font-size:13px; color:#92400E; margin-bottom:16px; display:flex; align-items:center; gap:8px; }

/* ── About 侧边栏区域 ── */
.about-box { background:var(--card-bg); border:1px solid var(--border); border-radius:12px;
    padding:14px; margin-top:12px; }
.about-box h4 { font-size:13px; font-weight:700; color:var(--text); margin:0 0 8px 0; }
.about-item { font-size:11px; color:var(--text-secondary); padding:3px 0; }
.about-stack { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
.about-chip { background:var(--primary-bg); color:var(--primary); padding:2px 8px;
    border-radius:10px; font-size:10px; font-weight:600; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════
# 全局数据与函数
# ═══════════════════════════════════════════════
@st.cache_resource
def _get_kg():
    from core.kg_store import get_kg_store
    kg = get_kg_store()
    try:
        kg.load_from_json()
    except Exception:
        pass
    return kg

@st.cache_resource
def _get_vs():
    try:
        from core.vector_store import get_vector_store
        return get_vector_store()
    except Exception:
        return None

def _get_stats():
    try:
        kg = _get_kg()
        stats = kg.get_stats()
        pd_dir = PROJECT_ROOT / "data" / "papers"
        n_pdf = sum(1 for _ in pd_dir.glob("*.pdf")) if pd_dir.exists() else 0
        n_chunks = 0
        vs = _get_vs()
        if vs:
            try:
                n_chunks = vs.collection.count()
            except Exception:
                pass
        return {"papers": n_pdf, "entities": stats.get("total_entities", 0),
                "relations": stats.get("total_triples", 0), "chunks": n_chunks}
    except Exception:
        return {"papers": 0, "entities": 0, "relations": 0, "chunks": 0}

def _get_activity():
    if "activity_log" not in st.session_state:
        st.session_state["activity_log"] = []
    return st.session_state["activity_log"]

def _log_activity(msg: str):
    acts = _get_activity()
    acts.insert(0, {"time": _t.strftime("%H:%M"), "msg": msg})
    st.session_state["activity_log"] = acts[:20]

# ═══════════════════════════════════════════════
# Demo 演示数据（预置示例知识图谱，无需 API Key）
# ═══════════════════════════════════════════════
def _load_demo_data():
    """加载预置的 Demo 知识图谱数据，让访客无需 API Key 即可体验完整功能。"""
    from core.models import Entity, Triple, EntityType, RelationType
    kg = _get_kg()
    # 示例论文
    papers_demo = [
        Entity(entity_id="demo_p1", entity_type=EntityType.PAPER, name="Attention Is All You Need",
                properties={"title":"Attention Is All You Need","year":"2017","venue":"NeurIPS","authors":"Vaswani et al."},
                source_paper_id="demo_p1", source_section="Abstract"),
        Entity(entity_id="demo_p2", entity_type=EntityType.PAPER, name="BERT: Pre-training of Deep Bidirectional Transformers",
                properties={"title":"BERT: Pre-training of Deep Bidirectional Transformers","year":"2018","venue":"NAACL","authors":"Devlin et al."},
                source_paper_id="demo_p2", source_section="Introduction"),
        Entity(entity_id="demo_p3", entity_type=EntityType.PAPER, name="Graph Attention Networks",
                properties={"title":"Graph Attention Networks","year":"2018","venue":"ICLR","authors":"Velicovic et al."},
                source_paper_id="demo_p3", source_section="Method"),
    ]
    # 示例实体
    entities_demo = [
        Entity(entity_id="demo_e1", entity_type=EntityType.METHOD, name="Self-Attention",
                properties={"description":"Computes attention weights between all token pairs"},
                source_paper_id="demo_p1", source_section="3.2 Self-Attention"),
        Entity(entity_id="demo_e2", entity_type=EntityType.MODEL, name="Transformer",
                properties={"description":"Architecture based entirely on attention mechanisms","year":"2017"},
                source_paper_id="demo_p1", source_section="3.1 Model Architecture"),
        Entity(entity_id="demo_e3", entity_type=EntityType.METHOD, name="Multi-Head Attention",
                properties={"description":"Runs multiple attention mechanisms in parallel","heads":"8"},
                source_paper_id="demo_p1", source_section="3.2.2 Multi-Head Attention"),
        Entity(entity_id="demo_e4", entity_type=EntityType.DATASET, name="WMT 2014 English-to-German",
                properties={"description":"Machine translation benchmark dataset","size":"4.5M pairs"},
                source_paper_id="demo_p1", source_section="4. Experiments"),
        Entity(entity_id="demo_e5", entity_type=EntityType.METRIC, name="BLEU Score",
                properties={"description":"Bilingual Evaluation Understudy for translation quality"},
                source_paper_id="demo_p1", source_section="4. Results"),
        Entity(entity_id="demo_e6", entity_type=EntityType.MODEL, name="BERT",
                properties={"description":"Bidirectional Encoder Representations from Transformers","layers":"12","hidden":"768"},
                source_paper_id="demo_p2", source_section="3.1 Architecture"),
        Entity(entity_id="demo_e7", entity_type=EntityType.TASK, name="Masked Language Modeling",
                properties={"description":"Predicts masked tokens using bidirectional context"},
                source_paper_id="demo_p2", source_section="3.1 Task 1"),
        Entity(entity_id="demo_e8", entity_type=EntityType.METHOD, name="Positional Encoding",
                properties={"description":"Encodes token position information using sin/cos functions"},
                source_paper_id="demo_p1", source_section="3.5 Positional Encoding"),
        Entity(entity_id="demo_e9", entity_type=EntityType.MODEL, name="GAT",
                properties={"description":"Graph Attention Network for node classification","layers":"2"},
                source_paper_id="demo_p3", source_section="2.1 GAT Layer"),
        Entity(entity_id="demo_e10", entity_type=EntityType.AUTHOR, name="Ashish Vaswani",
                 properties={"affiliation":"Google Brain"}, source_paper_id="demo_p1"),
    ]
    # 示例关系（含溯源字段）
    triples_demo = [
        Triple(triple_id="demo_t1", relation_type=RelationType.PROPOSES,
               source_entity_id="demo_p1", target_entity_id="demo_e2",
               source_entity_name="Attention Is All You Need", target_entity_name="Transformer",
               confidence=0.95, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch3"]),
        Triple(triple_id="demo_t2", relation_type=RelationType.USES,
               source_entity_id="demo_e2", target_entity_id="demo_e1",
               source_entity_name="Transformer", target_entity_name="Self-Attention",
               confidence=0.92, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch3_2"]),
        Triple(triple_id="demo_t3", relation_type=RelationType.BELONGS_TO,
               source_entity_id="demo_e3", target_entity_id="demo_e1",
               source_entity_name="Multi-Head Attention", target_entity_name="Self-Attention",
               confidence=0.88, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch3_2"]),
        Triple(triple_id="demo_t4", relation_type=RelationType.EVALUATED_ON,
               source_entity_id="demo_e2", target_entity_id="demo_e4",
               source_entity_name="Transformer", target_entity_name="WMT 2014 English-to-German",
               confidence=0.97, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch4"]),
        Triple(triple_id="demo_t5", relation_type=RelationType.ACHIEVES,
               source_entity_id="demo_e2", target_entity_id="demo_e5",
               source_entity_name="Transformer", target_entity_name="BLEU Score",
               confidence=0.93, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch4_2"],
               properties={"value": "28.4 BLEU (En-De)"}),
        Triple(triple_id="demo_t6", relation_type=RelationType.EXTENDS,
               source_entity_id="demo_e6", target_entity_id="demo_e2",
               source_entity_name="BERT", target_entity_name="Transformer",
               confidence=0.91, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p2", source_chunk_ids=["demo_p2::ch3"]),
        Triple(triple_id="demo_t7", relation_type=RelationType.PROPOSES,
               source_entity_id="demo_p2", target_entity_id="demo_e7",
               source_entity_name="BERT", target_entity_name="Masked Language Modeling",
               confidence=0.94, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p2", source_chunk_ids=["demo_p2::ch3_1"]),
        Triple(triple_id="demo_t8", relation_type=RelationType.USES,
               source_entity_id="demo_e2", target_entity_id="demo_e8",
               source_entity_name="Transformer", target_entity_name="Positional Encoding",
               confidence=0.89, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch3_5"]),
        Triple(triple_id="demo_t9", relation_type=RelationType.COMPARED_WITH,
               source_entity_id="demo_e2", target_entity_id="demo_e9",
               source_entity_name="Transformer", target_entity_name="GAT",
               confidence=0.65, llm_model="qwen-turbo", prompt_version="v2",
               source_paper_id="demo_p3", source_chunk_ids=["demo_p3::ch6"]),
        Triple(triple_id="demo_t10", relation_type=RelationType.AUTHORED_BY,
                source_entity_id="demo_p1", target_entity_id="demo_e10",
                source_entity_name="Attention Is All You Need", target_entity_name="Ashish Vaswani",
                confidence=0.99, llm_model="qwen-turbo", prompt_version="v2",
                source_paper_id="demo_p1", source_chunk_ids=["demo_p1::ch0"]),
    ]
    # 写入 KG
    for e in papers_demo + entities_demo:
        kg.graph.add_node(e.entity_id, entity_type=e.entity_type.value, name=e.name,
                          properties=e.properties or {}, source_paper_id=e.source_paper_id,
                          source_chunk_ids=e.source_chunk_ids, source_section=e.source_section)
    for t in triples_demo:
        kg.graph.add_edge(t.source_entity_id, t.target_entity_id, relation_type=t.relation_type.value,
                          triple_id=t.triple_id, source_entity_name=t.source_entity_name,
                          target_entity_name=t.target_entity_name, source_paper_id=t.source_paper_id,
                          source_chunk_ids=t.source_chunk_ids, confidence=t.confidence,
                          llm_model=t.llm_model, prompt_version=t.prompt_version,
                          created_at=t.created_at)
    kg._loaded = True
    st.session_state["demo_data_loaded"] = True
    st.session_state["is_demo_mode"] = True

def _render_stat_cards(stats):
    cards = [("📄", stats["papers"], "论文数"), ("🧩", stats["entities"], "实体数"),
             ("🔗", stats["relations"], "关系数"), ("📚", stats["chunks"], "Chunks")]
    cols = st.columns(4)
    for i, (icon, num, label) in enumerate(cards):
        with cols[i]:
            st.markdown(f"""<div class="stat-card"><div class="icon">{icon}</div>
            <div class="num">{num}</div><div class="label">{label}</div></div>""",
                       unsafe_allow_html=True)

def _friendly_error(err_msg: str) -> str:
    """将技术错误转为用户友好提示"""
    msg = str(err_msg).lower()
    if "validation error" in msg or "literal" in msg:
        return "⚠️ 图谱数据格式异常，建议重新处理论文或清理知识图谱。"
    if "api key" in msg or "unauthorized" in msg or "401" in msg:
        return "🔑 API 密钥无效，请检查 .env 文件中的 OPENAI_API_KEY。"
    if "connection" in msg or "timeout" in msg or "network" in msg:
        return "🌐 网络连接异常，请检查网络后重试。"
    if "memory" in msg or "cuda" in msg:
        return "💾 系统资源不足，请稍后重试。"
    return f"⚠️ 查询失败，请稍后重试。\n\n> 技术详情（仅供调试）: {err_msg}"

# ── 侧边栏 ──
with st.sidebar:
    st.markdown('<div style="text-align:center;padding:8px 0;">'
                '<div style="font-size:24px;">📚</div>'
                '<div style="font-size:16px;font-weight:700;color:#1E293B;">LitKG</div>'
                '<div style="font-size:10px;color:#64748B;">知识图谱助手 v4</div></div>',
               unsafe_allow_html=True)
    st.markdown("---")
    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "papers"

    pages = [("papers", "📊", "系统概览"), ("qa", "💬", "智能问答"), ("graph", "🔬", "图谱可视化")]
    for key, icon, label in pages:
        is_cur = st.session_state["current_page"] == key
        if st.button(f"{icon}  {label}", key=f"nav_{key}",
                     type="primary" if is_cur else "secondary", use_container_width=True):
            st.session_state["current_page"] = key
            st.rerun()
    st.markdown("---")
    stats_side = _get_stats()
    st.caption(f"📄 {stats_side['papers']}篇 · 🧩 {stats_side['entities']}实体")
    st.caption(f"🔗 {stats_side['relations']}关系 · 📚 {stats_side['chunks']}Chunk")

    # 最近活动
    st.markdown("**🕐 最近**")
    for act in _get_activity()[:4]:
        st.markdown(f'<div style="font-size:11px;color:#64748B;padding:2px 0;">'
                    f'{act["time"]} {act["msg"]}</div>', unsafe_allow_html=True)

    # ── About 项目信息（简历/Portfolio 呈现）──
    st.markdown("---")
    st.markdown("""<div class="about-box">
    <h4>🏗️ 关于本项目</h4>
    <div class="about-item">📌 <b>定位</b>：AI 驱动的文献知识图谱阅读助手</div>
    <div class="about-item">🎯 <b>核心价值</b>：将非结构化 PDF 论文 → 结构化知识图谱 → 可问答、可探索、可溯源</div>
    <div class="about-item">⚡ <b>开发方式</b>：Vibe-Coding（AI 辅助全栈开发）</div>
    <div class="about-stack">
        <span class="about-chip">Python</span>
        <span class="about-chip">Streamlit</span>
        <span class="about-chip">OpenAI API</span>
        <span class="about-chip">ChromaDB</span>
        <span class="about-chip">NetworkX</span>
        <span class="about-chip">PyVis</span>
        <span class="about-chip">Pydantic</span>
        <span class="about-chip">PyMuPDF</span>
    </div>
    <div class="about-item" style="margin-top:8px;color:#94A3B8;">🔗 <a href="https://github.com/AAly030120/litkg-assistant" target="_blank" style="color:#2563EB;text-decoration:none;">GitHub</a> ·
    <a href="#" style="color:#2563EB;text-decoration:none;">DEPLOY.md</a></div>
    </div>""", unsafe_allow_html=True)

page = st.session_state.get("current_page", "papers")

# ═══════════════════════════════════════════════
# 顶部全局栏
# ═══════════════════════════════════════════════
with st.container():
    c1, c2, c3 = st.columns([2, 4, 2])
    with c1:
        st.markdown('<div class="top-bar-logo">📚 LitKG</div>', unsafe_allow_html=True)
    with c2:
        st.text_input("🔍 全局搜索（实体 / 论文 / 方法）…", key="global_search",
                      label_visibility="collapsed", placeholder="搜索实体、方法、论文…")
    with c3:
        st.markdown(f'<div style="text-align:right;padding-top:8px;font-size:12px;color:#64748B;">'
                    f'论文 {stats_side["papers"]} | 实体 {stats_side["entities"]}</div>',
                    unsafe_allow_html=True)

st.markdown("---")

# ── 全局搜索处理 ──
gs = st.session_state.get("global_search", "").strip()
if gs:
    try:
        kg_now = _get_kg()
        ents = kg_now.get_all_entities()
        matches = [e for e in ents if gs.lower() in e.name.lower() or gs.lower() in e.entity_type.lower()]
        if matches:
            st.markdown("### 🔍 搜索结果")
            st.caption(f"找到 {len(matches)} 个匹配")
            mc = st.columns(min(4, len(matches)))
            for i, m in enumerate(matches[:12]):
                with mc[i % 4]:
                    st.markdown(f'<div class="trend-card"><span style="color:var(--primary);font-weight:600;">'
                                f'{m.entity_type}</span><br>{m.name[:40]}</div>', unsafe_allow_html=True)
        else:
            st.info(f"未找到与「{gs}」相关的实体")
    except Exception as e:
        app_logger.warning(f"全局搜索失败: {e}")

# ═══════════════════════════════════════════════
# PAGE 1: 系统概览
# ═══════════════════════════════════════════════
if page == "papers":
    stats = _get_stats()

    # ═════════════════════════════════════════
    # Hero 项目介绍卡（简历/Portfolio 呈现）
    # ═════════════════════════════════════════
    st.markdown("""
    <div class="hero-card">
        <div class="hero-badge">🚀 VIBE-CODING AI PRODUCT</div>
        <h1>📚 LitKG Assistant</h1>
        <p>基于 LLM + 知识图谱的智能文献阅读助手。上传 PDF 论文，自动抽取实体与关系构建领域知识图谱，
        支持 GraphRAG 融合检索问答、实体消歧、增量更新、三元组溯源——让科研文献从「逐篇阅读」升级为「结构化知识探索」。</p>
        <div class="hero-tags">
            <span class="hero-tag">🤖 LLM 实体抽取</span>
            <span class="hero-tag">🕸️ Knowledge Graph</span>
            <span class="hero-tag">🔍 GraphRAG 融合检索</span>
            <span class="hero-tag">🧹 三级实体消歧</span>
            <span class="hero-tag">📦 Chunk 级增量更新</span>
            <span class="hero-tag">🔗 Triple 溯源</span>
            <span class="hero-tag">🌐 Streamlit Cloud 部署</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Demo 演示模式开关 ──
    demo_mode = st.checkbox("🎮 开启 Demo 演示模式（预置示例数据，无需 API Key）", key="demo_mode")
    if demo_mode:
        st.markdown("""<div class="demo-banner">💡 <b>Demo 模式已开启</b>：
        系统已加载预置的示例知识图谱数据，你可以直接体验「智能问答」和「图谱可视化」功能。
        切换到 💬 智能问答 或 🔬 图谱可视化 页面即可查看效果。</div>""", unsafe_allow_html=True)
        # 注入 Demo 数据到 session_state
        if "demo_data_loaded" not in st.session_state:
            _load_demo_data()

    st.markdown('<div class="dashboard-title">📊 系统概览</div>', unsafe_allow_html=True)
    st.markdown('<div class="dashboard-subtitle">基于知识图谱的文献阅读与科研问答平台</div>',
               unsafe_allow_html=True)
    _render_stat_cards(stats)
    st.markdown("")

    # ── 上传 ──
    st.markdown('<div class="upload-zone"><div class="uz-icon">📄</div>'
               '<div class="uz-text">拖拽 PDF 到此处</div>'
               '<div class="uz-hint">或点击上传 · 支持批量上传</div></div>', unsafe_allow_html=True)
    files = st.file_uploader("上传", type="pdf", accept_multiple_files=True,
                             key="papers_up", label_visibility="collapsed")
    if files:
        try:
            from config.settings import settings as s
            d = s.papers_dir_abs_path
            d.mkdir(parents=True, exist_ok=True)
            saved = skipped = 0
            for f in files:
                buf = f.getvalue()
                h_val = hashlib.md5(buf).hexdigest()
                dup = any(x.exists() and hashlib.md5(x.read_bytes()).hexdigest() == h_val
                          for x in d.glob("*.pdf"))
                if dup:
                    skipped += 1
                else:
                    (d / f.name).write_bytes(buf)
                    saved += 1
                    _log_activity(f"📥 上传 {f.name}")
            if saved:
                st.toast(f"✅ 已保存 {saved} 个文件", icon="✅")
                st.rerun()
            if skipped:
                st.toast(f"⏭ 跳过 {skipped} 个重复", icon="⏭")
        except Exception as e:
            st.error(f"上传失败: {e}")

    # ── 论文列表 ──
    st.markdown('<div class="section-title">📑 论文</div>', unsafe_allow_html=True)
    try:
        from config.settings import settings as s
        d = s.papers_dir_abs_path
        pdfs = sorted(d.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True) if d.exists() else []
        if not pdfs:
            st.info("📭 暂无论文，请上传 PDF。")
        else:
            kg_now = _get_kg()
            all_entities = kg_now.get_all_entities()
            processed_ids = {e.source_paper_id.lower() for e in all_entities if e.entity_type == "Paper"}

            # 筛选
            cs, cy, cst = st.columns([3, 1.2, 1.2])
            with cs:
                search_t = st.text_input("🔍", placeholder="搜索…", key="ps", label_visibility="collapsed")
            with cy:
                yf = st.selectbox("年份", ["全部", "2024+", "2023+", "2022+", "2020+"], key="yf", label_visibility="collapsed")
            with cst:
                sf = st.selectbox("状态", ["全部", "✅ 已处理", "⏳ 待处理"], key="sf", label_visibility="collapsed")

            infos = []
            for pdf in pdfs:
                pid = pdf.stem.lower().replace(" ", "_")[:50]
                is_done = any(pid in s_ for s_ in processed_ids)
                meta = {"filename": pdf.name, "path": str(pdf), "pid": pid,
                        "is_done": is_done, "title": pdf.stem, "year": "", "venue": "", "authors": ""}
                for e in all_entities:
                    if e.entity_type == "Paper" and e.source_paper_id.lower() == pid:
                        meta["title"] = (e.properties or {}).get("title", e.name)
                        meta["year"] = str((e.properties or {}).get("year", ""))
                        meta["venue"] = (e.properties or {}).get("venue", "")
                        break
                if search_t:
                    sl = search_t.lower()
                    if not (sl in meta["title"].lower() or sl in meta["authors"].lower() or
                            sl in meta["venue"].lower()):
                        continue
                if yf != "全部":
                    try:
                        yr = int(meta["year"]) if meta["year"] and meta["year"].isdigit() else 0
                        if yr == 0 or yr < int(yf.replace("+", "")):
                            continue
                    except Exception:
                        pass
                if sf == "✅ 已处理" and not is_done:
                    continue
                if sf == "⏳ 待处理" and is_done:
                    continue
                infos.append(meta)
            if not infos:
                st.info("无匹配论文。")
            else:
                for ri in range(0, len(infos), 3):
                    row = infos[ri:ri + 3]
                    cols = st.columns(3)
                    for idx, pinfo in enumerate(row):
                        with cols[idx]:
                            pid_s = pinfo["pid"][:24]
                            sc = "sb-done" if pinfo["is_done"] else "sb-pending"
                            stt = "✅ 已处理" if pinfo["is_done"] else "⏳ 待处理"
                            ml = f"{pinfo['authors'][:35] or '未知作者'}"
                            if pinfo["year"]:
                                ml += f" · {pinfo['year']}"
                            if pinfo["venue"]:
                                ml += f" · {pinfo['venue'][:18]}"
                            st.markdown(f"""<div class="paper-card"><span class="pc-icon">📄</span>
                            <div class="pc-title">{pinfo['title'][:55]}</div>
                            <div class="pc-meta">{ml[:75]}</div>
                            <span class="status-badge {sc}">{stt}</span></div>""", unsafe_allow_html=True)
                            bc = st.columns(3)
                            with bc[0]:
                                bl = "⚡ 处理" if not pinfo["is_done"] else "🔄 重处理"
                                if st.button(bl, key=f"proc_{pid_s}", use_container_width=True):
                                    try:
                                        from core.kg_store import get_kg_store as gks
                                        from core.vector_store import get_vector_store as gvs
                                        from core.pdf_parser import parse_pdf, chunk_paper
                                        from core.entity_extractor import extract_entities
                                        if pinfo["is_done"]:
                                            kg2 = gks(); kg2.load_from_json()
                                            for e in kg2.get_all_entities():
                                                if e.source_paper_id.lower() == pinfo["pid"]:
                                                    kg2.graph.remove_node(e.entity_id)
                                            kg2.save_to_json()
                                        # ── 快速处理（已移除 API 测试，减少 LLM 往返）──
                                        with st.spinner(f"解析《{pinfo['title'][:30]}》…"):
                                            pmeta = parse_pdf(pinfo["path"])
                                            # 确保 paper_id 与 UI 端 pid 一致（否则卡片状态匹配失败）
                                            pmeta.paper_id = pinfo["pid"]
                                            # 确保论文标题不空：fallback 到文件名
                                            if not pmeta.title:
                                                pmeta.title = pinfo.get("filename", pinfo["pid"])
                                        # ── MVP-2 chunk 级增量更新（说明书 6.8）──
                                        # 重处理模式已清空该论文实体 → 必须全量重抽；
                                        # 其余情况按 chunk_hash 复用内容未变的 chunk，仅对新/变更 chunk 调 LLM。
                                        with st.spinner("分块 & 增量比对…"):
                                            chunks = chunk_paper(pmeta)
                                            force_full = pinfo["is_done"]
                                            existing_hashes = set()
                                            if not force_full:
                                                try:
                                                    existing_hashes = gvs().get_existing_chunk_hashes(pinfo["pid"])
                                                except Exception:
                                                    existing_hashes = set()
                                            if existing_hashes:
                                                new_chunks = [c for c in chunks
                                                              if c.chunk_hash not in existing_hashes]
                                                # 内容未变的 chunk 直接复用已有抽取结果
                                                for c in chunks:
                                                    if c.chunk_hash in existing_hashes:
                                                        c.extraction_status = "success"
                                            else:
                                                new_chunks = chunks
                                            reused_count = len(chunks) - len(new_chunks)

                                        tip = (f"AI 抽取（复用 {reused_count} 块，新增 {len(new_chunks)} 块）…"
                                               if reused_count else "AI 抽取…")
                                        with st.spinner(tip):
                                            r = extract_entities(new_chunks) if new_chunks else None
                                            # 成功时 extract_entities 已就地标记 success；
                                            # failed_chunk_ids 非空表示三级 fallback 全部失败
                                            if r is not None and getattr(r, "failed_chunk_ids", None):
                                                for c in new_chunks:
                                                    c.extraction_status = "failed"

                                        with st.spinner("存入知识图谱…"):
                                            kg3 = gks(); kg3.load_from_json()
                                            if r is not None:
                                                kg3.add_paper_batch(r.entities, r.triples)
                                                kg3.save_to_json()

                                        # 仅新/变更 chunk 重新 embedding；复用的 chunk 不重复计费
                                        try:
                                            vs2 = gvs()
                                            if new_chunks:
                                                vs2.add_chunks(new_chunks, pmeta)
                                            reused_ids = [c.chunk_id for c in chunks
                                                          if c.chunk_hash in existing_hashes]
                                            if reused_ids:
                                                vs2.update_chunk_status(reused_ids, "success")
                                        except Exception as ve:
                                            st.warning(f"向量索引跳过: {ve}")

                                        ent_n = len(r.entities) if r is not None else 0
                                        reuse_tip = f"（增量复用 {reused_count} 块）" if reused_count else ""
                                        _log_activity(f"✅ 处理《{pmeta.title[:30]}》- {ent_n}实体{reuse_tip}")
                                        st.toast(f"《{pmeta.title}》处理完成", icon="✅")
                                        # 清除缓存 → 立即刷新页面
                                        _get_kg.clear(); _get_vs.clear()
                                        st.rerun()
                                    except Exception as ee:
                                        app_logger.error(f"处理失败: {traceback.format_exc()}")
                                        st.error(_friendly_error(str(ee)))
                            with bc[1]:
                                with st.expander("📋"):
                                    st.markdown(f"**标题**: {pinfo['title']}")
                                    st.markdown(f"**作者**: {pinfo['authors'] or '未知'}")
                                    st.caption(f"文件: {pinfo['filename']}")

                                    # ── MVP-2 失败重试面板（说明书 2.4）──
                                    # 展示各 chunk 抽取状态，对 failed chunk 提供手动重试
                                    try:
                                        from core.vector_store import get_vector_store as _gvs2
                                        _chunks = _gvs2().get_chunks_by_paper(pinfo["pid"])
                                    except Exception:
                                        _chunks = []

                                    if _chunks:
                                        _ok = sum(1 for c in _chunks if c["extraction_status"] == "success")
                                        _bad = [c for c in _chunks if c["extraction_status"] == "failed"]
                                        _pending = [c for c in _chunks if c["extraction_status"] == "pending"]
                                        st.caption(
                                            f"抽取进度: {_ok}/{len(_chunks)} 成功"
                                            + (f" · {len(_bad)} 失败" if _bad else "")
                                            + (f" · {len(_pending)} 待处理" if _pending else "")
                                        )
                                        for _c in _bad[:5]:
                                            _rk = f"rt_{pid_s}_{_c['chunk_id']}"
                                            st.markdown(
                                                f'<div style="font-size:12px;color:#B91C1C;'
                                                f'margin-bottom:2px;">⚠ P{_c["page_num"]} · '
                                                f'{_c["preview"][:58]}…</div>',
                                                unsafe_allow_html=True)
                                            if st.button("🔁 重试此块", key=_rk, use_container_width=True):
                                                try:
                                                    from core.models import TextChunk as _TC
                                                    from core.kg_store import get_kg_store as _gks2
                                                    from core.entity_extractor import extract_entities as _ee
                                                    _tc = _TC(
                                                        chunk_id=_c["chunk_id"],
                                                        paper_id=pinfo["pid"],
                                                        content=_c["content"],
                                                        chunk_hash=_c["chunk_hash"],
                                                        page_num=_c["page_num"],
                                                        section_title=_c["section_title"],
                                                        extraction_status="pending",
                                                    )
                                                    _r = _ee([_tc])
                                                    if _r is not None and not _r.failed_chunk_ids:
                                                        _kg = _gks2(); _kg.load_from_json()
                                                        _kg.add_paper_batch(_r.entities, _r.triples)
                                                        _kg.save_to_json()
                                                        _gvs2().update_chunk_status([_c["chunk_id"]], "success")
                                                        _log_activity(
                                                            f"🔁 重试成功: {pinfo['filename']} P{_c['page_num']}")
                                                        st.toast("重试成功", icon="✅")
                                                        _get_kg.clear(); _get_vs.clear()
                                                        st.rerun()
                                                    else:
                                                        st.error("重试仍失败，请检查 API 配额或网络")
                                                except Exception as _re:
                                                    app_logger.error(f"重试失败: {traceback.format_exc()}")
                                                    st.error(_friendly_error(str(_re)))
                            with bc[2]:
                                if st.button("🗑", key=f"del_{pid_s}", use_container_width=True):
                                    st.session_state[f"confirm_del_{pid_s}"] = True
                            if st.session_state.get(f"confirm_del_{pid_s}", False):
                                ae = sum(1 for e in all_entities if e.source_paper_id.lower() == pinfo["pid"])
                                at = sum(1 for t in kg_now.get_all_triples()
                                        if t.get("source_paper_id", "").lower() == pinfo["pid"])
                                st.warning(f"⚠️ 确认删除？将移除 {ae} 实体、{at} 关系")
                                d1, d2 = st.columns(2)
                                with d1:
                                    if st.button("✔ 确认", key=f"yes_{pid_s}"):
                                        for e in all_entities:
                                            if e.source_paper_id.lower() == pinfo["pid"]:
                                                kg_now.graph.remove_node(e.entity_id)
                                        kg_now.save_to_json()
                                        try:
                                            vs = _get_vs()
                                            if vs: vs.delete_by_paper_id(pinfo["pid"])
                                        except: pass
                                        try: Path(pinfo["path"]).unlink()
                                        except: pass
                                        st.session_state[f"confirm_del_{pid_s}"] = False
                                        _log_activity(f"🗑 删除 {pinfo['filename']}")
                                        st.toast("已删除", icon="🗑")
                                        _t.sleep(0.5); st.rerun()
                                with d2:
                                    if st.button("✖ 取消", key=f"cancel_{pid_s}"):
                                        st.session_state[f"confirm_del_{pid_s}"] = False; st.rerun()
    except Exception as e:
        app_logger.error(f"论文列表加载失败: {traceback.format_exc()}")
        st.error(_friendly_error(str(e)))

    # ── 最近活动 ──
    if pdfs:
        st.markdown('<div class="section-title">🕐 最近活动</div>', unsafe_allow_html=True)
        acts = _get_activity()
        if acts:
            for a in acts[:5]:
                st.markdown(f'<div class="activity-item">{a["msg"]} <span style="float:right;color:#94A3B8;">{a["time"]}</span></div>',
                           unsafe_allow_html=True)
        else:
            recent_pdfs = sorted(d.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]
            for rp in recent_pdfs:
                mt = _t.strftime("%m-%d %H:%M", _t.localtime(rp.stat().st_mtime))
                is_pr = any(rp.stem.lower().replace(" ", "_")[:50] in s_ for s_ in processed_ids)
                st.markdown(f'<div class="activity-item">{"✅" if is_pr else "⏳"} {rp.stem[:45]} '
                           f'<span style="float:right;color:#94A3B8;">{mt}</span></div>', unsafe_allow_html=True)

    # ── 热门实体 ──
    if stats["entities"] > 0:
        st.markdown('<div class="section-title">🔥 热门实体</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        entities_all = kg_now.get_all_entities()
        mc, dc = {}, {}
        for e in entities_all:
            if e.entity_type == "Method":
                mc[e.name] = mc.get(e.name, 0) + 1
            elif e.entity_type == "Dataset":
                dc[e.name] = dc.get(e.name, 0) + 1
        with c1:
            st.markdown('<div class="trend-card"><h4>🏷 Top Methods</h4>', unsafe_allow_html=True)
            for i, (n, c) in enumerate(sorted(mc.items(), key=lambda x: x[1], reverse=True)[:5]):
                st.markdown(f'<div class="trend-item"><span class="trend-rank">#{i+1}</span> '
                           f'{n[:28]} <span class="trend-count">{c}</span></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        with c2:
            st.markdown('<div class="trend-card"><h4>📦 Top Datasets</h4>', unsafe_allow_html=True)
            for i, (n, c) in enumerate(sorted(dc.items(), key=lambda x: x[1], reverse=True)[:5]):
                st.markdown(f'<div class="trend-item"><span class="trend-rank">#{i+1}</span> '
                           f'{n[:28]} <span class="trend-count">{c}</span></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════
# PAGE 2: 智能问答（ChatGPT 风格）
# ═══════════════════════════════════════════════
elif page == "qa":
    # 初始化
    if "qa_messages" not in st.session_state:
        st.session_state["qa_messages"] = []
    if "qa_evidence" not in st.session_state:
        st.session_state["qa_evidence"] = None

    # ── 三栏：标题 + 聊天（左宽） + 证据面板（右窄） ──
    st.markdown('<div class="dashboard-title">💬 智能问答</div>', unsafe_allow_html=True)

    main_col, evidence_col = st.columns([5, 2])

    with main_col:
        # ── 聊天动画用容器 ──
        chat_area = st.container()
        with chat_area:
            if not st.session_state["qa_messages"]:
                st.markdown('<div class="chat-welcome"><h1>LitKG Assistant</h1>'
                           '<p>基于知识图谱的科研问答系统</p></div>', unsafe_allow_html=True)

            # 渲染对话历史
            for i, msg in enumerate(st.session_state["qa_messages"]):
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
                    # 助手消息：展示来源引用
                    if msg["role"] == "assistant" and i == len(st.session_state["qa_messages"]) - 1:
                        ev = st.session_state.get("qa_evidence")
                        if ev and ev.get("citations"):
                            with st.expander("📎 来源引用"):
                                for c in ev["citations"]:
                                    ct = getattr(c, "paper_title", "") or ""
                                    cc = getattr(c, "chunk_text", "") or ""
                                    st.markdown(f'<div class="source-citation">'
                                               f'<span class="sc-paper">📄 {ct}</span>'
                                               f'<br><span class="sc-text">{cc[:150]}…</span></div>',
                                               unsafe_allow_html=True)

        # ── 提问 chips ──
        if not st.session_state["qa_messages"]:
            st.markdown('<div class="question-chips">', unsafe_allow_html=True)
            chips = [
                ("📊", "三篇论文提出了什么方法？"),
                ("🧩", "哪些论文使用了 MS-MARCO？"),
                ("⚡", "RAG 与 KG-LLM 的区别？"),
                ("📈", "哪种方法效果最好？"),
            ]
            cc = st.columns(4)
            for i, (icon, q_text) in enumerate(chips):
                with cc[i]:
                    if st.button(f"{icon} {q_text[:14]}…", key=f"chip_{i}",
                                 use_container_width=True):
                        st.session_state["qa_messages"].append({"role": "user", "content": q_text})
                        st.session_state["qa_evidence"] = None
                        st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        # ── 论文选择（连接系统概览） ──
        st.markdown('<div style="font-size:12px;color:#64748B;margin:12px 0 4px;">'
                    '📑 选定论文范围（不选则检索全部）</div>', unsafe_allow_html=True)
        try:
            from config.settings import settings as s_pd
            pd_dir = s_pd.papers_dir_abs_path
            all_pdfs = sorted(pd_dir.glob("*.pdf"), key=lambda x: x.stat().st_mtime, reverse=True) if pd_dir.exists() else []
            paper_options = {}
            for pdf in all_pdfs:
                pid = pdf.stem.lower().replace(" ", "_")[:50]
                paper_options[pdf.stem[:50]] = pid
            if paper_options:
                # 最多显示时用 columns 紧凑布局，超过8个用滚动区
                if len(paper_options) <= 8:
                    selected_titles = st.multiselect(
                        "选定论文", list(paper_options.keys()), key="qa_selected_papers",
                        label_visibility="collapsed", placeholder="点击选择论文（可选）",
                    )
                else:
                    with st.container(height=150):
                        selected_titles = st.multiselect(
                            "选定论文", list(paper_options.keys()), key="qa_selected_papers",
                            label_visibility="collapsed", placeholder="点击选择论文（可选）",
                        )
                selected_pids = [paper_options[t] for t in selected_titles] if selected_titles else []
            else:
                selected_pids = []
        except Exception:
            selected_pids = []

        # ── 检索模式（复刻港大 LightRAG 的双层检索范式）──
        st.markdown('<div style="font-size:12px;color:#64748B;margin:10px 0 4px;">'
                    '🧭 检索模式</div>', unsafe_allow_html=True)
        qa_mode = st.radio(
            "检索模式",
            ["local", "global", "hybrid"],
            key="qa_mode",
            label_visibility="collapsed",
            horizontal=True,
            help="local=局部实体检索(具体事实)；global=全局综述(社区摘要·需先生成)；hybrid=两者融合",
        )
        st.caption({
            "local": "🔍 **局部**：基于实体/向量的精准检索，适合「某方法用什么数据集」等具体事实。",
            "global": "🌐 **全局**：基于社区摘要的综述合成，适合「这些论文主要研究什么」等宏观问题。需先在图谱页生成社区摘要。",
            "hybrid": "🔗 **融合**：同时给出具体事实与全局视角，兼顾细节与主题。",
        }[qa_mode])

        # ── 输入 ──
        q = st.chat_input("请输入您的问题…")
        if q:
            st.session_state["qa_messages"].append({"role": "user", "content": q})
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                placeholder = st.empty()
                placeholder.markdown("💭 *思考中…*")
                try:
                    from core.graphrag import ask as graphrag_ask
                    kg_now = _get_kg()
                    if kg_now.get_stats()["total_entities"] == 0:
                        answer = "图谱为空，请先在「系统概览」页上传并处理论文。"
                        evidence = None
                        placeholder.markdown(answer)
                    else:
                        vs_now = None
                        try: vs_now = _get_vs()
                        except: pass
                        result = graphrag_ask(q, kg=kg_now, vector_store=vs_now,
                                               paper_ids=selected_pids if selected_pids else None,
                                               mode=qa_mode)
                        answer = result.answer

                        # 构建证据数据
                        evidence = {
                            "question_type": result.question_type,
                            "hits_entities": result.hits_entities,
                            "hits_relations": result.hits_relations,
                            "hits_chunks": result.hits_chunks,
                            "citations": getattr(result, "citations", []) or [],
                            "entities": getattr(result, "source_entities", []) or [],
                            "triples": getattr(result, "source_triples", []) or [],
                        }
                        placeholder.markdown(answer)
                        # 底部统计
                        st.caption(f"🎯 {result.question_type} | "
                                  f"命中 {result.hits_entities}实体 "
                                  f"{result.hits_relations}关系 "
                                  f"{result.hits_chunks}Chunk")

                    st.session_state["qa_messages"].append({"role": "assistant", "content": answer})
                    st.session_state["qa_evidence"] = evidence

                except Exception as ee:
                    app_logger.error(f"问答失败: {traceback.format_exc()}")
                    err_display = _friendly_error(str(ee))
                    placeholder.error(err_display)
                    # 展开看详情
                    with st.expander("🔧 技术详情"):
                        st.code(traceback.format_exc())
                    st.session_state["qa_messages"].append({"role": "assistant", "content": err_display})
                    st.session_state["qa_evidence"] = None

            st.rerun()

        # ── 底部操作 ──
        if st.session_state["qa_messages"]:
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("🗑 清空对话", use_container_width=True):
                    st.session_state["qa_messages"] = []
                    st.session_state["qa_evidence"] = None
                    st.rerun()
            with b2:
                md = "\n\n".join([f"**{m['role']}**: {m['content']}" for m in st.session_state["qa_messages"]])
                st.download_button("📥 MD", md, file_name="litkg_chat.md", mime="text/markdown",
                                  use_container_width=True)
            with b3:
                txt = "\n\n".join([f"[{m['role']}] {m['content']}" for m in st.session_state["qa_messages"]])
                st.download_button("📄 TXT", txt, file_name="litkg_chat.txt", mime="text/plain",
                                  use_container_width=True)

    # ── 右侧知识证据面板 ──
    with evidence_col:
        ev = st.session_state.get("qa_evidence")
        if ev is None or not st.session_state["qa_messages"]:
            st.markdown('<div class="evidence-panel"><h4>🔍 知识证据</h4>'
                       '<div class="evidence-item" style="color:#94A3B8;">提出问题后将展示相关论文、实体与知识路径</div>'
                       '</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="evidence-panel"><h4>🔍 知识证据</h4>', unsafe_allow_html=True)

            # 命中统计
            st.markdown(f'<span class="evidence-stat">📊 {ev["hits_entities"]} 实体</span>'
                       f'<span class="evidence-stat">🔗 {ev["hits_relations"]} 关系</span>'
                       f'<span class="evidence-stat">📚 {ev["hits_chunks"]} Chunk</span>',
                       unsafe_allow_html=True)

            # 引用论文
            if ev.get("citations"):
                st.markdown('<div style="margin-top:10px;font-size:13px;font-weight:600;">📄 引用论文</div>',
                           unsafe_allow_html=True)
                for c in ev["citations"]:
                    ct = getattr(c, "paper_title", "") or "未知论文"
                    st.markdown(f'<div class="evidence-item evidence-paper">📑 {ct[:40]}</div>',
                               unsafe_allow_html=True)

            # 涉及实体
            if ev.get("entities"):
                st.markdown('<div style="margin-top:10px;font-size:13px;font-weight:600;">🧩 涉及实体</div>',
                           unsafe_allow_html=True)
                type_order = ["Method", "Model", "Dataset", "Metric", "Task", "Paper"]
                shown_ents = []
                for t in type_order:
                    for e in ev["entities"]:
                        et = getattr(e, "entity_type", "")
                        en = getattr(e, "name", "")
                        if et == t and en not in shown_ents:
                            shown_ents.append(en)
                            st.markdown(f'<div class="evidence-item evidence-entity">[{t}] {en[:35]}</div>',
                                       unsafe_allow_html=True)
                if not shown_ents:
                    other_ents = []
                    for e in ev["entities"][:10]:
                        en = getattr(e, "name", "")
                        et = getattr(e, "entity_type", "")
                        if en not in other_ents:
                            other_ents.append(en)
                            st.markdown(f'<div class="evidence-item evidence-entity">[{et}] {en[:35]}</div>',
                                       unsafe_allow_html=True)

            # 知识路径
            if ev.get("triples"):
                st.markdown('<div style="margin-top:10px;font-size:13px;font-weight:600;">🔗 知识路径</div>',
                           unsafe_allow_html=True)
                for t in ev["triples"][:5]:
                    sn = getattr(t, "source_entity_name", "?")
                    tn = getattr(t, "target_entity_name", "?")
                    rt = getattr(t, "relation_type", "?")
                    st.markdown(f'<div class="evidence-path">{sn[:20]} → <b>{rt}</b> → {tn[:20]}</div>',
                               unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)

# ═══════════════════════════════════════════════
# PAGE 3: 图谱可视化（论文聚类 + 语言切换）
# ═══════════════════════════════════════════════
elif page == "graph":
    st.markdown('<div class="dashboard-title">🔬 知识图谱可视化</div>', unsafe_allow_html=True)

    kg_now = _get_kg()
    stats_full = kg_now.get_stats()
    if stats_full["total_entities"] == 0:
        st.info("📭 图谱为空，请先在「系统概览」页上传并处理论文。")
        st.stop()

    entities = list(kg_now.get_all_entities())
    triples_list = kg_now.get_all_triples()

    # ── 构建论文列表 ──
    paper_entities = [e for e in entities if e.entity_type == "Paper"]
    paper_map = {}  # source_paper_id → paper name
    for pe in paper_entities:
        paper_map[pe.source_paper_id] = pe.name[:40]

    # ── 20/80 分栏 ──
    ctrl_col, graph_col = st.columns([4, 13])

    with ctrl_col:
        st.markdown('<div class="graph-control-panel">', unsafe_allow_html=True)

        # ── 语言切换 ──
        st.markdown("#### 🌐 显示语言")
        lang = st.radio("语言", ["English", "中文"], key="g_lang", label_visibility="collapsed",
                         horizontal=True)
        st.caption(
            "选择语言后图谱节点将统一显示对应语言。"
            "英文模式下节点标签为英文名，中文模式下优先显示中文名。"
            "旧论文建议**重新处理**以获得完整双语支持。"
        )

        # ── 实体类型中英文映射（仅用于 UI 显示标签和图表图例） ──
        ENTITY_TYPE_ZH = {
            "Paper": "论文", "Author": "作者", "Institution": "机构",
            "Method": "方法", "Task": "任务", "Dataset": "数据集",
            "Model": "模型", "Metric": "评价指标", "Result": "实验结果",
            "Domain": "领域",
        }
        TYPE_ORDER = ["Paper", "Author", "Institution", "Method", "Task",
                      "Dataset", "Model", "Metric", "Result", "Domain"]

        # 关系类型中英文映射
        RELATION_ZH = {
            "PROPOSES": "提出", "USES": "使用", "EVALUATED_ON": "评估于",
            "OUTPERFORMS": "优于", "ACHIEVES": "达成", "BELONGS_TO": "属于",
            "EXTENDS": "扩展", "COMPARED_WITH": "对比", "EVALUATED_BY": "被评估",
            "AUTHORED_BY": "作者",
        }

        # ── 论文筛选 ──
        st.markdown("#### 📄 按论文筛选")
        paper_options = [f"{pe.name[:35]}" for pe in paper_entities]
        if paper_options:
            selected_paper_names = st.multiselect(
                "论文", paper_options, key="g_papers",
                label_visibility="collapsed", placeholder="全部论文"
            )
            selected_pids = []
            if selected_paper_names:
                for pe in paper_entities:
                    if pe.name[:35] in selected_paper_names:
                        selected_pids.append(pe.source_paper_id)
            else:
                selected_pids = []
        else:
            selected_pids = []

        # ── 实体类型 ──
        st.markdown("#### 🎛 实体类型")
        # 底层始终存储英文值，通过 format_func 显示中文标签（避免 session_state 缓存冲突）
        all_types_en = sorted(set(e.entity_type for e in entities), key=lambda t: TYPE_ORDER.index(t) if t in TYPE_ORDER else 99)
        if lang == "中文":
            type_format_func = lambda et: ENTITY_TYPE_ZH.get(et, et)
        else:
            type_format_func = lambda et: et
        selected_types = st.multiselect(
            "实体类型",
            all_types_en,
            default=all_types_en,
            format_func=type_format_func,
            key="g_types_en",
            label_visibility="collapsed"
        )
        valid_types_en = selected_types

        st.markdown("#### 🔍 搜索")
        search_term = st.text_input("搜索实体", placeholder="关键词…", key="g_search",
                                    label_visibility="collapsed")

        # 迷你统计
        st.markdown(f'<div style="text-align:center;font-size:11px;color:#64748B;padding:6px;">'
                    f'节点 {len(entities)} · 边 {stats_full["total_triples"]}</div>',
                    unsafe_allow_html=True)

        if st.button("🔄 刷新图谱", use_container_width=True):
            _get_kg.clear(); st.rerun()

        # ── 社区发现（复刻微软 GraphRAG 的层级社区聚类）──
        st.markdown("---")
        st.markdown("#### 🧩 社区与全局综述")
        if st.button("🔬 生成社区摘要", use_container_width=True,
                     help="运行 Louvain 社区发现 + LLM 主题摘要，为全局综述问答提供预计算上下文（一次性离线成本）"):
            with st.spinner("正在社区发现并生成主题摘要（可能需要调用 LLM，请稍候）…"):
                try:
                    report = kg_now.generate_community_reports()
                    n_comm = len(report.get("communities", {}))
                    st.success(f"✅ 社区摘要已生成（{n_comm} 个主题社区）。"
                               "现在可在「智能问答」用 global/hybrid 模式问综述性问题。")
                    _get_kg.clear()
                except Exception as ce:
                    app_logger.error(f"社区摘要生成失败: {traceback.format_exc()}")
                    st.error(f"生成失败：{_friendly_error(str(ce))}")

        color_by_community = st.checkbox(
            "🌈 按社区着色",
            value=False,
            help="开启后节点按社区聚类着色（需先生成社区摘要以写入 community_id）",
        )

        # 路径查询
        st.markdown("---")
        st.markdown("#### 🔎 路径查询")
        all_names = sorted(set(e.name[:45] for e in entities))
        src = st.selectbox("起点", [""] + all_names, key="psrc", label_visibility="collapsed")
        tgt = st.selectbox("终点", [""] + all_names, key="ptgt", label_visibility="collapsed")
        if st.button("查询路径", use_container_width=True):
            if src and tgt:
                src_id = next((e.entity_id for e in entities if e.name[:45] == src), None)
                tgt_id = next((e.entity_id for e in entities if e.name[:45] == tgt), None)
                if src_id and tgt_id:
                    try:
                        import networkx as nx
                        path = nx.shortest_path(kg_now.graph, source=src_id, target=tgt_id)
                        parts = []
                        for i, nid in enumerate(path):
                            node = next((e for e in entities if e.entity_id == nid), None)
                            name = node.name[:30] if node else nid[:8]
                            parts.append(f"**{name}**")
                            if i < len(path) - 1:
                                rel = ""
                                for t in triples_list:
                                    if (t.get("source_entity_id") == nid and
                                            t.get("target_entity_id") == path[i + 1]):
                                        rel = t.get("relation", "")
                                        break
                                if lang == "中文" and rel in RELATION_ZH:
                                    rel_display = RELATION_ZH[rel]
                                else:
                                    rel_display = rel
                                parts.append(f" → *{rel_display}* → ")
                        st.success(f"找到路径（{len(path)-1} 步）")
                        st.markdown("".join(parts))
                    except nx.NetworkXNoPath:
                        st.warning("未找到路径")
                    except Exception as pe:
                        app_logger.warning(f"路径查询失败: {pe}")
                        st.warning("查询失败")
                else:
                    st.warning("未找到实体")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── 右侧：论文聚类图谱 ──
    with graph_col:
        # 按论文筛选（可选）
        if selected_pids:
            pid_set = {p.lower() for p in selected_pids}
            filtered = [e for e in entities
                       if e.entity_type in selected_types
                       and e.source_paper_id.lower() in pid_set]
            # 共享实体：属于多个选定论文的实体
            entity_papers = {}
            for e in filtered:
                pid = e.source_paper_id.lower()
                if pid not in entity_papers:
                    entity_papers[pid] = []
                entity_papers[pid].append(e.entity_id)
            shared_eids = set()
            if len(selected_pids) >= 2:
                all_paper_eids = [set(entity_papers.get(p, set())) for p in pid_set]
                if all_paper_eids:
                    shared_eids = all_paper_eids[0].copy()
                    for s in all_paper_eids[1:]:
                        shared_eids &= s
        else:
            filtered = [e for e in entities if e.entity_type in selected_types]
            shared_eids = set()

        if not filtered:
            st.info("无匹配实体，请调整筛选条件。")
            st.stop()

        import importlib
        if importlib.util.find_spec("pyvis") is None:
            st.info("需要安装 pyvis: `pip install pyvis`")
        else:
            try:
                from pyvis.network import Network

                # ── 浅色学术配色（按实体类型） ──
                COLORS = {
                    "Paper": "#3B82F6", "Author": "#EF4444", "Institution": "#8B5CF6",
                    "Method": "#10B981", "Task": "#F59E0B", "Dataset": "#F97316",
                    "Model": "#8B5CF6", "Metric": "#EC4899", "Result": "#6B7280",
                    "Domain": "#14B8A6",
                }
                # 论文专属颜色（用于论文聚类）
                PAPER_GROUP_COLORS = [
                    "#3B82F6", "#10B981", "#F97316", "#8B5CF6",
                    "#EC4899", "#14B8A6", "#EF4444", "#F59E0B",
                ]
                SHARED_COLOR = "#6366F1"  # 共享节点：靛紫色

                # 社区聚类配色（按 community_id 取色，复刻 GraphRAG 社区视图）
                COMMUNITY_COLORS = [
                    "#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6",
                    "#EC4899", "#14B8A6", "#F97316", "#0EA5E9", "#A855F7",
                    "#84CC16", "#FF6B6B", "#22D3EE", "#E879F9", "#FACC15",
                ]

                SIZES = {
                    "Paper": 40, "Author": 20, "Institution": 18,
                    "Method": 30, "Task": 18, "Dataset": 16,
                    "Model": 25, "Metric": 14, "Result": 12, "Domain": 20,
                }
                SHAPES = {
                    "Paper": "dot", "Author": "star", "Institution": "square",
                    "Method": "diamond", "Task": "triangle", "Dataset": "triangleDown",
                    "Model": "hexagon", "Metric": "dot", "Result": "dot", "Domain": "square",
                }

                net = Network(height="820px", width="100%",
                             bgcolor="#F8FAFC", font_color="#1E293B",
                             cdn_resources="remote")

                # ── 论文聚类：使用更强的引力让同论文节点聚集 ──
                net.barnes_hut(gravity=-8000, central_gravity=0.15,
                              spring_length=200, spring_strength=0.03, damping=0.15)

                # ── 构建论文→颜色映射 ──
                paper_color_map = {}
                if selected_pids:
                    for i, pid in enumerate(selected_pids):
                        paper_color_map[pid.lower()] = PAPER_GROUP_COLORS[i % len(PAPER_GROUP_COLORS)]

                for e in filtered:
                    et = e.entity_type
                    hl = search_term and search_term.lower() in e.name.lower()

                    # ── 节点颜色：社区模式 > 论文聚类模式 > 类型模式 ──
                    if color_by_community:
                        cid = getattr(e, "community_id", -1)
                        if cid is None or cid < 0:
                            color = "#94A3B8"  # 未分配社区：灰
                            size_boost = 1.0
                        else:
                            color = COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]
                            size_boost = 1.1
                    elif selected_pids:
                        pid_lower = e.source_paper_id.lower()
                        if e.entity_id in shared_eids:
                            color = SHARED_COLOR
                            size_boost = 1.6  # 共享节点放大
                        elif pid_lower in paper_color_map:
                            color = paper_color_map[pid_lower]
                            size_boost = 1.0
                        else:
                            color = COLORS.get(et, "#94A3B8")
                            size_boost = 1.0
                    else:
                        color = COLORS.get(et, "#94A3B8")
                        size_boost = 1.0

                    if hl:
                        color = "#E11D48"
                        size_boost = max(size_boost, 1.4)

                    size = int(SIZES.get(et, 18) * size_boost)

                    # ── 显示名称（语言切换） ──
                    props = e.properties or {}
                    name_zh = props.get("name_zh", "").strip()
                    if lang == "中文":
                        # 中文模式：优先 name_zh，fallback 到 e.name
                        label = (name_zh or e.name)[:28]
                    else:
                        # English 模式：始终使用 e.name
                        label = e.name[:28]

                    # 悬浮详情卡 — also respect language
                    if lang == "中文":
                        et_display = ENTITY_TYPE_ZH.get(et, et)
                        if name_zh:
                            title_lines = [f"【{et_display}】{name_zh}", f"（英文: {e.name}）"]
                        else:
                            title_lines = [f"【{et_display}】{e.name}"]
                    else:
                        title_lines = [f"【{et}】{e.name}"]
                        if name_zh:
                            title_lines.append(f"（中文: {name_zh}）")
                    if props.get("year"):
                        title_lines.append(f"📅 {props['year']}")
                    if props.get("venue"):
                        title_lines.append(f"📖 {props['venue'][:40]}")
                    if props.get("abstract"):
                        title_lines.append(f"📝 {props['abstract'][:120]}")
                    # 所属论文
                    sp = e.source_paper_id
                    if sp in paper_map:
                        title_lines.append(f"📄 论文: {paper_map[sp]}")
                    if selected_pids and e.entity_id in shared_eids:
                        title_lines.append("🔗 交叉节点（多论文共有）")
                    rel_count = sum(1 for t in triples_list
                                   if t.get("source_entity_id") == e.entity_id or
                                   t.get("target_entity_id") == e.entity_id)
                    title_lines.append(f"🔗 关联: {rel_count} 条")

                    border_w = 3 if (selected_pids and e.entity_id in shared_eids) else (2 if hl else 1)
                    net.add_node(
                        e.entity_id, label=label,
                        title="\n".join(title_lines),
                        color=color,
                        size=size,
                        shape=SHAPES.get(et, "dot"),
                        borderWidth=border_w,
                        borderWidthSelected=5,
                    )

                for t in triples_list:
                    sid = t.get("source_entity_id", "")
                    oid = t.get("target_entity_id", "")
                    if sid in net.get_nodes() and oid in net.get_nodes():
                        rel = t.get("relation", "")
                        net.add_edge(sid, oid, title=rel,
                                    color="#94A3B8", width=1,
                                    arrows="to")

                html = net.generate_html()
                st.markdown('<div class="graph-iframe-container">', unsafe_allow_html=True)
                st.iframe(srcdoc=html, height=840, scrolling=True)
                st.markdown('</div>', unsafe_allow_html=True)

                # ── 图例（含共享节点说明） ──
                with st.expander("📋 图例"):
                    lc = st.columns(5)
                    display_colors = {t: COLORS[t] for t in valid_types_en if t in COLORS}
                    for i, (etype, ecolor) in enumerate(display_colors.items()):
                        if i < 10:
                            with lc[i % 5]:
                                etype_display = ENTITY_TYPE_ZH.get(etype, etype) if lang == "中文" else etype
                                st.markdown(f'<span style="display:inline-block;width:12px;height:12px;'
                                           f'border-radius:50%;background:{ecolor};margin-right:4px;vertical-align:middle;"></span>'
                                           f'<span style="font-size:12px;color:#64748B;">{etype_display}</span>',
                                           unsafe_allow_html=True)
                    if selected_pids:
                        st.markdown("---")
                        st.markdown("##### 📄 论文专属颜色")
                        pc = st.columns(min(len(selected_pids), 4))
                        for i, pid in enumerate(selected_pids):
                            pname = paper_map.get(pid, pid[:12])
                            with pc[i % 4]:
                                st.markdown(
                                    f'<span style="display:inline-block;width:14px;height:14px;'
                                    f'border-radius:4px;background:{PAPER_GROUP_COLORS[i % len(PAPER_GROUP_COLORS)]};'
                                    f'margin-right:4px;vertical-align:middle;"></span>'
                                    f'<span style="font-size:12px;color:#64748B;">{pname[:20]}</span>',
                                    unsafe_allow_html=True)
                    if shared_eids:
                        st.markdown("---")
                        st.markdown(f'🔗 <span style="color:{SHARED_COLOR};font-weight:600;">共享节点</span>'
                                    f'（{len(shared_eids)} 个）：多篇论文共有的实体，位于交界处',
                                    unsafe_allow_html=True)

                    # ── 社区着色图例 ──
                    if color_by_community:
                        # 统计实际出现的社区
                        comm_ids = sorted({getattr(e, "community_id", -1)
                                           for e in filtered
                                           if getattr(e, "community_id", -1) is not None
                                           and e.community_id >= 0})
                        if comm_ids:
                            st.markdown("---")
                            st.markdown("##### 🌈 社区（Louvain 聚类）")
                            cc = st.columns(min(len(comm_ids), 5))
                            reports = kg_now.get_community_reports().get("communities", {})
                            for i, cid in enumerate(comm_ids):
                                ctitle = reports.get(str(cid), {}).get("title", f"社区 {cid}")
                                with cc[i % 5]:
                                    st.markdown(
                                        f'<span style="display:inline-block;width:12px;height:12px;'
                                        f'border-radius:50%;background:{COMMUNITY_COLORS[cid % len(COMMUNITY_COLORS)]};'
                                        f'margin-right:4px;vertical-align:middle;"></span>'
                                        f'<span style="font-size:11px;color:#64748B;" title="{ctitle}">#{cid}</span>',
                                        unsafe_allow_html=True)
                            st.caption("颜色对应社区编号；悬停查看社区主题标题。")
                        else:
                            st.markdown("---")
                            st.warning("⚠️ 尚未检测到社区。请先点击「🔬 生成社区摘要」写入 community_id。")

                # ── MVP-2 Triple 溯源检视（说明书「调试」要求）──
                with st.expander("🔍 三元组溯源（Debug）"):
                    st.caption(
                        "查看每条关系的抽取依据：来源片段、置信度、抽取模型与 Prompt 版本。"
                        "置信度低于 0.70 的关系在问答中会被标注为「待验证」。"
                    )
                    only_low = st.checkbox("仅看低置信度（< 0.70）", key="g_low_conf")

                    eid2name = {e.entity_id: e.name for e in entities}
                    visible_nodes = set(net.get_nodes())
                    shown = 0
                    low_total = 0

                    for t in triples_list:
                        try:
                            conf = float(t.get("confidence", 1.0) or 1.0)
                        except (TypeError, ValueError):
                            conf = 1.0
                        sid = t.get("source_entity_id", "")
                        oid = t.get("target_entity_id", "")
                        if sid not in visible_nodes or oid not in visible_nodes:
                            continue
                        if conf < 0.70:
                            low_total += 1
                        if only_low and conf >= 0.70:
                            continue
                        if shown >= 30:
                            st.caption("… 仅显示前 30 条，可用上方筛选缩小范围")
                            break

                        sn = t.get("source_entity_name") or eid2name.get(sid, str(sid)[:8])
                        tn = t.get("target_entity_name") or eid2name.get(oid, str(oid)[:8])
                        rel = t.get("relation", "")
                        rel_disp = RELATION_ZH.get(rel, rel) if lang == "中文" else rel

                        if conf >= 0.85:
                            badge_bg, badge_fg = "#DCFCE7", "#166534"
                        elif conf >= 0.70:
                            badge_bg, badge_fg = "#FEF9C3", "#854D0E"
                        else:
                            badge_bg, badge_fg = "#FEE2E2", "#991B1B"

                        st.markdown(
                            f'<div style="font-size:13px;padding:5px 0;border-bottom:1px solid #F1F5F9;">'
                            f'{str(sn)[:22]} → <b>{rel_disp}</b> → {str(tn)[:22]}'
                            f' <span style="background:{badge_bg};color:{badge_fg};'
                            f'border-radius:6px;padding:1px 6px;font-size:11px;margin-left:4px;">'
                            f'置信度 {conf:.2f}</span>'
                            f'{" ⚠ 待验证" if conf < 0.70 else ""}</div>',
                            unsafe_allow_html=True)

                        chunks = t.get("source_chunk_ids", []) or []
                        paper_t = paper_map.get(t.get("source_paper_id", ""), "")
                        detail = []
                        if paper_t:
                            detail.append(f"📄 {paper_t}")
                        if chunks:
                            detail.append(
                                f"📎 来源片段 {len(chunks)} 处："
                                f"{', '.join(str(c)[:12] for c in chunks[:3])}"
                            )
                        else:
                            detail.append("📎 来源片段：未记录")
                        if t.get("llm_model"):
                            detail.append(f"🤖 {t['llm_model']}")
                        if t.get("prompt_version"):
                            detail.append(f"🏷 Prompt {t['prompt_version']}")
                        if t.get("created_at"):
                            detail.append(f"🕐 {str(t['created_at'])[:19]}")
                        st.caption(" ｜ ".join(detail))
                        shown += 1

                    if shown == 0:
                        st.caption("当前筛选条件下没有可显示的关系。")
                    if low_total:
                        st.caption(
                            f"⚠ 共 {low_total} 条低置信度关系，问答中会标注「待验证」，"
                            f"可考虑对相关论文重新抽取。"
                        )

            except Exception as e:
                app_logger.error(f"图谱渲染失败: {traceback.format_exc()}")
                st.error(_friendly_error(str(e)))
                with st.expander("🔧 详情"):
                    st.code(traceback.format_exc())
