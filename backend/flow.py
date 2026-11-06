# -*- coding: utf-8 -*-
"""报销模板的标准流程，以及记录上的流程快照与进度。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .render_erp import META, fill, link_label, load_nodes

from .store import kind_dir, read_note, write_note

ROLE_PATH = META / "render" / "角色.yaml"

STEP_KEYS = ("键", "单据", "动作", "角色", "标题")
PROGRESS_KEYS = ("键", "轮次", "备注1", "完成", "备注2")

ERP_GREEN = [
    {"键": "erp-submit", "单据": "ERP", "动作": "提交", "角色": "经办人"},
    {"键": "erp-dept", "单据": "ERP", "动作": "审批", "角色": "部门领导"},
    {"键": "erp-leader", "单据": "ERP", "动作": "审批", "角色": "分管领导"},
    {"键": "erp-ceo", "单据": "ERP", "动作": "审批", "角色": "总经理"},
    {"键": "green-fill", "单据": "绿色单", "动作": "填写", "角色": "经办人"},
    {"键": "green-dept", "单据": "绿色单", "动作": "签字", "角色": "部门领导"},
    {"键": "green-leader", "单据": "绿色单", "动作": "签字", "角色": "分管领导"},
    {"键": "green-ceo", "单据": "绿色单", "动作": "签字", "角色": "总经理"},
]

WHITE_INTERNAL = [
    {"键": "white-fill", "单据": "白色单", "动作": "填写、打印并签字", "角色": "经办人"},
    {"键": "white-dept", "单据": "白色单", "动作": "签字", "角色": "部门领导"},
    {"键": "white-km", "单据": "白色单", "动作": "签字", "角色": "科管部负责人"},
    {"键": "white-pi", "单据": "白色单", "动作": "签字", "角色": "项目负责人"},
    {"键": "white-rd", "单据": "白色单", "动作": "签字", "角色": "科研分管领导"},
    {"键": "white-hr", "单据": "白色单", "动作": "签字", "角色": "人力资源分管领导"},
    {
        "键": "white-dean",
        "单据": "白色单",
        "动作": "签字",
        "角色": "总经理",
        "标题": "单位负责人签字",
    },
    {"键": "white-submit", "单据": "白色单", "动作": "交给综合办", "角色": "经办人"},
]

WHITE_EXTERNAL = [
    {"键": "white-fill", "单据": "白色单", "动作": "填写、打印并签字", "角色": "经办人"},
    {"键": "white-dept", "单据": "白色单", "动作": "签字", "角色": "部门领导"},
    {"键": "white-gk-head", "单据": "白色单", "动作": "签字", "角色": "归口管理部门负责人"},
    {"键": "white-gk-leader", "单据": "白色单", "动作": "签字", "角色": "归口管理部门分管领导"},
    {"键": "white-pi", "单据": "白色单", "动作": "签字", "角色": "项目负责人"},
    {"键": "white-fin", "单据": "白色单", "动作": "签字", "角色": "财务分管领导"},
    {
        "键": "white-dean",
        "单据": "白色单",
        "动作": "签字",
        "角色": "总经理",
        "标题": "单位负责人签字",
    },
    {"键": "white-submit", "单据": "白色单", "动作": "交给综合办", "角色": "经办人"},
]


def clone_steps(steps: list[dict]) -> list[dict]:
    return [normalize_step(step) for step in steps]


def normalize_step(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("标准流程每一步必须是对象")
    step = {}
    for key in STEP_KEYS:
        value = raw.get(key, "")
        step[key] = "" if value is None else str(value).strip()
    if not step["键"]:
        raise ValueError("标准流程每一步都要有键")
    if not step["单据"] or not step["动作"] or not step["角色"]:
        raise ValueError(f"步骤 {step['键']} 缺少单据、动作或角色")
    if step["标题"] == "":
        step.pop("标题", None)
    return step


def normalize_progress(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("流程进度格式不对")
    item = {
        "键": "" if raw.get("键") is None else str(raw.get("键")).strip(),
        "轮次": 1,
        "备注1": "" if raw.get("备注1") is None else str(raw.get("备注1")),
        "完成": False,
        "备注2": "" if raw.get("备注2") is None else str(raw.get("备注2")),
    }
    if not item["键"]:
        raise ValueError("流程进度缺少键")
    round_raw = raw.get("轮次", 1)
    try:
        item["轮次"] = int(round_raw)
    except (TypeError, ValueError):
        item["轮次"] = 1
    if item["轮次"] < 1:
        item["轮次"] = 1
    done = raw.get("完成", False)
    if isinstance(done, bool):
        item["完成"] = done
    elif isinstance(done, str):
        item["完成"] = done.strip().lower() in {"1", "true", "yes", "是", "完成"}
    else:
        item["完成"] = bool(done)
    return item


def steps_from_fee(fee_data: dict | None) -> list[dict]:
    if not isinstance(fee_data, dict):
        return []
    raw = fee_data.get("A-标准流程")
    if not isinstance(raw, list):
        return []
    steps = []
    seen = set()
    for item in raw:
        step = normalize_step(item)
        if step["键"] in seen:
            raise ValueError(f"标准流程的键重复：{step['键']}")
        seen.add(step["键"])
        steps.append(step)
    return steps


def fee_steps_for_label(fee_label: str, nodes=None) -> list[dict]:
    if not fee_label:
        return []
    if nodes is None:
        nodes = load_nodes()
    fee = nodes.get(fee_label)
    if fee is None:
        by_stem = getattr(nodes, "by_stem", {})
        key = by_stem.get(fee_label)
        fee = nodes.get(key) if key else None
    return steps_from_fee(fee)


def load_roles() -> dict:
    if not ROLE_PATH.exists():
        return {}
    data = yaml.safe_load(ROLE_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return {
        str(key).strip(): "" if value is None else str(value).strip()
        for key, value in data.items()
        if str(key).strip()
    }


def role_names() -> list[str]:
    return list(load_roles())


def resolve_role_person(role: str, record: dict, nodes=None) -> str:
    roles = load_roles()
    template = roles.get(role, "")
    if not template:
        return ""
    if nodes is None:
        nodes = load_nodes()
    return fill(template, record, nodes, None) or ""


def step_title(step: dict) -> str:
    title = step.get("标题") or ""
    if title:
        return title
    action = (step.get("动作") or "").strip()
    role = (step.get("角色") or "").strip()
    if action and role:
        return f"{action} · {role}"
    return action or role


def flow_started(template, progress) -> bool:
    if not isinstance(template, list) or not isinstance(progress, list):
        return False
    if not progress:
        return False
    for item in progress:
        if not isinstance(item, dict):
            continue
        try:
            row = normalize_progress(item)
        except ValueError:
            continue
        if row["完成"] or row["备注1"].strip() or row["备注2"].strip() or row["轮次"] > 1:
            return True
    return False


def blank_progress(steps: list[dict], round_no: int = 1) -> list[dict]:
    return [{
        "键": step["键"],
        "轮次": round_no,
        "备注1": "",
        "完成": False,
        "备注2": "",
    } for step in steps]


def seed_from_fee(record: dict, nodes=None) -> tuple[list[dict], list[dict]]:
    if nodes is None:
        nodes = load_nodes()
    fee_label = link_label(record.get("B-报销模板"), nodes)
    steps = fee_steps_for_label(fee_label, nodes)
    return clone_steps(steps), blank_progress(steps)


def ensure_record_flow(record: dict, nodes=None) -> tuple[dict, bool]:
    """未开始时按报销模板重带；已开始则原样返回。返回 (更新后的 record, 是否写回)。"""
    if nodes is None:
        nodes = load_nodes()
    template = record.get("A-流程模板")
    progress = record.get("A-流程")
    if flow_started(template, progress):
        return record, False
    seeded_template, seeded_progress = seed_from_fee(record, nodes)
    changed = template != seeded_template or progress != seeded_progress
    record = dict(record)
    record["A-流程模板"] = seeded_template
    record["A-流程"] = seeded_progress
    return record, changed


def merge_flow_fields(existing: dict, data: dict) -> dict:
    """保存报销信息时，把流程两段从原文件并回去；未开始则按新报销模板重带。"""
    merged = dict(data)
    template = existing.get("A-流程模板")
    progress = existing.get("A-流程")
    if flow_started(template, progress):
        if isinstance(template, list):
            merged["A-流程模板"] = template
        if isinstance(progress, list):
            merged["A-流程"] = progress
        return merged
    nodes = load_nodes()
    # 用即将保存的报销模板重带
    probe = dict(existing)
    probe.update(data)
    seeded_template, seeded_progress = seed_from_fee(probe, nodes)
    merged["A-流程模板"] = seeded_template
    merged["A-流程"] = seeded_progress
    return merged


def current_step_label(template, progress, record=None, nodes=None) -> str:
    rows = present_flow_rows(template, progress, record, nodes)
    if not rows and not template:
        return "无标准流程"
    for row in rows:
        if not row["done"]:
            return row["label"]
    if rows:
        return "已完成"
    return "无标准流程"


def present_flow_rows(template, progress, record=None, nodes=None) -> list[dict]:
    if not isinstance(template, list):
        template = []
    if not isinstance(progress, list):
        progress = []
    if nodes is None and record is not None:
        nodes = load_nodes()
    by_key = {}
    for step in template:
        if isinstance(step, dict) and step.get("键"):
            by_key[str(step["键"]).strip()] = normalize_step(step)
    rows = []
    for item in progress:
        if not isinstance(item, dict):
            continue
        try:
            row = normalize_progress(item)
        except ValueError:
            continue
        step = by_key.get(row["键"], {
            "键": row["键"],
            "单据": "",
            "动作": "",
            "角色": "",
        })
        person = ""
        if record is not None and step.get("角色"):
            person = resolve_role_person(step["角色"], record, nodes)
        label = step_title(step)
        if step.get("单据"):
            shown = f"{step['单据']} · {label}"
        else:
            shown = label or row["键"]
        rows.append({
            "key": row["键"],
            "round": row["轮次"],
            "note1": row["备注1"],
            "done": row["完成"],
            "note2": row["备注2"],
            "doc": step.get("单据", ""),
            "action": step.get("动作", ""),
            "role": step.get("角色", ""),
            "title": step.get("标题", ""),
            "label": shown,
            "person": person,
        })
    return rows


def apply_progress_update(template, progress, items: list) -> list[dict]:
    if not isinstance(template, list):
        raise ValueError("这条记录还没有流程模板")
    if not isinstance(progress, list):
        raise ValueError("这条记录还没有流程进度")
    if not isinstance(items, list):
        raise ValueError("流程进度格式不对")
    if len(items) != len(progress):
        raise ValueError("流程进度行数不对")
    updated = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError("流程进度格式不对")
        old = normalize_progress(progress[index])
        new = normalize_progress({
            "键": old["键"],
            "轮次": old["轮次"],
            "备注1": raw.get("备注1", old["备注1"]),
            "完成": raw.get("完成", old["完成"]),
            "备注2": raw.get("备注2", old["备注2"]),
        })
        if new["键"] != old["键"] or new["轮次"] != old["轮次"]:
            raise ValueError("不能改步骤键或轮次")
        updated.append(new)
    return updated


def rework_progress(template, progress, start_key: str, end_key: str) -> list[dict]:
    if not isinstance(template, list) or not template:
        raise ValueError("这条记录还没有流程模板")
    steps = [normalize_step(step) for step in template if isinstance(step, dict)]
    keys = [step["键"] for step in steps]
    start_key = (start_key or "").strip()
    end_key = (end_key or "").strip()
    if start_key not in keys or end_key not in keys:
        raise ValueError("起止步骤不在流程模板里")
    left = keys.index(start_key)
    right = keys.index(end_key)
    if left > right:
        raise ValueError("起始步骤不能晚于结束步骤")
    segment = steps[left:right + 1]
    current = []
    max_round = 1
    if isinstance(progress, list):
        for item in progress:
            if not isinstance(item, dict):
                continue
            row = normalize_progress(item)
            current.append(row)
            if row["轮次"] > max_round:
                max_round = row["轮次"]
    current.extend(blank_progress(segment, max_round + 1))
    return current


def flow_text_from_steps(steps: list[dict]) -> str:
    lines = []
    for step in steps:
        step = normalize_step(step)
        parts = [step["键"], step["单据"], step["动作"], step["角色"], step.get("标题", "")]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def steps_from_flow_text(text: str) -> list[dict]:
    if text is None:
        return []
    steps = []
    seen = set()
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        while len(parts) < 5:
            parts.append("")
        step = normalize_step({
            "键": parts[0],
            "单据": parts[1],
            "动作": parts[2],
            "角色": parts[3],
            "标题": parts[4],
        })
        roles = set(role_names())
        if roles and step["角色"] not in roles:
            raise ValueError(f"角色不在角色表里：{step['角色']}")
        if step["键"] in seen:
            raise ValueError(f"标准流程的键重复：{step['键']}")
        seen.add(step["键"])
        steps.append(step)
    return steps


def write_fee_flow(stem: str, steps: list[dict]):
    path = kind_dir("fees") / f"{stem}.md"
    data, body = read_note(path) if path.exists() else ({}, "\n")
    data = dict(data)
    data["A-标准流程"] = clone_steps(steps)
    write_note(path, data, body)


def bootstrap_fee_flows():
    """把计划中的初始步骤写入各报销模板。已有非空标准流程的不覆盖。"""
    mapping = {
        "集团课题劳务费-内部": ERP_GREEN + WHITE_INTERNAL,
        "集团课题劳务费-外部-集团内": ERP_GREEN + WHITE_EXTERNAL,
        "集团课题劳务费-外部-集团外": ERP_GREEN + WHITE_EXTERNAL,
        "非政府委托课题劳务费-集团外": ERP_GREEN + WHITE_EXTERNAL,
        "集团课题知识产权费": ERP_GREEN,
        "非政府委托课题知识产权费": ERP_GREEN,
    }
    for stem, steps in mapping.items():
        path = kind_dir("fees") / f"{stem}.md"
        if not path.exists():
            continue
        data, body = read_note(path)
        existing = data.get("A-标准流程")
        if isinstance(existing, list) and existing:
            continue
        data = dict(data)
        data["A-标准流程"] = clone_steps(steps)
        write_note(path, data, body)
