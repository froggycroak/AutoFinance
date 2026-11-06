# -*- coding: utf-8 -*-
"""把 xlsx 画成 PDF。纸张固定为横向 A4，缩放到一页且不超过 100%。

几何是对照本机 Excel（ExportAsFixedFormat）量出来的，不是屏幕上的列宽像素公式：

- 列宽（点）= 列宽字符数 × 5.76 × 打印缩放
  5.76 = 等线/宋体 11pt 的最大数字宽度 8px × 72/100
- 行高（点）= 行高 × 0.903 × 打印缩放
- 缩放到页：按可打印区域计算比例，再向下取整到整数百分比，且不超过 100%
- 单元格文字内边距约 3 点 × 缩放（96dpi 下的 4px）

只覆盖这两份劳务费表用到的子集：A4、宋体、合并单元格、细/中边框、
自动换行、会计格式、简单 SUM。
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path

import fitz
from lxml import etree
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl import load_workbook

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Excel 导出的 A4，和 ISO 的 595.28×841.89 差一截，以 PDF 实测为准。
A4 = (595.2, 841.68)
COL_PT = 5.76
ROW_FACTOR = 0.903
# 100% 缩放下的左右内边距，等于 96dpi 的 4px。
PAD_PT = 3.0

THIN = 1.0
MEDIUM = 2.0
BORDER_W = {
    "hair": 0.5,
    "dotted": 1.0,
    "dashed": 1.0,
    "thin": THIN,
    "mediumDashed": MEDIUM,
    "medium": MEDIUM,
    "thick": 3.0,
    "double": MEDIUM,
}

SIMSUN = r"C:\Windows\Fonts\simsun.ttc"


@dataclass
class PageSetup:
    landscape: bool
    fit: bool
    fit_w: int | None  # None = 不限制
    fit_h: int | None
    zoom: float  # fit 关闭时使用
    margin_l: float
    margin_r: float
    margin_t: float
    margin_b: float


def _sheet_targets(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        wb = etree.fromstring(z.read("xl/workbook.xml"))
        rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to = {rel.get("Id"): rel.get("Target") for rel in rels}
    out = {}
    for sh in wb.find("m:sheets", NS):
        target = rid_to[sh.get(REL + "id")]
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        out[sh.get("name")] = target
    return out


def _column_widths(path: Path, sheet_name: str, default: float, max_col: int) -> list[float]:
    """返回 1-based 列宽列表，下标 0 废弃。处理 col min/max 跨列。"""
    widths = [default] * (max_col + 1)
    target = _sheet_targets(path)[sheet_name]
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read(target))
    cols = root.find("m:cols", NS)
    if cols is None:
        return widths
    for col in cols:
        lo = int(col.get("min"))
        hi = int(col.get("max"))
        if col.get("hidden") == "1":
            w = 0.0
        elif col.get("width") is not None:
            w = float(col.get("width"))
        else:
            continue
        for i in range(lo, hi + 1):
            if i <= max_col:
                widths[i] = w
    return widths


def _setup(ws) -> PageSetup:
    ps = ws.page_setup
    pm = ws.page_margins
    pr = ws.sheet_properties.pageSetUpPr
    fit = bool(pr is not None and pr.fitToPage)
    # 省略 fitToWidth/Height 时 Excel 当 1；显式 0 表示这一维不参与缩放。
    def axis(value):
        if value is None:
            return 1
        if int(value) == 0:
            return None
        return int(value)

    return PageSetup(
        landscape=(ps.orientation == "landscape"),
        fit=fit,
        fit_w=axis(ps.fitToWidth) if fit else None,
        fit_h=axis(ps.fitToHeight) if fit else None,
        zoom=(ps.scale or 100) / 100.0,
        margin_l=(pm.left or 0.7) * 72,
        margin_r=(pm.right or 0.7) * 72,
        margin_t=(pm.top or 0.75) * 72,
        margin_b=(pm.bottom or 0.75) * 72,
    )


def _paper(landscape: bool) -> tuple[float, float]:
    w, h = A4
    return (h, w) if landscape else (w, h)


def _scale(content_w, content_h, page: PageSetup, pw, ph) -> float:
    printable_w = pw - page.margin_l - page.margin_r
    printable_h = ph - page.margin_t - page.margin_b
    if not page.fit:
        return page.zoom
    ratios = []
    if page.fit_w and content_w > 0:
        ratios.append(printable_w * page.fit_w / content_w)
    if page.fit_h and content_h > 0:
        ratios.append(printable_h * page.fit_h / content_h)
    if not ratios:
        return 1.0
    raw = min(1.0, *ratios)
    pct = max(10, int(raw * 100 + 1e-8))
    return pct / 100.0


_SUM = re.compile(r"^=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$", re.I)


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _eval(ws, value, cache: dict):
    if not (isinstance(value, str) and value.startswith("=")):
        return value
    m = _SUM.match(value.replace(" ", ""))
    if not m:
        return value
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
    from openpyxl.utils import column_index_from_string

    a = column_index_from_string(c1)
    b = column_index_from_string(c2)
    total = 0.0
    for r in range(min(r1, r2), max(r1, r2) + 1):
        for c in range(min(a, b), max(a, b) + 1):
            v = cache.get((r, c))
            n = _num(v)
            if n is not None:
                total += n
    return total


def _format_number(value, fmt: str) -> str:
    if fmt and "0.00" in fmt:
        return f"{value:,.2f}"
    if fmt and "#,##0" in fmt:
        return f"{value:,.0f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _display(value, fmt: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        if value.startswith("="):
            return value
        return value
    if isinstance(value, datetime):
        return f"{value.year}/{value.month}/{value.day}"
    if isinstance(value, date):
        return f"{value.year}/{value.month}/{value.day}"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return _format_number(value, fmt or "")
    return str(value)


def _is_accounting(fmt: str | None) -> bool:
    return bool(fmt) and fmt.startswith("_") and "#" in fmt


class Fonts:
    def __init__(self):
        self.simsun = fitz.Font(fontfile=SIMSUN)

    def width(self, text: str, size: float) -> float:
        return self.simsun.text_length(text, size)

    def line_height(self, size: float) -> tuple[float, float, float]:
        """返回 (ascent, descent, 行距)，单位点。用字体 em 比例，行距取 1.224×字号。

        1.224 来自 Excel PDF 里 8.04pt 宋体三行日期的基线间距 9.84。
        """
        ascent = self.simsun.ascender * size
        descent = -self.simsun.descender * size
        return ascent, descent, size * 1.224


def _wrap(text: str, fonts: Fonts, size: float, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if para == "":
            lines.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if cur and fonts.width(trial, size) > max_w:
                lines.append(cur)
                cur = ch
            else:
                cur = trial
        lines.append(cur)
    return lines or [""]


def workbook_sheets(path: Path) -> dict:
    """列出工作表名称，并标出 Excel 里当前打开的那一张。"""
    path = Path(path)
    wb = load_workbook(path, read_only=True)
    try:
        names = list(wb.sheetnames)
        active = wb.active.title if names and wb.active is not None else ""
    finally:
        wb.close()
    return {"sheets": names, "active": active}


def render_sheet(path: Path, sheet_name: str | None, out: Path) -> dict:
    path = Path(path)
    wb = load_workbook(path, data_only=False)
    wb_val = load_workbook(path, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    ws_val = wb_val[ws.title]
    setup = _setup(ws)
    # 打印统一为横向 A4，并缩放到一页（不超过 100%）。
    setup.landscape = True
    setup.fit = True
    setup.fit_w = 1
    setup.fit_h = 1
    pw, ph = _paper(setup.landscape)

    max_row = ws.max_row or 1
    max_col = ws.max_column or 1
    default_w = ws.sheet_format.defaultColWidth or 8.43
    default_h = ws.sheet_format.defaultRowHeight or 15
    col_w = _column_widths(path, ws.title, default_w, max_col)

    row_h = [0.0] * (max_row + 1)
    for r in range(1, max_row + 1):
        dim = ws.row_dimensions[r]
        row_h[r] = dim.height if dim.height is not None else default_h
        if dim.hidden:
            row_h[r] = 0.0

    merges = {}
    covered = set()
    merge_ranges = []
    for m in ws.merged_cells.ranges:
        min_c, min_r, max_c, max_r = range_boundaries(str(m))
        merges[(min_r, min_c)] = (max_r, max_c)
        merge_ranges.append((min_r, min_c, max_r, max_c))
        for r in range(min_r, max_r + 1):
            for c in range(min_c, max_c + 1):
                if (r, c) != (min_r, min_c):
                    covered.add((r, c))

    # 公式优先用 Excel 存下来的缓存值；没有缓存时再算 SUM。
    cache = {}
    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            cached = ws_val.cell(r, c).value
            raw = ws.cell(r, c).value
            cache[(r, c)] = cached if cached is not None else raw
    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            raw = ws.cell(r, c).value
            cur = cache[(r, c)]
            if isinstance(raw, str) and raw.startswith("=") and (cur is None or (isinstance(cur, str) and cur.startswith("="))):
                cache[(r, c)] = _eval(ws, raw, cache)

    fonts = Fonts()
    base_h = row_h[:]

    def fit_scale(heights) -> float:
        content_w = sum(col_w[1:]) * COL_PT
        content_h = sum(heights[1:]) * ROW_FACTOR
        return _scale(content_w, content_h, setup, pw, ph)

    def row_boost(scale: float) -> list[float]:
        """文字块高出单元格时，返回每一行需要追加的行高（Excel 点）。"""
        pad = PAD_PT * scale
        boost = [0.0] * (max_row + 1)
        for r in range(1, max_row + 1):
            for c in range(1, max_col + 1):
                if (r, c) in covered or row_h[r] <= 0:
                    continue
                cell = ws.cell(r, c)
                shown = cache.get((r, c))
                text = _display(shown, cell.number_format)
                if text == "":
                    continue
                r2, c2 = merges.get((r, c), (r, c))
                span_w = sum(col_w[c3] for c3 in range(c, c2 + 1)) * COL_PT * scale
                inner_w = max(1.0, span_w - 2 * pad)
                align = cell.alignment
                h_align = align.horizontal
                if h_align in (None, "general"):
                    h_align = "right" if isinstance(shown, (int, float)) and not isinstance(shown, bool) else "left"
                if _is_accounting(cell.number_format):
                    h_align = "right"
                wrap = bool(align.wrap_text) or "\n" in text or h_align in ("justify", "distributed")
                font_size = (cell.font.size or 11) * scale
                lines = _wrap(text, fonts, font_size, inner_w) if wrap else text.split("\n")
                ascent, descent, leading = fonts.line_height(font_size)
                block_h = ascent + descent + (len(lines) - 1) * leading
                span_h = sum(row_h[rr] for rr in range(r, r2 + 1)) * ROW_FACTOR * scale
                slack = 1.0 * scale
                if block_h + slack > span_h + 0.4:
                    extra = (block_h + slack - span_h) / (ROW_FACTOR * scale)
                    boost[r2] = max(boost[r2], extra)
        return boost

    scale = fit_scale(row_h)
    for _ in range(4):
        boost = row_boost(scale)
        if max(boost) < 0.2:
            break
        for r in range(1, max_row + 1):
            row_h[r] += boost[r]
        scale = fit_scale(row_h)

    grown = {
        r: (round(base_h[r], 2), round(row_h[r], 2))
        for r in range(1, max_row + 1)
        if row_h[r] > base_h[r] + 0.2
    }

    xs = [0.0] * (max_col + 1)
    xs[0] = setup.margin_l
    for c in range(1, max_col + 1):
        xs[c] = xs[c - 1] + col_w[c] * COL_PT * scale
    ys = [0.0] * (max_row + 1)
    ys[0] = setup.margin_t
    for r in range(1, max_row + 1):
        ys[r] = ys[r - 1] + row_h[r] * ROW_FACTOR * scale

    edges: dict[tuple, float] = {}

    def keep(key, style):
        if style is None or not style.style:
            return
        w = BORDER_W.get(style.style)
        if w is None:
            return
        edges[key] = max(edges.get(key, 0.0), w * scale)

    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            b = ws.cell(r, c).border
            keep(("h", r, c), b.top)
            keep(("h", r + 1, c), b.bottom)
            keep(("v", c, r), b.left)
            keep(("v", c + 1, r), b.right)

    # 合并区域内的边框留在各子单元格上，打印时只保留外框。
    for r1, c1, r2, c2 in merge_ranges:
        for rb in range(r1 + 1, r2 + 1):
            for c in range(c1, c2 + 1):
                edges.pop(("h", rb, c), None)
        for cb in range(c1 + 1, c2 + 1):
            for r in range(r1, r2 + 1):
                edges.pop(("v", cb, r), None)

    doc = fitz.open()
    page = doc.new_page(width=pw, height=ph)
    shape = page.new_shape()

    def hline(c, r_bound):
        y = ys[r_bound - 1]
        x0, x1 = xs[c - 1], xs[c]
        t = edges[("h", r_bound, c)]
        shape.draw_rect(fitz.Rect(x0, y - t / 2, x1, y + t / 2))

    def vline(r, c_bound):
        x = xs[c_bound - 1]
        y0, y1 = ys[r - 1], ys[r]
        t = edges[("v", c_bound, r)]
        shape.draw_rect(fitz.Rect(x - t / 2, y0, x + t / 2, y1))

    drawn = set()
    for (kind, a, b), t in edges.items():
        if t <= 0 or (kind, a, b) in drawn:
            continue
        drawn.add((kind, a, b))
        if kind == "h":
            hline(b, a)
        else:
            vline(b, a)
    shape.finish(color=None, fill=(0, 0, 0), width=0)
    shape.commit()

    pad = PAD_PT * scale
    tw = fitz.TextWriter(page.rect)

    for r in range(1, max_row + 1):
        for c in range(1, max_col + 1):
            if (r, c) in covered:
                continue
            cell = ws.cell(r, c)
            shown_value = cache.get((r, c))
            text = _display(shown_value, cell.number_format)
            if text == "":
                continue
            r2, c2 = merges.get((r, c), (r, c))
            x0, x1 = xs[c - 1], xs[c2]
            y0, y1 = ys[r - 1], ys[r2]
            font_size = (cell.font.size or 11) * scale
            align = cell.alignment
            h_align = align.horizontal
            v_align = align.vertical or "bottom"
            accounting = _is_accounting(cell.number_format)
            if h_align in (None, "general"):
                h_align = "right" if isinstance(shown_value, (int, float)) and not isinstance(shown_value, bool) else "left"
            # 会计格式自带右对齐（星号填充把数字顶到右边），盖过单元格里写的居中。
            if accounting:
                h_align = "right"
            # Excel 的两端对齐、分散对齐会自动换行。
            wrap = bool(align.wrap_text) or "\n" in text or h_align in ("justify", "distributed")
            if h_align in ("justify", "distributed"):
                h_align = "left"
            inner_w = max(1.0, (x1 - x0) - 2 * pad)
            lines = _wrap(text, fonts, font_size, inner_w) if wrap else text.split("\n")
            ascent, descent, leading = fonts.line_height(font_size)
            block_h = ascent + descent + (len(lines) - 1) * leading
            if v_align == "center":
                base = y0 + (y1 - y0 - block_h) / 2 + ascent
            elif v_align == "top":
                base = y0 + pad + ascent
            else:
                base = y1 - pad - descent - (len(lines) - 1) * leading
            bold = bool(cell.font.bold)
            for i, line in enumerate(lines):
                lw = fonts.width(line, font_size)
                if h_align == "center":
                    x = x0 + (x1 - x0 - lw) / 2
                elif h_align == "right":
                    # 会计格式末尾的 `_` 是一个空格宽的右缩进，不再叠加普通内边距。
                    inset = fonts.width(" ", font_size) if accounting else pad
                    x = x1 - inset - lw
                else:
                    x = x0 + pad
                y = base + i * leading
                tw.append((x, y), line, font=fonts.simsun, fontsize=font_size)
                if bold:
                    # Excel 对宋体加粗是同一副字形描边，这里用极小的水平偏移近似。
                    tw.append((x + 0.18 * scale, y), line, font=fonts.simsun, fontsize=font_size)

    tw.write_text(page, color=(0, 0, 0))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    doc.close()
    wb.close()
    wb_val.close()
    return {
        "sheet": ws.title,
        "page": (pw, ph),
        "scale": scale,
        "landscape": setup.landscape,
        "grown_rows": grown,
        "out": str(out),
    }


def main():
    import argparse

    p = argparse.ArgumentParser(description="按 Excel 页面设置把 xlsx 画成 PDF")
    p.add_argument("xlsx")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--sheet", default=None)
    args = p.parse_args()
    info = render_sheet(Path(args.xlsx), args.sheet, Path(args.out))
    print(info)


if __name__ == "__main__":
    main()
