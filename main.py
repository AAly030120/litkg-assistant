"""
LitKG Assistant — MVP-0 主入口
单论文闭环：上传 PDF → 解析 → LLM 抽取 → 构图谱 → 问答循环

用法：
    python main.py                          # 交互模式：输入 PDF 路径
    python main.py --pdf path/to/paper.pdf  # 直接指定 PDF 文件
"""

import argparse
import logging
import sys
from pathlib import Path

# 确保 litkg-assistant 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import settings
from core.pdf_parser import parse_pdf, chunk_paper
from core.entity_extractor import extract_entities
from core.kg_store import KGStore
from core.graphrag import ask

# ============================================================
# 日志配置
# ============================================================

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ============================================================
# 启动校验
# ============================================================

def _validate_config() -> bool:
    """校验启动配置"""
    errors = settings.validate()
    if errors:
        print("\n❌ 配置错误：")
        for err in errors:
            print(f"  - {err}")
        print("\n请编辑 .env 文件后再运行。参考 .env.example。")
        return False

    # 打印配置诊断信息
    masked_key = settings.LLM_API_KEY
    if masked_key and len(masked_key) > 8:
        masked_key = masked_key[:4] + "****" + masked_key[-4:]
    print(f"\n  📋 配置诊断:")
    print(f"     LLM_BASE_URL  : {settings.LLM_BASE_URL}")
    print(f"     LLM_MODEL_NAME: {settings.LLM_MODEL_NAME}")
    print(f"     LLM_API_KEY   : {masked_key if settings.LLM_API_KEY else '(空!)'}")
    return True


# ============================================================
# 处理单篇论文
# ============================================================

def _resolve_pdf_path(raw_path: str) -> Path | None:
    """
    解析用户输入的路径：支持直接 PDF 文件路径或包含 PDF 的文件夹路径。
    如果是文件夹，自动找到第一个 PDF 文件。
    """
    path = Path(raw_path.strip().strip("'\""))
    if not path.exists():
        print(f"❌ 路径不存在: {path}")
        return None

    if path.is_file():
        if path.suffix.lower() != ".pdf":
            print(f"❌ 不是 PDF 文件: {path.name}")
            return None
        return path.resolve()

    # 是文件夹：扫描 PDF 文件
    pdf_files = sorted(path.glob("*.pdf"))
    if not pdf_files:
        print(f"❌ 文件夹中没有找到 PDF 文件: {path}")
        return None

    if len(pdf_files) == 1:
        print(f"📂 检测到文件夹，自动选择 PDF: {pdf_files[0].name}")
        return pdf_files[0].resolve()

    # 多个 PDF：列出让用户选
    print(f"\n📂 文件夹中有 {len(pdf_files)} 个 PDF 文件:")
    for i, f in enumerate(pdf_files, 1):
        print(f"  [{i}] {f.name}")
    while True:
        try:
            choice = input(f"  请选择序号 (1-{len(pdf_files)}): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(pdf_files):
                return pdf_files[idx].resolve()
        except (ValueError, EOFError):
            pass
        print("  输入无效，请重新选择。")


def process_paper(pdf_path: str, kg: KGStore) -> bool:
    """
    处理一篇论文：解析 → 抽取 → 存图。

    返回: True 表示成功，False 表示失败
    """
    resolved = _resolve_pdf_path(pdf_path)
    if resolved is None:
        return False

    pdf_path = resolved

    print(f"\n{'='*60}")
    print(f"📄 正在处理: {pdf_path.name}")
    print(f"{'='*60}")

    # --- Step 1: PDF 解析 ---
    print("\n[1/3] 解析 PDF...")
    try:
        paper_meta = parse_pdf(str(pdf_path))
        print(f"  ✅ 解析完成: {paper_meta.total_pages} 页")
        print(f"  📌 标题: {paper_meta.title or '(未识别)'}")
        print(f"  📑 章节数: {len(paper_meta.sections)}")
    except Exception as e:
        print(f"  ❌ PDF 解析失败: {e}")
        logger.error(f"PDF 解析失败: {e}", exc_info=True)
        return False

    # --- Step 1.5: 分块 ---
    chunks = chunk_paper(paper_meta)
    print(f"  🧩 分块: {len(chunks)} 个 chunk")
    if not chunks:
        print("  ❌ 无文本内容")
        return False

    # --- Step 2: 抽取实体和关系 ---
    print("\n[2/3] 调用 LLM 抽取实体和关系...")
    print(f"  🤖 模型: {settings.LLM_MODEL_NAME}")
    print(f"  ⏳ 请等待（通常需要 10~30 秒）...")

    try:
        result = extract_entities(chunks)
        latency = result.metadata.get("latency_ms", 0)
        retry_level = result.metadata.get("retry_level", 0)
        print(f"  ✅ 抽取完成 (耗时 {latency/1000:.1f}s, 重试级别 L{retry_level})")
        print(f"  📊 实体: {len(result.entities)} 个")
        print(f"  🔗 关系: {len(result.triples)} 个")

        # 打印实体类型分布
        type_counts = {}
        for e in result.entities:
            type_counts[e.entity_type] = type_counts.get(e.entity_type, 0) + 1
        for etype, count in type_counts.items():
            print(f"     - {etype}: {count}")
    except RuntimeError as e:
        # API 连接等致命错误，不再继续
        print(f"\n  ❌ 抽取因致命错误中止: {e}")
        logger.error(f"LLM 抽取致命错误: {e}")
        return False
    except Exception as e:
        print(f"  ❌ 抽取失败: {e}")
        logger.error(f"LLM 抽取失败: {e}", exc_info=True)
        return False

    if not result.entities:
        print("  ⚠️ 未抽取到任何实体，跳过入库")
        return False

    # --- Step 3: 存入 KG ---
    print("\n[3/3] 存入知识图谱...")
    try:
        kg.add_paper_batch(result.entities, result.triples)
        kg.save_to_json()
        print(f"  ✅ 已存入 {len(result.entities)} 个实体, {len(result.triples)} 个关系")
    except Exception as e:
        print(f"  ❌ 存入 KG 失败: {e}")
        logger.error(f"KG 存储失败: {e}", exc_info=True)
        return False

    # --- 打印 KG 统计 ---
    stats = kg.get_stats()
    print(f"\n📊 知识图谱当前状态:")
    print(f"  实体总数: {stats['total_entities']}")
    print(f"  关系总数: {stats['total_triples']}")

    return True


# ============================================================
# 问答循环
# ============================================================

def qa_loop(kg: KGStore):
    """命令行问答循环"""
    print(f"\n{'='*60}")
    print(f"💬 问答模式 — 输入问题 (输入 exit 退出)")
    print(f"{'='*60}")

    stats = kg.get_stats()
    if stats["total_entities"] == 0:
        print("\n⚠️ 知识图谱为空，请先上传论文。")
        return

    while True:
        try:
            question = input("\n🔍 问题: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if not question:
            continue
        if question.lower() in ("exit", "quit", "q"):
            print("👋 再见！")
            break

        # 本地回退：如果问的是图谱统计
        if "统计" in question and ("实体" in question or "关系" in question):
            stats = kg.get_stats()
            print(f"\n📊 当前图谱统计:")
            print(f"  实体: {stats['total_entities']}")
            print(f"  关系: {stats['total_triples']}")
            print(f"  类型分布: {stats['entity_type_distribution']}")
            continue

        print("  ⏳ 检索中...")
        try:
            answer = ask(question, kg)

            print(f"\n{'─'*50}")
            print(answer.answer)
            print(f"{'─'*50}")

            # 展示来源
            if answer.source_entities:
                print(f"\n📎 来源实体 ({len(answer.source_entities)} 个):")
                for e in answer.source_entities[:5]:
                    print(f"  [{e.entity_type}] {e.name}")
                if len(answer.source_entities) > 5:
                    print(f"  ... 还有 {len(answer.source_entities) - 5} 个")
            if answer.source_triples:
                print(f"\n📎 来源关系 ({len(answer.source_triples)} 条):")
                for t in answer.source_triples[:5]:
                    print(f"  {t.source_entity_name} --[{t.relation_type}]--> {t.target_entity_name}")

            print(f"\n⏱️ 耗时: {answer.latency_ms/1000:.1f}s")

        except Exception as e:
            print(f"\n❌ 问答出错: {e}")
            logger.error(f"问答失败: {e}", exc_info=True)


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="LitKG Assistant — MVP-0 文献知识图谱助手"
    )
    parser.add_argument(
        "--pdf", "-p",
        type=str,
        help="论文 PDF 文件路径（可选，不指定则进入交互模式）",
    )
    args = parser.parse_args()

    # 校验配置
    if not _validate_config():
        sys.exit(1)

    print("=" * 60)
    print("  📚 LitKG Assistant — MVP-0 文献知识图谱助手")
    print("=" * 60)
    print(f"  LLM 模型: {settings.LLM_MODEL_NAME}")
    print(f"  KG 文件:  {settings.kg_json_abs_path}")

    # 初始化 KG
    kg = KGStore()

    if args.pdf:
        # 指定了 PDF 文件
        success = process_paper(args.pdf, kg)
        if not success:
            sys.exit(1)
    else:
        # 交互模式：提示输入 PDF 路径
        try:
            pdf_input = input("\n📎 请输入论文 PDF 文件路径: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            return

        if not pdf_input:
            print("❌ 未输入文件路径")
            return

        success = process_paper(pdf_input, kg)
        if not success:
            sys.exit(1)

    # 进入问答循环
    qa_loop(kg)


if __name__ == "__main__":
    main()
