# -*- coding: utf-8 -*-
"""JSON 接口。页面怎么画由 frontend/ 决定，这里只收发档案数据。"""
from __future__ import annotations

from .render_erp import index_name, link_label, link_name, load_entry, load_nodes

from .flow import (apply_progress_update, current_step_label,
                   ensure_record_flow, flow_text_from_steps, merge_flow_fields,
                   normalize_progress, normalize_step, present_flow_rows,
                   rework_progress, role_names, seed_from_fee, step_title,
                   steps_from_fee, steps_from_flow_text)
from .store import (BUDGETS, KINDS, LINK_KIND, OVERVIEW, entries, id_example,
                    kind_dir, link_or_blank, read_note, safe_stem, save_named,
                    stems, template_fields, write_note)

RECORD_KEYS = [
    "A-单据编号",
    "A-总金额",
    "A-付款日期",
    "A-事由",
    "A-发放时间",
    "A-阶段名称",
    "A-阶段计划及目标",
    "A-成果形式",
    "A-预算情况",
    "A-预算项目",
    "B-报销人",
    "B-报销项目",
    "B-报销模板",
    "B-供应商",
]

LINE_KEYS = [
    "A-人员类别",
    "A-工作内容",
    "A-成果",
    "A-发放事由",
    "A-发放金额",
    "A-个人所得税",
    "A-备注",
]


class HttpError(Exception):

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def dispatch(method: str, parts: list[str], payload: dict | None):
    if not parts or parts[0] != "api":
        raise HttpError("没有这一页", 404)
    if parts[1:] == ["meta"]:
        return _method("GET", method, get_meta)
    if parts[1:] == ["catalog"]:
        return _method("GET", method, get_catalog)
    if parts[1:] == ["records"]:
        if method == "GET":
            return get_records()
        if method == "POST":
            return create_record(payload or {})
        raise HttpError("不支持这个操作", 405)
    if len(parts) == 4 and parts[1] == "records" and parts[3] == "flow":
        stem = safe_stem(parts[2])
        if method == "PUT":
            return update_record_flow(stem, payload or {})
        raise HttpError("不支持这个操作", 405)
    if len(parts) == 3 and parts[1] == "records":
        stem = safe_stem(parts[2])
        if method == "GET":
            return get_record(stem)
        if method == "PUT":
            return update_record(stem, payload or {})
        raise HttpError("不支持这个操作", 405)
    if len(parts) == 3 and parts[1] == "data":
        kind = _kind(parts[2])
        if method == "GET":
            return get_kind(kind)
        if method == "POST":
            return create_note(kind, payload or {})
        raise HttpError("不支持这个操作", 405)
    if len(parts) == 4 and parts[1] == "data":
        kind = _kind(parts[2])
        stem = parts[3] if parts[3] in {"_new", "_template"} else safe_stem(parts[3])
        if stem == "_new":
            return _method("GET", method, lambda: get_note(kind, stem))
        if stem == "_template":
            if method == "GET":
                return get_note(kind, stem)
            if method == "PUT":
                return update_note(kind, stem, payload or {})
            raise HttpError("不支持这个操作", 405)
        if method == "GET":
            return get_note(kind, stem)
        if method == "PUT":
            return update_note(kind, stem, payload or {})
        raise HttpError("不支持这个操作", 405)
    raise HttpError("没有这一页", 404)


def _method(expected: str, method: str, fn):
    if method != expected:
        raise HttpError("不支持这个操作", 405)
    return fn()


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HttpError("没有这一页", 404)
    return kind


def get_meta():
    kinds = list(KINDS) + ["records"]
    return {
        "kinds": KINDS,
        "linkKind": LINK_KIND,
        "budgets": list(BUDGETS),
        "roles": role_names(),
        "idExamples": {kind: id_example(kind) for kind in kinds},
    }


def get_catalog():
    nodes = load_nodes()
    found = {}
    for kind in KINDS:
        rows = []
        for ident, name in entries(kind):
            item = {"key": ident, "label": name}
            if kind == "fees":
                item["blocks"] = load_entry(name, nodes)
            rows.append(item)
        found[kind] = rows
    return found


def get_records():
    nodes = load_nodes()
    rows = []
    for stem in stems("records"):
        path = kind_dir("records") / f"{stem}.md"
        data, body = read_note(path)
        data, changed = ensure_record_flow(data, nodes)
        if changed:
            write_note(path, data, body)
            nodes = load_nodes()
        flow_rows = present_flow_rows(
            data.get("A-流程模板"), data.get("A-流程"), data, nodes)
        rows.append({
            "stem": stem,
            "code": shown(data.get("A-单据编号") or ""),
            "who": link_label(data.get("B-报销人"), nodes),
            "fee": link_label(data.get("B-报销模板"), nodes),
            "amount": shown(data.get("A-总金额") or ""),
            "step": current_step_label(
                data.get("A-流程模板"), data.get("A-流程"), data, nodes),
            "steps": [
                {"done": bool(row["done"]), "label": row["label"]}
                for row in flow_rows
                if int(row.get("round") or 1) <= 1
            ],
        })
    return rows


def get_record(stem: str):
    path = kind_dir("records") / f"{stem}.md"
    if not path.exists():
        raise HttpError("没有这条记录", 404)
    data, body = read_note(path)
    nodes = load_nodes()
    data, changed = ensure_record_flow(data, nodes)
    if changed:
        write_note(path, data, body)
        nodes = load_nodes()
    raw = data.get("B-劳务人员")
    if not isinstance(raw, list) or not raw:
        raw = [{}]
    return {
        "stem": stem,
        "id": stored_id(data),
        "idExample": id_example("records"),
        "feeLabel": link_label(data.get("B-报销模板"), nodes),
        "pages": record_pages(data, nodes),
        "fields": present_fields(data),
        "lines": [present_line(line) for line in raw],
        "flow": present_flow_payload(data, nodes),
    }


def create_record(payload: dict):
    data = record_from_payload(payload)
    nodes = load_nodes()
    template, progress = seed_from_fee(data, nodes)
    data["A-流程模板"] = template
    data["A-流程"] = progress
    saved = save_named("records", None, text_name(payload), data, "\n")
    return {"stem": saved}


def update_record(stem: str, payload: dict):
    path = kind_dir("records") / f"{stem}.md"
    if not path.exists():
        raise HttpError("没有这条记录", 404)
    existing, body = read_note(path)
    data = merge_flow_fields(existing, record_from_payload(payload))
    saved = save_named("records", stem, text_name(payload), data, body)
    return {"stem": saved}


def update_record_flow(stem: str, payload: dict):
    path = kind_dir("records") / f"{stem}.md"
    if not path.exists():
        raise HttpError("没有这条记录", 404)
    data, body = read_note(path)
    nodes = load_nodes()
    data, changed = ensure_record_flow(data, nodes)
    if changed:
        write_note(path, data, body)
        data, body = read_note(path)
    action = str(payload.get("action") or "save").strip()
    template = data.get("A-流程模板")
    progress = data.get("A-流程")
    if action == "rework":
        progress = rework_progress(template, progress,
                                   form_one(payload, "start"),
                                   form_one(payload, "end"))
    else:
        progress = apply_progress_update(template, progress,
                                         payload.get("items") or [])
    data = dict(data)
    data["A-流程"] = [normalize_progress(item) for item in progress]
    write_note(path, data, body)
    nodes = load_nodes()
    return {"stem": stem, "flow": present_flow_payload(data, nodes)}


def present_flow_payload(data: dict, nodes=None) -> dict:
    if nodes is None:
        nodes = load_nodes()
    template = data.get("A-流程模板")
    progress = data.get("A-流程")
    rows = present_flow_rows(template, progress, data, nodes)
    choices = []
    if isinstance(template, list):
        for step in template:
            if not isinstance(step, dict) or not step.get("键"):
                continue
            try:
                normalized = normalize_step(step)
            except ValueError:
                continue
            label = step_title(normalized)
            doc = normalized.get("单据") or ""
            choices.append({
                "key": normalized["键"],
                "label": f"{doc} · {label}" if doc else label,
            })
    frozen = any(
        row["done"] or row["note1"].strip() or row["note2"].strip()
        or row["round"] > 1 for row in rows)
    return {
        "current": current_step_label(template, progress, data, nodes),
        "frozen": frozen,
        "items": rows,
        "choices": choices,
    }


def get_kind(kind: str):
    nodes = load_nodes()
    columns = [{"key": key, "label": label} for key, label in OVERVIEW[kind]]
    rows = []
    for stem in stems(kind):
        data, _ = read_note(kind_dir(kind) / f"{stem}.md")
        cells = []
        for key, _label in OVERVIEW[kind]:
            value = data.get(key)
            if kind == "grants" and key == "A-项目名称" and not value:
                value = data.get("title-cn")
            if kind == "fees" and key == "A-标准流程":
                cells.append(str(len(steps_from_fee(data))))
                continue
            cells.append(plain(value, nodes))
        rows.append({"stem": stem, "cells": cells})
    return {
        "kind": kind,
        "label": KINDS[kind],
        "columns": columns,
        "rows": rows,
    }


def get_note(kind: str, stem: str):
    label = KINDS[kind]
    if stem == "_new":
        data = template_fields(kind)
        payload = {
            "kind": kind,
            "mode": "new",
            "title": "新建" + label,
            "stem": "_new",
            "name": "",
            "id": "",
            "idExample": id_example(kind),
            "fields": field_rows(data, kind),
        }
        if kind == "fees":
            payload["flowText"] = ""
        return payload
    if stem == "_template":
        data, _ = read_note(kind_dir(kind) / "_template.md")
        payload = {
            "kind": kind,
            "mode": "template",
            "title": label + "标准模板",
            "stem": "_template",
            "name": "",
            "id": "",
            "idExample": id_example(kind),
            "fields": field_rows(data, kind),
        }
        if kind == "fees":
            payload["flowText"] = flow_text_from_steps(steps_from_fee(data))
        return payload
    data, _ = read_note(kind_dir(kind) / f"{stem}.md")
    payload = {
        "kind": kind,
        "mode": "edit",
        "title": stem,
        "stem": stem,
        "name": stem,
        "id": stored_id(data),
        "idExample": id_example(kind),
        "fields": field_rows(data, kind),
    }
    if kind == "fees":
        payload["flowText"] = flow_text_from_steps(steps_from_fee(data))
    return payload


def create_note(kind: str, payload: dict):
    saved = save_named(kind, None, text_name(payload),
                       collect_fields(payload, kind), "\n")
    return {"stem": saved}


def update_note(kind: str, stem: str, payload: dict):
    if stem == "_template":
        target = kind_dir(kind) / "_template.md"
        _, body = read_note(target)
        write_note(target, collect_fields(payload, kind), body)
        return {"stem": "_template"}
    path = kind_dir(kind) / f"{stem}.md"
    _, body = read_note(path)
    saved = save_named(kind, stem, text_name(payload),
                       collect_fields(payload, kind), body)
    return {"stem": saved}


def shown(value) -> str:
    if value is None:
        return ""
    return str(value)


def stored_id(data: dict) -> str:
    raw = data.get("id") if isinstance(data, dict) else None
    return "" if raw in (None, "") else str(raw).strip()


def selected_link(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text == "[[]]":
        return ""
    return link_name(text) or text


def plain(value, nodes=None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        text = value.strip()
        linked = link_name(text)
        if linked:
            return link_label(text, nodes) or linked
        if text.startswith("[[") and text.endswith("]]"):
            return ""
        return text
    return str(value)


def record_pages(record: dict, nodes=None) -> list[str]:
    """这条记录要打开的单据。绿色单始终有，其余看任务模板上的索引。"""
    if nodes is None:
        nodes = load_nodes()
    fee = link_label(record.get("B-报销模板"), nodes)
    pages = ["green"]
    if index_name(fee, "A-ERP", nodes):
        pages.append("erp")
    if index_name(fee, "A-发放清单", nodes):
        pages.append("list")
    if index_name(fee, "A-发放说明", nodes):
        pages.append("note")
    return pages


def present_fields(data: dict) -> dict:
    fields = {}
    for key in RECORD_KEYS:
        value = data.get(key, "")
        if key == "A-发放时间":
            fields[key] = dates_text(value)
        elif key.startswith("B-"):
            fields[key] = selected_link(value)
        else:
            fields[key] = shown(value)
    return fields


def present_line(line) -> dict:
    line = line if isinstance(line, dict) else {}
    item = {"B-人员": selected_link(line.get("B-人员"))}
    for key in LINE_KEYS:
        item[key] = shown(line.get(key))
    return item


def field_rows(data: dict, kind: str = "") -> list[dict]:
    rows = []
    for key, value in data.items():
        if key == "id":
            continue
        if kind == "fees" and key == "A-标准流程":
            continue
        if str(key).startswith("B-"):
            shown_value = selected_link(value)
        else:
            shown_value = shown(value)
        rows.append({"key": str(key), "value": shown_value})
    return rows


def text_name(payload: dict) -> str:
    name = payload.get("name", "")
    if name is None:
        return ""
    return name if isinstance(name, str) else str(name)


def collect_fields(payload: dict, kind: str = "") -> dict:
    raw = payload.get("fields")
    if not isinstance(raw, dict):
        raise ValueError("字段格式不对")
    data = {}
    for key, value in raw.items():
        key = str(key).strip()
        if not key or key == "id":
            continue
        if kind == "fees" and key == "A-标准流程":
            continue
        if key.startswith("B-"):
            text = "" if value is None else str(value).strip()
            name = "" if not text or text == "[[]]" else (link_name(text) or
                                                          text)
            data[key] = link_or_blank(name)
        elif value is None:
            data[key] = ""
        elif isinstance(value, str):
            data[key] = value
        else:
            data[key] = str(value)
    if kind == "fees":
        data["A-标准流程"] = steps_from_flow_text(payload.get("flowText", ""))
    return data


def coerce(value: str):
    text = value.strip()
    if text == "":
        return ""
    if text.lstrip("-").isdigit():
        return int(text)
    return value


def form_one(payload: dict, name: str) -> str:
    value = payload.get(name, "")
    if value is None:
        return ""
    return str(value).strip()


def parse_dates(text: str):
    parts = []
    for piece in text.replace("，", "\n").replace(",", "\n").replace(
            "、", "\n").splitlines():
        if piece.strip():
            parts.append(piece.strip())
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return parts


def dates_text(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item not in (None, ""))
    return "" if value is None else str(value)


def labor_lines_from_payload(payload: dict) -> list:
    raw = payload.get("lines", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("劳务人员格式不对")

    def at(line, name):
        value = line.get(name, "")
        return "" if value is None else str(value).strip()

    lines = []
    for line in raw:
        if not isinstance(line, dict):
            continue
        amount = at(line, "A-发放金额")
        tax = at(line, "A-个人所得税")
        fields = {
            "A-人员类别": at(line, "A-人员类别"),
            "A-工作内容": at(line, "A-工作内容"),
            "A-成果": at(line, "A-成果"),
            "A-发放事由": at(line, "A-发放事由"),
            "A-发放金额": coerce(amount) if amount else "",
            "A-个人所得税": coerce(tax) if tax else "",
            "A-备注": at(line, "A-备注"),
        }
        person = at(line, "B-人员")
        if not person and not any(fields.values()):
            continue
        lines.append({"B-人员": link_or_blank(person), **fields})
    return lines


def record_from_payload(payload: dict) -> dict:
    return {
        "A-单据编号": form_one(payload, "A-单据编号"),
        "A-总金额": coerce(form_one(payload, "A-总金额")),
        "A-付款日期": form_one(payload, "A-付款日期"),
        "A-事由": form_one(payload, "A-事由"),
        "A-发放时间": parse_dates(form_one(payload, "A-发放时间")),
        "A-阶段名称": form_one(payload, "A-阶段名称"),
        "A-阶段计划及目标": form_one(payload, "A-阶段计划及目标"),
        "A-成果形式": form_one(payload, "A-成果形式"),
        "A-预算情况": form_one(payload, "A-预算情况"),
        "A-预算项目": form_one(payload, "A-预算项目"),
        "B-报销人": link_or_blank(form_one(payload, "B-报销人")),
        "B-报销项目": link_or_blank(form_one(payload, "B-报销项目")),
        "B-报销模板": link_or_blank(form_one(payload, "B-报销模板")),
        "B-供应商": link_or_blank(form_one(payload, "B-供应商")),
        "B-劳务人员": labor_lines_from_payload(payload),
    }
