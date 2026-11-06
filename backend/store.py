# -*- coding: utf-8 -*-
"""档案的读写、编号和改名。不生成页面。"""
from __future__ import annotations

import json
import re
import secrets
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import yaml

from .render_erp import META

KINDS = {
    "people": "人员",
    "departments": "部门",
    "grants": "课题",
    "companies": "公司",
    "fees": "任务模板",
    "feetypes": "费用类型",
    "budgets": "预算类别",
    "taxes": "个税科目",
    "vendors": "供应商",
}

# 编号：签发日 + 类型 + 四位编码。类型码固定，编码避开 0/O、1/I。
ID_KIND = {
    "people": "RY",
    "departments": "BM",
    "grants": "KT",
    "companies": "GS",
    "fees": "FY",
    "feetypes": "LX",
    "budgets": "YS",
    "taxes": "SM",
    "vendors": "GY",
    "records": "JL",
}
ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

PRESETS = {
    "people": ["A-姓名", "A-工号", "A-身份证号", "A-手机号", "B-所属部门"],
    "departments":
    ["A-部门全称", "A-部门简称", "A-部门编号", "B-所属公司", "B-部门领导", "B-分管领导"],
    "grants": ["A-项目名称", "A-项目编号", "A-项目类型", "A-课题编号", "B-预算类别", "B-项目负责人"],
    "companies": [
        "A-公司全称", "A-公司简称", "A-公司编号", "A-税号", "B-总经理",
        "B-人力资源分管", "B-财务分管", "B-科研分管", "B-科管部门", "B-母公司",
    ],
    "fees": ["B-费用类型", "B-个税科目", "B-预算类别", "A-录入", "A-ERP", "A-发放清单", "A-发放说明", "A-标准流程"],
    "feetypes": ["A-费用类型编号", "A-费用类型简称", "A-费用类型名称"],
    "budgets": ["A-类别编码", "A-类别名称"],
    "taxes": ["A-科目编码", "A-科目名称"],
    "vendors": ["A-供应商全称", "A-供应商简称", "A-税号", "A-开户行", "A-银行账号"],
}

# B- 字段是指向另一份档案的引用。已知字段只列出那一类；没见过的 B- 字段列出全部档案。
LINK_KIND = {
    "B-所属部门": "departments",
    "B-所属公司": "companies",
    "B-部门领导": "people",
    "B-分管领导": "people",
    "B-项目负责人": "people",
    "B-总经理": "people",
    "B-人力资源分管": "people",
    "B-财务分管": "people",
    "B-科研分管": "people",
    "B-科管部门": "departments",
    "B-母公司": "companies",
    "B-报销人": "people",
    "B-报销项目": "grants",
    "B-报销模板": "fees",
    "B-费用类型": "feetypes",
    "B-人员": "people",
    "B-预算类别": "budgets",
    "B-个税科目": "taxes",
    "B-供应商": "vendors",
}

BUDGETS = ["年初预算内项目", "预算调整后项目", "预算增加后项目"]

OVERVIEW = {
    "people": [("A-姓名", "姓名"), ("A-工号", "工号"), ("A-手机号", "手机号"), ("A-身份证号", "身份证号"), ("B-所属部门", "所属部门")],
    "departments": [("A-部门全称", "全称"), ("A-部门编号", "编号"), ("B-所属公司", "所属公司"), ("B-部门领导", "部门领导"), ("B-分管领导", "分管领导")],
    "grants": [("A-项目名称", "项目名称"), ("A-项目编号", "项目编号"), ("A-课题编号", "课题编号"), ("A-项目类型", "项目类型"), ("B-预算类别", "预算类别"), ("B-项目负责人", "项目负责人")],
    "companies": [("A-公司全称", "全称"), ("A-公司编号", "编号"), ("A-税号", "税号"), ("B-母公司", "母公司"), ("B-总经理", "总经理")],
    "fees": [("B-费用类型", "费用类型"), ("B-个税科目", "个税科目"), ("B-预算类别", "预算类别"), ("A-标准流程", "步骤数")],
    "feetypes": [("A-费用类型编号", "编号"), ("A-费用类型简称", "简称"), ("A-费用类型名称", "名称")],
    "budgets": [("A-类别编码", "编码"), ("A-类别名称", "名称")],
    "taxes": [("A-科目编码", "编码"), ("A-科目名称", "名称")],
    "vendors": [("A-供应商全称", "全称"), ("A-供应商简称", "简称"), ("A-税号", "税号")],
}


def kind_dir(kind: str) -> Path:
    if kind not in KINDS and kind != "records":
        raise KeyError(kind)
    return META / kind


def safe_stem(stem: str) -> str:
    stem = unquote(stem).strip()
    if not stem or stem in {".", ".."} or any(ch in stem
                                              for ch in '\\/:*?"<>|'):
        raise ValueError("名称不能包含路径符号")
    return stem


def read_note(path: Path):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            data = yaml.safe_load(text[3:end]) or {}
            body = text[end + 4:]
            if not body.startswith("\n"):
                body = "\n" + body
            return data, body
    return {}, "\n" + text


def emit_scalar(value):
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value)
    if text == "" or text.strip() != text or any(
            ch in text for ch in ":#{}[]&,*!|>%@`'\"\n"):
        return json.dumps(text, ensure_ascii=False)
    return text


def dump_map(data, indent):
    lines = []
    for key, value in data.items():
        lines.extend(dump_pair("  " * indent, key, value, indent))
    return lines


def dump_pair(pad, key, value, indent):
    if isinstance(value, dict):
        body = dump_map(value, indent + 1)
        return [f"{pad}{key}:", *body] if body else [f"{pad}{key}:"]
    if isinstance(value, list):
        if not value:
            return [f"{pad}{key}:"]
        lines = [f"{pad}{key}:"]
        for item in value:
            if isinstance(item, dict):
                lines.extend(dump_dash_map(indent + 1, item))
            else:
                rendered = emit_scalar(item)
                lines.append(f"{pad}  - {rendered}" if rendered !=
                             "" else f"{pad}  -")
        return lines
    rendered = emit_scalar(value)
    return [f"{pad}{key}: {rendered}"] if rendered != "" else [f"{pad}{key}:"]


def dump_dash_map(indent, item):
    pad = "  " * indent
    pairs = list(item.items())
    if not pairs:
        return [f"{pad}-"]
    lines = []
    for index, (key, value) in enumerate(pairs):
        prefix = f"{pad}- " if index == 0 else f"{pad}  "
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.extend(dump_map(value, indent + 2))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for child in value:
                rendered = emit_scalar(child)
                lines.append(f"{pad}    - {rendered}" if rendered !=
                             "" else f"{pad}    -")
        else:
            rendered = emit_scalar(value)
            lines.append(f"{prefix}{key}: {rendered}" if rendered !=
                         "" else f"{prefix}{key}:")
    return lines


def write_note(path: Path, data: dict, body: str):
    lines = ["---", *dump_map(data, 0), "---"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) +
                    (body if body.startswith("\n") else "\n" + body),
                    encoding="utf-8")


def stems(kind: str) -> list[str]:
    folder = kind_dir(kind)
    if not folder.exists():
        return []
    return sorted(p.stem for p in folder.glob("*.md")
                  if not p.stem.startswith("_"))


def entries(kind: str) -> list[tuple[str, str]]:
    """(稳定 id, 当前文件名)。还没改过名的档案，id 就是文件名。"""
    folder = kind_dir(kind)
    if not folder.exists():
        return []
    found = []
    for path in folder.glob("*.md"):
        if path.stem.startswith("_"):
            continue
        data, _ = read_note(path)
        ident = data.get("id")
        key = path.stem if ident in (None, "") else str(ident).strip()
        found.append((key, path.stem))
    return sorted(found, key=lambda item: item[1])


def name_taken(stem: str, except_stem: str = "") -> bool:
    """文件名和 id 共用一个名字空间，两边都不能撞。"""
    for path in META.rglob("*.md"):
        if path.stem.startswith("_") or path.stem == except_stem:
            continue
        if path.stem == stem:
            return True
        data, _ = read_note(path)
        ident = data.get("id")
        if ident not in (None, "") and str(ident).strip() == stem:
            return True
    render_dir = META / "render"
    if render_dir.is_dir():
        for path in render_dir.rglob("*.yaml"):
            if path.stem == stem and path.stem != except_stem:
                return True
    preview = META / "preview"
    if preview.is_dir():
        for suffix in (".html", ".绿色单子.html"):
            if (preview / f"{stem}{suffix}").exists() and stem != except_stem:
                return True
    return False


def new_id(kind: str) -> str:
    prefix = ID_KIND[kind]
    day = date.today().strftime("%Y%m%d")
    for _ in range(20):
        code = "".join(secrets.choice(ID_ALPHABET) for _ in range(4))
        ident = f"{day}-{prefix}-{code}"
        if not name_taken(ident):
            return ident
    raise ValueError("编号没有生成成功")


def id_example(kind: str) -> str:
    return f"{date.today().strftime('%Y%m%d')}-{ID_KIND[kind]}-7K3Q"


def rewrite_links(old: str, ident: str):
    """把 [[旧名称]] 改成 [[编号]]。只认整段链接，不改文件名和正文。"""

    def repl(match):
        body = match.group(1).strip()
        key, sep, alias = body.partition("|")
        if key.strip() != old:
            return match.group(0)
        if sep:
            return f"[[{ident}|{alias}]]"
        return f"[[{ident}]]"

    pattern = re.compile(r"\[\[([^\]]*)\]\]")
    for path in META.rglob("*"):
        if path.suffix.lower() not in {".md", ".yaml", ".yml"}:
            continue
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        updated = pattern.sub(repl, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def retitle_companions(old: str, new: str):
    """渲染规则和预览文件跟报销模板、记录的文件名走。"""
    render_dir = META / "render"
    if render_dir.is_dir():
        for path in list(render_dir.rglob("*.yaml")):
            if path.stem != old:
                continue
            text = path.read_text(encoding="utf-8").replace(
                f"{old}.md", f"{new}.md")
            target = path.with_name(new + path.suffix)
            target.write_text(text, encoding="utf-8")
            if target.resolve() != path.resolve():
                path.unlink()
    preview = META / "preview"
    if preview.is_dir():
        for suffix in (".绿色单子.html", ".html"):
            path = preview / f"{old}{suffix}"
            if path.exists():
                path.replace(preview / f"{new}{suffix}")


def link_or_blank(stem: str) -> str:
    stem = stem.strip()
    return f"[[{stem}]]" if stem else ""


def save_named(kind: str, old: str | None, new: str, data: dict,
               body: str) -> str:
    """保存档案。编号在新建时生成，改名不改编号。"""
    new = safe_stem(new)
    if new.startswith("_"):
        raise ValueError("名称不能以 _ 开头")
    data = {key: value for key, value in data.items() if key != "id"}
    folder = kind_dir(kind)
    if old is None:
        if name_taken(new):
            raise ValueError("已经有同名文件")
        write_note(folder / f"{new}.md", {"id": new_id(kind), **data}, body)
        return new
    old = safe_stem(old)
    source = folder / f"{old}.md"
    if not source.exists():
        raise ValueError("没有这条数据")
    existing, _ = read_note(source)
    ident = existing.get("id")
    ident = "" if ident in (None, "") else str(ident).strip()
    if new == old:
        if ident:
            data = {"id": ident, **data}
        write_note(source, data, body)
        return old
    if name_taken(new, old):
        raise ValueError("已经有同名文件")
    minted = False
    if not ident:
        ident = new_id(kind)
        minted = True
    data = {"id": ident, **data}
    aside = source.with_name(f"_{old}.__renaming__.md")
    source.replace(aside)
    target = folder / f"{new}.md"
    try:
        write_note(target, data, body)
    except Exception:
        aside.replace(source)
        raise
    aside.unlink()
    retitle_companions(old, new)
    if minted:
        rewrite_links(old, ident)
    return new


def template_fields(kind: str) -> dict:
    """新建时按该类的 _template.md 起稿。模板里的值留空，这里也留空。"""
    path = kind_dir(kind) / "_template.md"
    if path.exists():
        data, _ = read_note(path)
        if data:
            return {key: "" for key in data}
    return {key: "" for key in PRESETS.get(kind, [])}
