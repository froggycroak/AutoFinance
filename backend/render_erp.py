# -*- coding: utf-8 -*-
"""Render one record's ERP section to a standalone HTML form.

Values come from the selected data repo, composed by that repo's render YAML.
The repo is chosen at startup with AF_REPO (see the start bats).
"""
from __future__ import annotations

import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def resolve_meta() -> Path:
    """定位当前数据仓。仓库根就是档案目录。

    AF_REPO 可以是 repo.sample、sample，或一个目录路径。
    没指定时用 data/repo.sstd；那个目录不在时用 data/repo.sample。
    """
    data = ROOT / "data"
    raw = os.environ.get("AF_REPO", "").strip().strip('"')
    if raw:
        given = Path(raw)
        if given.is_absolute():
            return given
        direct = data / raw
        prefixed = data / raw if raw.startswith("repo.") else data / f"repo.{raw}"
        if direct.is_dir():
            return direct
        if prefixed.is_dir():
            return prefixed
        return direct

    for name in ("repo.sstd", "repo.sample"):
        candidate = data / name
        if candidate.is_dir():
            return candidate
    return data / "repo.sstd"


META = resolve_meta()


def default_record() -> Path:
    folder = META / "records"
    if folder.is_dir():
        files = sorted(
            path for path in folder.glob("*.md") if not path.stem.startswith("_")
        )
        if files:
            return files[0]
    return folder / "record.md"

LINK = re.compile(r"\[\[(.*?)\]\]")
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


class Nodes(dict):
    """按稳定 id 存放档案。没有 id 时，id 就是当前文件名。

    用文件名也能取到同一条：改名之后两种键都有效。
    """

    def __init__(self):
        super().__init__()
        self.labels = {}
        self.by_stem = {}

    def _stable(self, key):
        if dict.__contains__(self, key):
            return key
        return self.by_stem.get(key)

    def get(self, key, default=None):
        stable = self._stable(key)
        if stable is None:
            return default
        return dict.__getitem__(self, stable)

    def __getitem__(self, key):
        stable = self._stable(key)
        if stable is None:
            raise KeyError(key)
        return dict.__getitem__(self, stable)

    def __contains__(self, key):
        return self._stable(key) is not None


def load_nodes():
    nodes = Nodes()
    for path in META.rglob("*.md"):
        if path.stem.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end < 0:
            continue
        data = yaml.safe_load(text[3:end]) or {}
        ident = data.get("id")
        key = path.stem if ident in (None, "") else str(ident).strip()
        nodes[key] = data
        nodes.labels[key] = path.stem
        nodes.by_stem[path.stem] = key
    return nodes


def link_key(text: str) -> str:
    text = text.strip()
    if "|" in text:
        text = text.split("|", 1)[0].strip()
    return text


def link_name(value):
    if not isinstance(value, str):
        return None
    match = LINK.search(value)
    if not match:
        return None
    name = link_key(match.group(1))
    return name or None


def link_label(value, nodes=None) -> str:
    """引用在页面上显示的名字：档案的当前文件名。"""
    key = link_name(value)
    if not key:
        return ""
    labels = getattr(nodes, "labels", None)
    if labels and key in labels:
        return labels[key]
    by_stem = getattr(nodes, "by_stem", None)
    if by_stem and key in by_stem and labels and by_stem[key] in labels:
        return labels[by_stem[key]]
    return key


def resolve_path(path, record, nodes, row):
    path = path.strip()
    if path.startswith("[["):
        match = re.match(r"\[\[(.*?)\]\]\.(.+)", path)
        if not match:
            return ""
        cur = nodes.get(link_key(match.group(1)))
        parts = match.group(2).split(".")
    else:
        parts = path.split(".")
        head, parts = parts[0], parts[1:]
        if head == "this":
            cur = record
        elif head == "row":
            cur = row
        else:
            return ""
    for index, part in enumerate(parts):
        if not isinstance(cur, dict) or part not in cur or cur[part] is None:
            return ""
        value = cur[part]
        last = index == len(parts) - 1
        if part.startswith("B-"):
            target = link_name(value)
            if last:
                return link_label(value, nodes) or ""
            cur = nodes.get(target) if target else None
        elif last:
            if isinstance(value, list):
                if any(isinstance(item, (dict, list)) for item in value):
                    return ""
                return "、".join(
                    str(item).strip() for item in value if item not in (None, "")
                )
            if isinstance(value, dict):
                return ""
            return str(value).strip()
        else:
            return ""
    return ""


_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_SMALL_UNITS = ["", "拾", "佰", "仟"]
_BIG_UNITS = ["", "万", "亿", "兆"]


def _rmb_section(number):
    text = ""
    pending_zero = False
    for index in range(4):
        digit = number % 10
        number //= 10
        if digit == 0:
            if text:
                pending_zero = True
        else:
            if pending_zero:
                text = "零" + text
                pending_zero = False
            text = _DIGITS[digit] + _SMALL_UNITS[index] + text
    return text


def _rmb_integer(number):
    if number == 0:
        return "零"
    groups = []
    while number:
        groups.append(number % 10000)
        number //= 10000
    result = ""
    previous = None
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            continue
        piece = _rmb_section(group) + _BIG_UNITS[index]
        if previous is not None and (previous != index + 1 or group < 1000):
            result += "零"
        result += piece
        previous = index
    return result


def rmb_uppercase(value):
    if value is None or str(value).strip() == "":
        return ""
    amount = Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "负" if amount < 0 else ""
    amount = abs(amount)
    integer = int(amount)
    fraction = int((amount - integer) * 100)
    jiao, fen = divmod(fraction, 10)
    head = sign + _rmb_integer(integer) + "元"
    if jiao == 0 and fen == 0:
        return head + "整"
    if jiao == 0:
        return head + "零" + _DIGITS[fen] + "分"
    text = head + _DIGITS[jiao] + "角"
    if fen == 0:
        return text + "整"
    return text + _DIGITS[fen] + "分"


def rmb_lowercase(value):
    if value is None or str(value).strip() == "":
        return ""
    amount = Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount:,.2f}"


def fill(template, record, nodes, row):
    if not template or isinstance(template, (list, dict)):
        return ""

    def repl(match):
        expr = match.group(1).strip()
        path, _, filt = expr.partition("|")
        value = resolve_path(path.strip(), record, nodes, row)
        filt = filt.strip()
        if filt == "大写":
            return rmb_uppercase(value)
        if filt == "小写":
            return rmb_lowercase(value)
        if filt == "年月":
            digits = re.sub(r"\D", "", value)
            return digits[:6] if len(digits) >= 6 else ""
        return value

    return " ".join(PLACEHOLDER.sub(repl, str(template)).split())


def person_rows(record, nodes):
    """报销明细的每一行。行上的 B-人员 才链到人员档案。"""
    raw = record.get("B-劳务人员")
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if isinstance(item, dict) and link_name(item.get("B-人员")):
            rows.append(item)
    return rows


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def field_cells(names, values):
    count = len(names)
    value_span = (8 // count) - 1 if count and 8 % count == 0 else 1
    cells = []
    for name in names:
        value = values.get(name, "")
        empty = " empty" if not value else ""
        span = f' colspan="{value_span}"' if value_span > 1 else ""
        wide = name in ("事由", "柔性规则信息", "发票证明")
        control = (
            f'<textarea readonly>{esc(value)}</textarea>'
            if wide
            else f'<div class="val">{esc(value)}</div>'
        )
        cells.append(
            f'<th>{esc(name)}</th><td{span} class="{empty.strip()}">{control}</td>'
        )
    return "".join(cells)


def fee_record(fee_name: str, nodes=None) -> dict:
    """任务模板的档案。fee_name 是当前文件名。"""
    if not fee_name:
        return {}
    if nodes is None:
        nodes = load_nodes()
    data = nodes.get(fee_name)
    return data if isinstance(data, dict) else {}


def index_name(fee_name: str, key: str, nodes=None) -> str:
    """任务模板上的渲染索引。空字符串表示这一页不用。"""
    value = fee_record(fee_name, nodes).get(key)
    if value is None:
        return ""
    return str(value).strip()


def load_render(folder: str, name: str):
    """按索引里的文件名读取一份渲染规则。文件名对不上就没有。"""
    if not name:
        return None
    path = META / "render" / folder / f"{name}.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else None


def load_entry(fee_name: str, nodes=None) -> list[str]:
    """信息录入里多出来的块。用任务模板的 A-录入，不看模板自己的文件名。"""
    data = load_render("录入", index_name(fee_name, "A-录入", nodes))
    if not isinstance(data, dict):
        return []
    raw = data.get("块")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def load_erp(fee_name: str, nodes=None):
    """按任务模板的 A-ERP 读取 ERP 规则。没写或文件不在就没有这份单据。"""
    name = index_name(fee_name, "A-ERP", nodes)
    path = META / "render" / "erp" / f"{name}.yaml"
    if not name or not path.is_file():
        raise FileNotFoundError(fee_name or name)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def detail_spec(erp):
    """劳务费用「报销明细」，向供应商打款用「费用明细」。"""
    for key in ("报销明细", "费用明细"):
        if key in erp:
            return key, erp[key]
    raise KeyError("这份 ERP 规则没有明细")


def detail_rows(detail, record, nodes):
    repeat = detail.get("repeat")
    if not repeat:
        return [None]
    if repeat == "this.B-劳务人员":
        return person_rows(record, nodes)
    return []


def render(record_path: Path, write: bool = True):
    nodes = load_nodes()
    record = nodes.get(record_path.stem)
    if record is None:
        raise SystemExit(f"找不到记录：{record_path}")
    fee_name = link_label(record.get("B-报销模板"), nodes)
    erp = load_erp(fee_name, nodes)
    fields = erp["字段"]
    title = erp.get("标题") or "劳务报销单"

    header_rows = []
    for names in erp["基本信息"]:
        values = {name: fill(fields.get(name), record, nodes, None) for name in names}
        header_rows.append(f"<tr>{field_cells(names, values)}</tr>")

    detail_name, detail = detail_spec(erp)
    columns = detail["列"]
    detail_fields = detail["字段"]
    body = []
    for index, row in enumerate(detail_rows(detail, record, nodes), start=1):
        tds = [f"<td>{index}</td>"]
        for name in columns:
            value = fill(detail_fields.get(name), record, nodes, row)
            empty = " empty" if not value else ""
            tds.append(f'<td class="{empty.strip()}">{esc(value)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")

    heads = "".join(f"<th>{esc(name)}</th>" for name in ["序号", *columns])
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{esc(title)} · {esc(record_path.stem)}</title>
<style>
  body {{ margin: 0; background: #eef2f6; color: #1f2933;
    font: 13px/1.4 "Microsoft YaHei", "PingFang SC", sans-serif; }}
  header {{ background: #2b6cb0; color: #fff; padding: 12px 20px; font-size: 16px; }}
  main {{ padding: 16px 20px 32px; }}
  .src {{ margin: 0 0 12px; color: #52606d; }}
  h2 {{ margin: 18px 0 8px; font-size: 14px; font-weight: 600; }}
  h2 span {{ display: inline-block; background: #2b6cb0; color: #fff;
    padding: 4px 14px; border-radius: 2px 2px 0 0; }}
  table {{ border-collapse: collapse; background: #fff; width: 100%; }}
  .sheet th, .sheet td {{ border: 1px solid #d9e2ec; padding: 4px 6px; vertical-align: middle; }}
  .sheet th {{ width: 92px; background: #f5f7fa; color: #52606d; font-weight: 400; text-align: right; white-space: nowrap; }}
  .val, textarea {{ box-sizing: border-box; border: 1px solid #cbd2d9;
    background: #fff; color: #1f2933; font: inherit; padding: 4px 6px; min-height: 26px; }}
  textarea {{ width: 100%; min-height: 52px; resize: vertical; }}
  td.empty .val, td.empty textarea {{ background: #fafbfc; }}
  .grid-wrap {{ overflow-x: auto; background: #fff; border: 1px solid #d9e2ec; }}
  .grid {{ min-width: 1680px; }}
  .grid th, .grid td {{ border: 1px solid #e4e7eb; padding: 6px 8px; white-space: nowrap; }}
  .grid th {{ background: #f5f7fa; color: #52606d; font-weight: 400; text-align: left; }}
  .grid td.empty {{ color: transparent; }}
</style>
</head>
<body>
<header>{esc(title)}</header>
<main>
  <p class="src">{esc(record_path.stem)}</p>
  <h2><span>基本信息</span></h2>
  <table class="sheet">
    {"".join(header_rows)}
  </table>
  <h2><span>{esc(detail_name)}</span></h2>
  <div class="grid-wrap">
    <table class="grid">
      <thead><tr>{heads}</tr></thead>
      <tbody>
        {"".join(body)}
      </tbody>
    </table>
  </div>
</main>
</body>
</html>
"""
    if write:
        out = META / "preview" / f"{record_path.stem}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(out)
    return html


def _print_erp(record_path: Path):
    nodes = load_nodes()
    record = nodes.get(record_path.stem)
    fee_name = link_label(record.get("B-报销模板"), nodes)
    erp = load_erp(fee_name, nodes)
    fields = erp["字段"]
    detail_name, detail = detail_spec(erp)
    columns = detail["列"]
    detail_fields = detail["字段"]
    print(erp.get("标题") or "劳务报销单")
    for names in erp["基本信息"]:
        for name in names:
            print(f"  {name}: {fill(fields.get(name), record, nodes, None)}")
    print(f"  [{detail_name}]")
    for index, row in enumerate(detail_rows(detail, record, nodes), start=1):
        print(f"  明细{index}: " + " | ".join(
            fill(detail_fields.get(name), record, nodes, row) or "-" for name in columns
        ))


def render_green(record_path: Path, write: bool = True):
    nodes = load_nodes()
    record = nodes.get(record_path.stem)
    if record is None:
        raise SystemExit(f"找不到记录：{record_path}")
    rule = yaml.safe_load((META / "render" / "绿色单子.yaml").read_text(encoding="utf-8"))

    def text_of(raw):
        if isinstance(raw, list) or raw is None:
            return ""
        return fill(raw, record, nodes, None)

    title = text_of(rule.get("标题")) or "项目付款凭证"
    brand = rule.get("标识") if isinstance(rule.get("标识"), dict) else {}
    mark = text_of(brand.get("缩写"))
    brand_name = text_of(brand.get("名称"))
    budget = rule["预算情况（3选1）"]
    chosen = text_of(budget.get("选中"))
    checks = []
    for option in budget["选项"]:
        tick = "☑" if option == chosen else "☐"
        checks.append(f'<span class="check">{tick} {esc(option)}</span>')

    signs = []
    sign_rule = rule["签字"]
    for label in ["总经理", "财务经理", "审核", "分管领导", "部门主任", "经办人/领款人"]:
        shown = "经办人\n领款人" if label == "经办人/领款人" else label
        shown = "<br>".join(esc(line) for line in shown.split("\n"))
        klass = "sign tall" if label == "经办人/领款人" else "sign"
        signs.append(
            f'<div class="{klass}"><b>{esc(text_of(sign_rule.get(label)))}</b><span>{shown}</span></div>'
        )

    line_count = 5
    summary = esc(text_of(rule.get("摘要")))
    rows = []
    for index in range(line_count):
        if index == 0:
            cells = [
                f'<td class="summary" rowspan="{line_count}">{summary}</td>',
                f"<td>{esc(text_of(rule.get('预算项目')))}</td>",
                f"<td>{esc(text_of(rule.get('费用类型')))}</td>",
                f"<td>{esc(text_of(rule.get('金额')))}</td>",
            ]
        else:
            cells = ["<td></td>", "<td></td>", "<td></td>"]
        rows.append("<tr>" + "".join(cells) + "</tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{esc(title)} · {esc(record_path.stem)}</title>
<style>
  body {{ margin: 0; background: #eceae4; color: #1c2a1e;
    font: 15px/1.4 "SimSun", "Songti SC", "Microsoft YaHei", serif; }}
  .page {{ padding: 12px; }}
  .slip {{ width: 100%; max-width: 980px; margin: 0 auto; box-sizing: border-box; background: #d5e4cc; border: 2px solid #3f5c46;
    padding: 16px 18px 10px; box-shadow: 0 1px 0 rgba(255,255,255,.4) inset; }}
  .top {{ display: grid; grid-template-columns: 1fr 168px; align-items: end; }}
  h1 {{ margin: 0; text-align: center; font-size: 32px; font-weight: 600; letter-spacing: 0.35em; }}
  .date {{ text-align: center; letter-spacing: 0.7em; margin: 8px 0 10px; }}
  .brand {{ display: flex; align-items: center; gap: 8px; justify-content: flex-end; padding-bottom: 4px; }}
  .mark {{ width: 34px; height: 34px; border: 3px solid #23402c; position: relative; }}
  .mark i {{ position: absolute; left: 8px; top: 4px; width: 16px; height: 22px; border-left: 3px solid #23402c; border-right: 3px solid #23402c; }}
  .brand-text {{ line-height: 1.05; }}
  .brand-text b {{ display: block; font-family: Arial, sans-serif; font-size: 18px; letter-spacing: 0.04em; }}
  .brand-text small {{ font-size: 12px; }}
  .attach {{ text-align: right; letter-spacing: 0.35em; margin-bottom: 8px; }}
  .body {{ display: flex; align-items: stretch; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td {{ border: 1px solid #3f5c46; height: 34px; padding: 2px 8px; background: transparent; }}
  .lab {{ width: 78px; text-align: center; background: #c3d7b8; letter-spacing: 0.15em; white-space: nowrap; }}
  .wide {{ letter-spacing: 0.2em; }}
  .checks {{ letter-spacing: 0; }}
  .check {{ margin-right: 22px; }}
  td.inset {{ padding: 0; }}
  .lines th, .lines td {{ height: 30px; text-align: center; background: #c3d7b8; font-weight: 400; letter-spacing: 0.35em; }}
  .lines td {{ background: transparent; letter-spacing: 0; white-space: nowrap; }}
  .lines td.summary {{ white-space: normal; text-align: left; vertical-align: top; border-bottom: 0; }}
  .lines th:first-child, .lines td:first-child {{ border-left: 0; }}
  .lines th:last-child, .lines td:last-child {{ border-right: 0; }}
  .lines tr:first-child th {{ border-top: 0; }}
  .lines tr:last-child td {{ border-bottom: 0; }}
  .money td.lab {{ width: 130px; letter-spacing: 0.05em; }}
  .signs {{ width: 168px; flex: none; display: flex; flex-direction: column; border-top: 1px solid #3f5c46;
    border-right: 1px solid #3f5c46; border-bottom: 1px solid #3f5c46; }}
  .sign {{ flex: 1; border-bottom: 1px solid #3f5c46; position: relative; min-height: 58px; }}
  .sign.tall {{ min-height: 72px; }}
  .sign:last-child {{ border-bottom: 0; }}
  .sign b {{ position: absolute; left: 8px; right: 8px; top: 8px; text-align: center; font-weight: 400; }}
  .sign span {{ position: absolute; right: 8px; bottom: 5px; letter-spacing: 0.28em; line-height: 1.15; text-align: right; }}
  .note {{ margin: 6px 0 0; font-size: 13px; }}
</style>
</head>
<body>
<div class="page">
  <div class="slip">
    <div class="top">
      <div>
        <h1>{esc(title)}</h1>
        <div class="date">年　　月　　日</div>
      </div>
      <div>
        <div class="brand"><span class="mark"><i></i></span><span class="brand-text"><b>{esc(mark)}</b><small>{esc(brand_name)}</small></span></div>
        <div class="attach">附件　　张</div>
      </div>
    </div>
    <div class="body">
      <table>
        <tr>
          <td class="lab">部门</td><td>{esc(text_of(rule.get("部门")))}</td>
          <td class="lab">姓名</td><td>{esc(text_of(rule.get("姓名")))}</td>
          <td class="lab">联系电话</td><td>{esc(text_of(rule.get("联系电话")))}</td>
        </tr>
        <tr>
          <td class="lab">项目编号</td><td>{esc(text_of(rule.get("项目编号")))}</td>
          <td class="lab wide">项目名称</td><td colspan="3">{esc(text_of(rule.get("项目名称")))}</td>
        </tr>
        <tr>
          <td class="lab">预算情况</td>
          <td class="checks" colspan="5">{"".join(checks)}</td>
        </tr>
        <tr>
          <td class="inset" colspan="6">
            <table class="lines">
              <colgroup><col style="width:24%"><col style="width:28%"><col style="width:28%"><col style="width:20%"></colgroup>
              <tr><th>摘　要</th><th>预算项目</th><th>费用类型</th><th>金　额</th></tr>
              {"".join(rows)}
            </table>
          </td>
        </tr>
        <tr class="money">
          <td class="lab">报销金额（大写）</td><td colspan="2">{esc(text_of(rule.get("报销金额（大写）")))}</td>
          <td class="lab">报销金额（小写）</td><td colspan="2">{esc(text_of(rule.get("报销金额（小写）")))}</td>
        </tr>
      </table>
      <div class="signs">{"".join(signs)}</div>
    </div>
    <p class="note">注：先业务审核，再资金审核，逐级审批。</p>
  </div>
</div>
</body>
</html>
"""
    if write:
        out = META / "preview" / f"{record_path.stem}.绿色单子.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(out)
    return html


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else default_record()
    render(target)
    _print_erp(target)
    render_green(target)
