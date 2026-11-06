# -*- coding: utf-8 -*-
"""把一条报销记录渲染成可打印的单据 HTML。"""
from __future__ import annotations

from .render_erp import (esc, fill, index_name, link_label, load_nodes,
                        load_render, person_rows, render, render_green)

from .store import kind_dir


class DocumentError(Exception):

    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


def open_doc(kind: str, stem: str) -> bytes:
    record_path = kind_dir("records") / f"{stem}.md"
    if not record_path.exists():
        raise DocumentError("没有这条记录")
    if kind == "green":
        return render_green(record_path, write=False).encode("utf-8")
    if kind == "erp":
        try:
            return render(record_path, write=False).encode("utf-8")
        except FileNotFoundError:
            raise DocumentError("这个任务模板还没有 ERP 渲染规则。")
    if kind == "list":
        return doc_section(stem, "发放清单")
    if kind == "note":
        return doc_section(stem, "发放说明")
    raise DocumentError("没有这一页")


def sheet(title: str, inner: str) -> bytes:
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{esc(title)}</title>
<link rel="stylesheet" href="/assets/sheet.css">
</head><body><div class="paper">{inner}</div></body></html>"""
    return html.encode("utf-8")


def labor_section(record, nodes, section: str):
    fee = link_label(record.get("B-报销模板"), nodes)
    key = "A-发放清单" if section == "发放清单" else "A-发放说明"
    data = load_render("劳务费发放清单", index_name(fee, key, nodes))
    if not isinstance(data, dict):
        return None
    spec = data.get(section)
    return spec if isinstance(spec, dict) else None


def line_values(spec, record, nodes):
    columns = spec.get("列") or []
    fields = spec.get("字段") or {}
    rows = []
    for index, line in enumerate(person_rows(record, nodes), start=1):
        values = []
        for name in columns:
            if name == "序号":
                values.append(str(index))
            else:
                values.append(fill(fields.get(name), record, nodes, line))
        rows.append(values)
    return rows


def doc_section(stem: str, section: str) -> bytes:
    nodes = load_nodes()
    record = nodes[stem]
    spec = labor_section(record, nodes, section)
    if not spec:
        return sheet(section, f"<p>这个任务模板还没有{esc(section)}的渲染规则。</p>")
    value = lambda key: fill(spec.get(key), record, nodes, None)
    rows = line_values(spec, record, nodes)
    total = value("合计")
    columns = [str(name) for name in (spec.get("列") or [])]

    def heads(fallback):
        names = columns or fallback
        cells = []
        for index, name in enumerate(names):
            klass = ' class="num"' if index == 0 else ""
            cells.append(f"<th{klass}>{esc(name)}</th>")
        return "".join(cells)

    def caption(key, fallback):
        text = value(key)
        return text or fallback

    if section == "发放清单":
        body = []
        for values in rows:
            body.append("<tr>"
                        f'<td class="num">{esc(values[0])}</td>'
                        f'<td class="center">{esc(values[1])}</td>'
                        f'<td class="center">{esc(values[2])}</td>'
                        f"<td>{esc(values[3])}</td>"
                        f'<td class="money">{esc(values[4])}</td>'
                        f"<td>{esc(values[5])}</td>"
                        "</tr>")
        empty = '<tr><td colspan="6">这条记录还没有劳务人员</td></tr>'
        labels = spec.get("落款")
        if not isinstance(labels, list) or not any(str(item).strip() for item in labels):
            labels = ["负责人", "分管领导", "项目负责人"]
        signoff = "".join(
            f"<span>{esc(str(item))}：</span>" for item in labels if str(item).strip()
        )
        inner = f"""
<h1>{esc(value("标题"))}（单位：元）</h1>
<table>
  <tr>
    <td colspan="4">{esc(caption("项目栏", "项目名称（ERP编号）"))}：{esc(value("项目"))}</td>
    <td colspan="2">{esc(caption("类型栏", "项目类型"))}：{esc(value("项目类型"))}</td>
  </tr>
  <tr>
    {heads(["序号", "姓名", "人员类别", "发放事由", "应发金额", "备注"])}
  </tr>
  {"".join(body) or empty}
  <tr><td colspan="4">合计</td><td class="money">{esc(total)}</td><td></td></tr>
</table>
<div class="signoff">{signoff}</div>"""
    else:
        body = []
        for values in rows:
            body.append("<tr>" + f'<td class="num">{esc(values[0])}</td>' +
                        f'<td class="center">{esc(values[1])}</td>' +
                        "".join(f"<td>{esc(item)}</td>"
                                for item in values[2:5]) +
                        f'<td class="money">{esc(values[5])}</td>' + "</tr>")
        empty = '<tr><td colspan="6">这条记录还没有劳务人员</td></tr>'
        inner = f"""
<h1>{esc(value("标题"))}</h1>
<table>
  <tr>
    <td class="label">劳务费发放时间</td>
    <td>{esc(value("发放时间"))}</td>
    <td class="label">报销单编号</td>
    <td>{esc(value("报销单编号"))}</td>
  </tr>
  <tr><th>阶段名称</th><th>阶段计划及目标</th><th colspan="2">成果形式</th></tr>
  <tr>
    <td class="center">{esc(value("阶段名称"))}</td>
    <td>{esc(value("阶段计划及目标"))}</td>
    <td colspan="2">{esc(value("成果形式"))}</td>
  </tr>
</table>
<table>
  <tr>{heads(["序号", "姓名", "工作内容", "成果", "人员类别", "发放金额"])}</tr>
  {"".join(body) or empty}
  <tr><td colspan="5">合计金额</td><td class="money">{esc(total)}</td></tr>
</table>"""
    return sheet(f"{section} · {stem}", inner)
