"""
LitKG Assistant — PDF 解析模块
基于 PyMuPDF (fitz)，支持页眉页脚过滤、双栏排版处理、章节识别、文本分块。
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import List, Tuple

import fitz  # PyMuPDF

from config.settings import settings
from core.models import PaperMeta, Section, TextBlock, TextChunk

logger = logging.getLogger(__name__)


# ============================================================
# 章节标题识别正则
# ============================================================

# 匹配常见章节标题模式
# 例如: "1. Introduction", "2. Related Work", "3.1 Model Architecture"
SECTION_PATTERNS = [
    re.compile(r"^(?:\d+\.)+\s+[A-Z][a-zA-Z\s\-]+$"),     # "1. Introduction" / "3.1.2 Model"
    re.compile(r"^(?:[IVX]+)\.\s+[A-Z][a-zA-Z\s\-]+$"),    # "IV. Experiments"
    re.compile(r"^(?:Abstract|摘要)$", re.IGNORECASE),
    re.compile(r"^(?:Introduction|Related Work|Method(?:ology)?|Experiment|"
               r"Result|Discussion|Conclusion|References?|"
               r"Acknowledgments?|Appendix)$", re.IGNORECASE),
]


def _is_section_heading(line: str) -> bool:
    """判断一行文本是否为章节标题"""
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    # 全文大写且长度合适（如 "ABSTRACT"）
    if stripped.isupper() and 5 <= len(stripped) <= 40:
        return True
    return any(pat.match(stripped) for pat in SECTION_PATTERNS)


# ============================================================
# 页眉页脚过滤
# ============================================================

def _should_skip_block(block: TextBlock, page_height: float,
                       header_ratio: float = None,
                       footer_ratio: float = None) -> bool:
    """
    根据 y 坐标判断是否应该跳过该文本块（页眉/页脚区域）。

    参数:
        block: 文本块
        page_height: 页面高度
        header_ratio: 页眉区域比例（顶部 0~header_ratio）
        footer_ratio: 页脚区域比例（footer_ratio~1.0）
    """
    h_ratio = header_ratio or settings.HEADER_RATIO
    f_ratio = footer_ratio or settings.FOOTER_RATIO

    # y0 是文本块顶部，值越小越靠近页面顶部
    if block.y1 < page_height * h_ratio:
        return True  # 在页眉区域
    if block.y0 > page_height * f_ratio:
        return True  # 在页脚区域
    return False


# ============================================================
# 双栏排版处理
# ============================================================

def _sort_blocks_reading_order(blocks: List[TextBlock],
                                page_center_x: float) -> List[TextBlock]:
    """
    将页面文本块按阅读顺序排序：
    - 如果页面是双栏，按左栏从上到下 → 右栏从上到下排列。
    - 判断标准：如果有文本块跨越页面中心线两侧，视为单栏。
    """
    # 区分左栏和右栏
    left_col = []
    right_col = []
    cross_col = []

    for blk in blocks:
        if blk.x0 < page_center_x and blk.x1 < page_center_x:
            left_col.append(blk)
        elif blk.x0 >= page_center_x:
            right_col.append(blk)
        else:
            # 跨栏文本块（如通栏标题、图表）
            cross_col.append(blk)

    # 如果左栏或右栏少于 3 个块，视为单栏布局（直接按 y 排序）
    if len(left_col) < 3 or len(right_col) < 3:
        return sorted(blocks, key=lambda b: (b.y0, b.x0))

    # 双栏：左栏按 y0 排序 → 右栏按 y0 排序
    # 但跨栏块需要插入到正确的位置（按 y 坐标插入）
    left_col.sort(key=lambda b: b.y0)
    right_col.sort(key=lambda b: b.y0)
    cross_col.sort(key=lambda b: b.y0)

    # 合并：按 y 坐标交错插入跨栏文本
    result = []
    li = ri = ci = 0
    while li < len(left_col) or ri < len(right_col) or ci < len(cross_col):
        # 获取下一个应该处理的块
        candidates = []
        if ci < len(cross_col):
            candidates.append(("cross", cross_col[ci]))
        if li < len(left_col):
            candidates.append(("left", left_col[li]))
        if ri < len(right_col):
            candidates.append(("right", right_col[ri]))

        candidates.sort(key=lambda x: x[1].y0)
        next_type, _ = candidates[0]

        if next_type == "cross":
            result.append(cross_col[ci])
            ci += 1
        elif next_type == "left":
            result.append(left_col[li])
            li += 1
        else:
            result.append(right_col[ri])
            ri += 1

    return result


# ============================================================
# PDF 文本提取
# ============================================================

def _extract_page_blocks(page: fitz.Page, page_num: int) -> List[TextBlock]:
    """
    从单页提取所有文本块（含位置信息）。
    使用 get_text("blocks") 获取带坐标的文本块。
    """
    blocks = []
    raw_blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, ...)

    for raw in raw_blocks:
        if len(raw) < 5:
            continue
        text = raw[4].strip() if isinstance(raw[4], str) else ""
        if not text or len(text) < 5:
            continue

        # 跳过纯数字行（可能是页码）
        if re.match(r"^\d+$", text):
            continue

        try:
            block = TextBlock(
                text=text,
                x0=float(raw[0]),
                y0=float(raw[1]),
                x1=float(raw[2]),
                y1=float(raw[3]),
                block_no=int(raw[5]) if len(raw) > 5 else 0,
                page_num=page_num,
            )
            blocks.append(block)
        except (ValueError, IndexError):
            continue

    return blocks


# ============================================================
# 主解析函数
# ============================================================

def parse_pdf(file_path: str | Path) -> PaperMeta:
    """
    解析 PDF 文件，提取全文文本、元信息和章节。

    参数:
        file_path: PDF 文件路径

    返回:
        PaperMeta 对象，包含论文标题、摘要、全文、章节等
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"PDF 文件不存在: {file_path}")

    logger.info(f"正在解析 PDF: {file_path.name}")
    doc = fitz.open(str(file_path))

    meta = PaperMeta()
    meta.total_pages = len(doc)

    # 提取 PDF 元数据中的标题
    pdf_title = doc.metadata.get("title", "")
    if pdf_title:
        meta.title = pdf_title.strip()

    all_blocks: List[TextBlock] = []
    page_text_map: dict[int, str] = {}  # page_num -> 该页文本

    for page_num, page in enumerate(doc, start=1):
        page_rect = page.rect
        page_width = page_rect.width
        page_height = page_rect.height
        page_center_x = page_width / 2

        # 提取文本块
        blocks = _extract_page_blocks(page, page_num)

        # 过滤页眉页脚
        blocks = [b for b in blocks
                  if not _should_skip_block(b, page_height)]

        # 双栏阅读顺序排序
        blocks = _sort_blocks_reading_order(blocks, page_center_x)

        all_blocks.extend(blocks)

        # 按页拼接文本
        page_text = "\n".join(b.text for b in blocks)
        page_text_map[page_num] = page_text

    doc.close()

    # 拼接全文
    meta.full_text = "\n\n".join(page_text_map.values())

    # 识别章节
    meta.sections = _identify_sections(all_blocks, page_text_map)

    # 提取摘要（通常在 Abstract 节之前或第一节中）
    meta.abstract = _extract_abstract(meta)

    # 提取参考文献
    meta = _extract_references(meta)

    logger.info(
        f"PDF 解析完成: {meta.total_pages} 页, "
        f"{len(meta.sections)} 个章节, "
        f"全文 {len(meta.full_text)} 字符"
    )
    return meta


def _identify_sections(blocks: List[TextBlock],
                       page_text_map: dict[int, str]) -> List[Section]:
    """
    基于章节标题启发式切分全文为 Section 列表。
    """
    sections: List[Section] = []
    current_section = Section(heading="Abstract", content="")

    # 简化处理：按块级别切分
    all_text = []
    for block in blocks:
        all_text.extend(block.text.split("\n"))

    for line in all_text:
        stripped = line.strip()
        if not stripped:
            continue

        if _is_section_heading(stripped):
            # 保存上一节
            if current_section.content.strip():
                sections.append(current_section)
            current_section = Section(heading=stripped, content="")
        else:
            if current_section.content:
                current_section.content += "\n" + stripped
            else:
                current_section.content = stripped

    # 保存最后一节
    if current_section.content.strip():
        sections.append(current_section)

    return sections


def _extract_abstract(meta: PaperMeta) -> str:
    """
    从全文或第一节中提取摘要文本。
    策略：找到 "Abstract" 章节，其内容即为摘要；
    如果找不到，取全文前 1500 字符作为摘要。
    """
    # 先尝试从章节中找
    for section in meta.sections:
        if section.heading.lower().startswith("abstract"):
            return section.content[:2000]

    # 回退：取全文前一段
    first_para = meta.full_text.split("\n\n")[0] if meta.full_text else ""
    if len(first_para) > 200:
        return first_para[:1500]
    return first_para[:1500]


def _extract_references(meta: PaperMeta) -> PaperMeta:
    """
    从全文中提取参考文献部分。
    找到 References 章节之后的内容即为参考文献。
    同时从全文中移除参考文献（避免 LLM 抽取时处理冗余引用）。
    """
    ref_pattern = re.compile(
        r"(?:^|\n)(?:References?|REFERENCES|Bibliography|BIBLIOGRAPHY)\s*\n",
        re.IGNORECASE
    )
    match = ref_pattern.search(meta.full_text)
    if match:
        meta.references_raw = meta.full_text[match.end():]
        meta.full_text = meta.full_text[:match.start()]

    return meta


# ============================================================
# 文本分块
# ============================================================

def chunk_paper(meta: PaperMeta,
                chunk_size: int = None,
                overlap: int = None) -> List[TextChunk]:
    """
    将 PaperMeta 的全文按固定大小分块。
    每个 chunk 包含完整的元信息（页码、字符位置、SHA256 哈希）。

    参数:
        meta: 解析后的论文元信息
        chunk_size: 每个 chunk 的字符数
        overlap: 相邻 chunk 的重叠字符数

    返回:
        TextChunk 列表
    """
    cs = chunk_size or settings.CHUNK_SIZE
    ol = overlap or settings.CHUNK_OVERLAP

    text = meta.full_text
    text_len = len(text)

    if text_len == 0:
        logger.warning(f"论文 {meta.paper_id} 无文本内容")
        return []

    chunks: List[TextChunk] = []
    pos = 0
    chunk_idx = 0

    # 构建字符位置 → 页码的映射
    char_to_page = _build_char_page_map(meta)

    while pos < text_len:
        end = min(pos + cs, text_len)
        chunk_text = text[pos:end]

        if not chunk_text.strip():
            pos = end
            continue

        # 如果 chunk 在段落中间截断，尽量调整到最近的段落边界
        if end < text_len and chunk_text.rfind("\n\n") > cs // 2:
            adjust_pos = chunk_text.rfind("\n\n")
            end = pos + adjust_pos
            chunk_text = text[pos:end]

        # 计算 SHA256
        chunk_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()

        # 确定页码（基于字符位置）
        page_num = _get_page_for_char(char_to_page, pos)

        # 确定所属章节
        section_title = _get_section_for_pos(meta.sections, pos, end)

        chunk = TextChunk(
            paper_id=meta.paper_id,
            content=chunk_text,
            chunk_hash=chunk_hash,
            page_num=page_num,
            char_start=pos,
            char_end=end,
            section_title=section_title,
        )
        chunks.append(chunk)

        # 如果已经到达文本末尾，退出循环
        if end >= text_len:
            break

        # 移动到下一个 chunk 起始位置（带重叠）
        pos = max(pos + 1, end - ol)  # 确保 pos 严格递增
        chunk_idx += 1

    logger.info(f"分块完成: {len(chunks)} 个 chunk (chunk_size={cs}, overlap={ol})")
    return chunks


def _build_char_page_map(meta: PaperMeta) -> List[Tuple[int, int]]:
    """
    构建字符位置到页码的映射。
    返回 [(char_start, page_num), ...] 列表。
    简化实现：按总字符数 / 总页数 估算每页字符数。
    """
    if meta.total_pages <= 1:
        return [(0, 1)]

    chars_per_page = len(meta.full_text) / meta.total_pages
    mapping = []
    for p in range(meta.total_pages):
        start = int(p * chars_per_page)
        mapping.append((start, p + 1))
    return mapping


def _get_page_for_char(char_page_map: List[Tuple[int, int]], pos: int) -> int:
    """给定字符位置，返回页码"""
    page = 1
    for start, p in char_page_map:
        if pos >= start:
            page = p
        else:
            break
    return page


def _get_section_for_pos(sections: List[Section],
                         char_start: int,
                         char_end: int) -> str:
    """
    根据字符位置确定所属章节标题。
    简化实现：遍历章节，累计内容长度判断。
    """
    accumulated = 0
    for section in sections:
        section_len = len(section.content) + len(section.heading) + 2
        # 如果 chunk 的起始位置在该节范围内
        if accumulated <= char_start < accumulated + section_len:
            return section.heading
        accumulated += section_len

    return ""
