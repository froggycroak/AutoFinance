const NAV = [
  { key: "home", href: "/", label: "报销记录", english: "Records" },
  { key: "base", href: "/data/people", label: "基础信息", english: "Basics" },
  { key: "assistant", href: "/assistant", label: "智能助手", english: "Assistant" },
  { key: "tools", href: "/tools", label: "辅助功能", english: "Tools" },
];

const main = document.getElementById("main");
const dialog = document.getElementById("leave-dialog");

let meta = null;
let catalog = null;
let routeSeq = 0;
let pendingForm = null;
let pendingHref = "";

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function href(...parts) {
  return "/" + parts.map((part) => encodeURIComponent(part)).join("/");
}

function pathParts() {
  let path = location.pathname;
  try {
    path = decodeURIComponent(path);
  } catch (error) {
    /* 地址里有坏的百分号时，按原样拆。 */
  }
  return path.split("/").filter(Boolean);
}

function samePath(left, right) {
  try {
    return decodeURIComponent(left) === decodeURIComponent(right);
  } catch (error) {
    return left === right;
  }
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "请求失败");
    error.status = response.status;
    throw error;
  }
  return data;
}

function mount(html, title) {
  document.title = title;
  main.innerHTML = html;
  const recordForm = main.querySelector('form[data-save="record"]');
  if (recordForm) applyFeePanels(recordForm);
  main.querySelectorAll("form[data-list]").forEach((form) => {
    form.dataset.clean = snapshot(form);
  });
}

function snapshot(form) {
  const data = new FormData(form);
  data.delete("after");
  return Array.from(data.entries()).map(([key, value]) => key + "=" + value).join("\n");
}

function renderNav(current) {
  document.getElementById("nav").innerHTML = NAV.map((item) => {
    const mark = item.key === current ? ' class="current"' : "";
    return `<a href="${item.href}"${mark}><span>${esc(item.label)}</span><span class="en">${esc(item.english)}</span></a>`;
  }).join("");
}

function navKey(parts) {
  if (parts[0] === "assistant") return "assistant";
  if (parts[0] === "tools" || parts[0] === "account") return "tools";
  if (parts[0] === "data" && parts[1] && parts[1] !== "records" && meta.kinds[parts[1]]) return "base";
  if (!parts.length || parts[0] === "new" || parts[0] === "r" || (parts[0] === "data" && parts[1] === "records")) return "home";
  return "";
}

function go(path) {
  if (!samePath(location.pathname, path)) history.pushState({}, "", path);
  return route();
}

async function route() {
  const seq = ++routeSeq;
  try {
    const [nextMeta, nextCatalog] = await Promise.all([
      api("GET", "/api/meta"),
      api("GET", "/api/catalog"),
    ]);
    if (seq !== routeSeq) return;
    meta = nextMeta;
    catalog = nextCatalog;
    const parts = pathParts();
    renderNav(navKey(parts));
    await renderView(parts, seq);
  } catch (error) {
    if (seq !== routeSeq) return;
    mount(`<p class="error">${esc(error.message)}</p>`, "出错了");
  }
}

async function renderView(parts, seq) {
  if (!parts.length) {
    await viewHome(seq);
    return;
  }
  if (parts[0] === "new" && parts.length === 1) {
    viewNewRecord();
    return;
  }
  if (parts[0] === "assistant" && parts.length === 1) {
    mount("", "智能助手");
    return;
  }
  if ((parts[0] === "tools" || parts[0] === "account") && parts.length === 1) {
    viewTools();
    return;
  }
  if (parts[0] === "r" && parts.length === 2) {
    await viewRecord(parts[1], seq);
    return;
  }
  if (parts[0] === "data" && parts[1] === "records" && parts.length === 3) {
    if (parts[2] === "_new") {
      viewNewRecord();
      return;
    }
    await viewRecordForm(parts[2], seq);
    return;
  }
  if (parts[0] === "data" && meta.kinds[parts[1]] && parts.length === 2) {
    await viewKind(parts[1], seq);
    return;
  }
  if (parts[0] === "data" && meta.kinds[parts[1]] && parts.length === 3) {
    await viewNote(parts[1], parts[2], seq);
    return;
  }
  mount("<p>没有这一页</p>", "没有这一页");
}

function viewTools() {
  mount(`
<h1>辅助功能</h1>
<section class="tool">
  <h2>表格打印成 PDF</h2>
  <p class="muted">上传一份 xlsx，选择其中一张工作表，导出横向 A4 的 PDF。发放清单和发放说明用的是同一套打印，不用再选表的种类。字超出格子时会自动加高那一行。</p>
  <div class="row">
    <label>表格文件
      <span class="file-pill" id="print-file-pill">
        <input id="print-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet">
        <span class="file-pill-name" id="print-file-name">选择 xlsx</span>
      </span>
    </label>
    <label>工作表
      <select id="print-sheet" disabled>
        <option value="">先选择文件</option>
      </select>
    </label>
  </div>
  <p class="actions"><button type="button" class="primary" id="print-go" disabled>导出 PDF</button></p>
  <p id="print-status" class="muted"></p>
</section>`, "辅助功能");

  const fileInput = document.getElementById("print-file");
  const filePill = document.getElementById("print-file-pill");
  const fileName = document.getElementById("print-file-name");
  const sheetSelect = document.getElementById("print-sheet");
  const button = document.getElementById("print-go");
  const status = document.getElementById("print-status");
  let file = null;

  fileInput.addEventListener("change", async () => {
    file = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
    fileName.textContent = file ? file.name : "选择 xlsx";
    filePill.classList.toggle("has-file", !!file);
    sheetSelect.innerHTML = `<option value="">先选择文件</option>`;
    sheetSelect.disabled = true;
    button.disabled = true;
    status.className = "muted";
    if (!file) {
      status.textContent = "";
      return;
    }
    status.textContent = "正在读取工作表…";
    try {
      const data = await postXlsx("/api/print/sheets", file);
      const names = Array.isArray(data.sheets) ? data.sheets : [];
      if (!names.length) {
        status.textContent = "这个文件里没有工作表";
        return;
      }
      sheetSelect.innerHTML = names.map((name) => (
        `<option value="${esc(name)}"${name === data.active ? " selected" : ""}>${esc(name)}</option>`
      )).join("");
      sheetSelect.disabled = false;
      button.disabled = false;
      status.textContent = "选好工作表后导出 PDF。";
    } catch (error) {
      status.className = "error";
      status.textContent = error.message;
    }
  });

  button.addEventListener("click", async () => {
    if (!file || !sheetSelect.value) return;
    button.disabled = true;
    status.className = "muted";
    status.textContent = "正在生成 PDF…";
    const query = "?sheet=" + encodeURIComponent(sheetSelect.value)
      + "&file=" + encodeURIComponent(file.name);
    try {
      const response = await fetch("/api/print/pdf" + query, {
        method: "POST",
        headers: {
          "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        body: file,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || "导出失败");
      }
      const blob = await response.blob();
      const name = pdfName(response, file.name, sheetSelect.value);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      status.textContent = "已导出 " + name;
    } catch (error) {
      status.className = "error";
      status.textContent = error.message;
    } finally {
      button.disabled = !file;
    }
  });
}

async function postXlsx(path, file) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    body: file,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function pdfName(response, fileName, sheet) {
  const header = response.headers.get("Content-Disposition") || "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch (error) {
      /* 头里的文件名坏了就用本地拼的名字。 */
    }
  }
  const stem = fileName.replace(/\.xlsx$/i, "") || "表格";
  return stem + "-" + sheet + ".pdf";
}

function pageKicker(section) {
  const item = section === "base"
    ? { zh: "基础信息", en: "Basics" }
    : { zh: "报销记录", en: "Records" };
  return `<p class="page-kicker">${item.zh}<span>${item.en}</span></p>`;
}

async function viewHome(seq) {
  const rows = await api("GET", "/api/records");
  if (seq !== routeSeq) return;
  const body = rows.length
    ? rows.map((row) => (
      "<tr>"
      + `<td><a href="${href("r", row.stem)}">${esc(row.stem)}</a></td>`
      + `<td>${esc(row.code)}</td><td>${esc(row.who)}</td><td>${esc(row.fee)}</td>`
      + `<td>${esc(row.amount)}</td><td>${progressMarks(row)}</td>`
      + "</tr>"
    )).join("")
    : "<tr><td colspan='6'>还没有记录</td></tr>";
  mount(`
${pageKicker("records")}
<p class="actions"><a class="button primary" href="/new">新建一条报销</a></p>
<div class="table-wrap"><table class="data">
  <tr><th>记录</th><th>单据编号</th><th>报销人</th><th>任务模板</th><th>总金额</th><th>进度</th></tr>
  ${body}
</table></div>`, "报销记录");
}

function progressMarks(row) {
  const steps = Array.isArray(row.steps) ? row.steps : [];
  if (!steps.length) return esc(row.step || "");
  const boxes = steps.map((item) => {
    const mark = item.done ? ' class="on"' : "";
    return `<span${mark} title="${esc(item.label || "")}"></span>`;
  }).join("");
  return `<span class="prog" title="${esc(row.step || "")}">${boxes}</span>`;
}

function viewNewRecord() {
  renderRecordForm({
    stem: "",
    id: "",
    idExample: meta.idExamples.records,
    fields: {},
    lines: [{}],
  }, "new");
}

async function viewRecordForm(stem, seq) {
  try {
    const data = await api("GET", href("api", "records", stem));
    if (seq !== routeSeq) return;
    renderRecordPage(data, "info");
  } catch (error) {
    if (seq !== routeSeq) return;
    if (error.status === 404) {
      mount(`${pageKicker("records")}<p>${esc(error.message)}</p>`, "没有这条记录");
      return;
    }
    throw error;
  }
}

async function viewRecord(stem, seq) {
  try {
    const data = await api("GET", href("api", "records", stem));
    if (seq !== routeSeq) return;
    renderRecordPage(data);
  } catch (error) {
    if (seq !== routeSeq) return;
    if (error.status === 404) {
      mount(`${pageKicker("records")}<p>${esc(error.message)}</p>`, "没有这条记录");
      return;
    }
    throw error;
  }
}

function flowChoiceOptions(choices, selected) {
  let html = '<option value=""></option>';
  for (const item of choices || []) {
    const mark = item.key === selected ? " selected" : "";
    html += `<option value="${esc(item.key)}"${mark}>${esc(item.label)}</option>`;
  }
  return html;
}

function renderFlowBox(stem, flow) {
  const items = flow?.items || [];
  if (!items.length) {
    return `
<div class="flow-box" data-flow-stem="${esc(stem)}">
  <h2>流程清单</h2>
  <p class="muted">这个任务模板还没有标准流程。可在任务模板里补步骤；未开始勾选前打开本页会重带。</p>
</div>`;
  }
  const body = items.map((item, index) => {
    const round = item.round > 1 ? `<span class="flow-round">第${esc(item.round)}轮</span>` : "";
    const who = item.person || item.role || "";
    const whoHtml = who ? `<span class="flow-who">${esc(who)}</span>` : "";
    const mark = item.done ? " checked" : "";
    const rowClass = item.done ? " flow-done" : "";
    return `<div class="flow-line${rowClass}" data-flow-index="${index}">
  <label class="flow-check"><input type="checkbox" name="done"${mark}></label>
  <span class="flow-step">${esc(item.label)}${round}${whoHtml}</span>
  <input type="text" name="note1" value="${esc(item.note1 || "")}" placeholder="计划时间等">
  <input type="text" name="note2" value="${esc(item.note2 || "")}" placeholder="勾选时可填">
</div>`;
  }).join("");
  return `
<div class="flow-box" data-flow-stem="${esc(stem)}">
  <h2>流程清单</h2>
  <p class="flow-current">当前步骤：<strong data-flow-current>${esc(flow.current || "")}</strong></p>
  <p class="error" data-flow-error></p>
  <div class="flow-list">${body}</div>
  <p class="actions"><button type="button" class="primary" data-flow-save>保存进度</button></p>
  <div class="flow-rework">
    <label>返工起始<select data-flow-start>${flowChoiceOptions(flow.choices)}</select></label>
    <label>返工结束<select data-flow-end>${flowChoiceOptions(flow.choices)}</select></label>
    <button type="button" data-flow-rework>再走一轮</button>
  </div>
  <p class="muted">返工会把选中区段追加到清单末尾，原先勾选保留。</p>
</div>`;
}

function recordDocs(data) {
  const pages = new Set(data.pages || ["green", "erp"]);
  const docs = [];
  if (pages.has("green")) {
    docs.push({ key: "green", label: "绿色单", src: href("doc", "green", data.stem) });
  }
  if (pages.has("erp")) {
    docs.push({ key: "erp", label: "ERP", src: href("doc", "erp", data.stem) });
  }
  if (pages.has("list")) {
    docs.push({ key: "list", label: "发放清单", src: href("doc", "list", data.stem) });
  }
  if (pages.has("note")) {
    docs.push({ key: "note", label: "发放说明", src: href("doc", "note", data.stem) });
  }
  return docs;
}

function recordTabLink(key, label, active, src) {
  const mark = key === active ? ' class="active"' : "";
  const srcAttr = src ? ` data-src="${esc(src)}"` : "";
  return `<a href="#${esc(key)}" data-tab="${esc(key)}"${srcAttr}${mark}>${esc(label)}</a>`;
}

function renderRecordPage(data, active) {
  const fee = data.feeLabel || "未选";
  const docs = recordDocs(data);
  const known = new Set(["flow", "info", ...docs.map((doc) => doc.key)]);
  const tab = known.has(active) ? active : (docs[0] ? docs[0].key : "flow");
  const currentDoc = docs.find((doc) => doc.key === tab);
  const links = [
    recordTabLink("flow", "流程录入", tab),
    recordTabLink("info", "信息录入", tab),
    ...docs.map((doc) => recordTabLink(doc.key, doc.label, tab, doc.src)),
  ];
  const hide = (name) => (tab === name ? "" : " is-hidden");
  mount(`
${pageKicker("records")}
<h1>${esc(data.stem)}</h1>
<p class="muted">任务模板：${esc(fee)}。单据是虚拟预览，还不会提交到 ERP，也不会代替正式用印的表。</p>
<div class="tabs" id="record-tabs">${links.join("")}</div>
<div id="panel-flow" class="record-panel${hide("flow")}">${renderFlowBox(data.stem, data.flow || {})}</div>
<div id="panel-info" class="record-panel${hide("info")}">${recordFormMarkup(data, "edit")}</div>
<div id="panel-doc" class="record-panel${currentDoc ? "" : " is-hidden"}"><iframe name="doc"${currentDoc ? ` src="${currentDoc.src}"` : ""}></iframe></div>`, data.stem);
}

function showRecordTab(key) {
  const bar = document.getElementById("record-tabs");
  if (!bar) return;
  const tabs = Array.from(bar.querySelectorAll("a[data-tab]"));
  const tab = tabs.find((el) => el.dataset.tab === key);
  if (!tab) return;
  tabs.forEach((el) => el.classList.toggle("active", el === tab));
  document.getElementById("panel-flow")?.classList.toggle("is-hidden", key !== "flow");
  document.getElementById("panel-info")?.classList.toggle("is-hidden", key !== "info");
  const docPanel = document.getElementById("panel-doc");
  const frame = docPanel?.querySelector("iframe");
  const src = tab.dataset.src || "";
  if (docPanel) docPanel.classList.toggle("is-hidden", !src);
  if (frame && src) {
    const next = new URL(src, location.origin).href;
    if (frame.src !== next) frame.src = next;
  }
}

function collectFlowItems(box) {
  return Array.from(box.querySelectorAll("[data-flow-index]")).map((row) => ({
    备注1: row.querySelector('[name="note1"]')?.value || "",
    完成: !!(row.querySelector('[name="done"]')?.checked),
    备注2: row.querySelector('[name="note2"]')?.value || "",
  }));
}

async function saveFlowProgress(box) {
  const stem = box.dataset.flowStem;
  const err = box.querySelector("[data-flow-error]");
  if (err) err.textContent = "";
  try {
    const result = await api("PUT", href("api", "records", stem, "flow"), {
      action: "save",
      items: collectFlowItems(box),
    });
    const data = await api("GET", href("api", "records", stem));
    data.flow = result.flow || data.flow;
    renderRecordPage(data, "flow");
  } catch (error) {
    if (err) err.textContent = error.message || "保存失败";
  }
}

async function reworkFlow(box) {
  const stem = box.dataset.flowStem;
  const err = box.querySelector("[data-flow-error]");
  const start = box.querySelector("[data-flow-start]")?.value || "";
  const end = box.querySelector("[data-flow-end]")?.value || "";
  if (err) err.textContent = "";
  if (!start || !end) {
    if (err) err.textContent = "先选返工的起止步骤";
    return;
  }
  try {
    await api("PUT", href("api", "records", stem, "flow"), {
      action: "save",
      items: collectFlowItems(box),
    });
    const result = await api("PUT", href("api", "records", stem, "flow"), {
      action: "rework",
      start,
      end,
    });
    const data = await api("GET", href("api", "records", stem));
    data.flow = result.flow || data.flow;
    renderRecordPage(data, "flow");
  } catch (error) {
    if (err) err.textContent = error.message || "返工失败";
  }
}

function formTable(rows) {
  return `<table class="form"><colgroup><col class="k"><col><col class="k"><col></colgroup>${rows}</table>`;
}

function formRow(cells) {
  const html = cells.map((cell) => {
    const mark = cell.fee ? ` data-fee="${esc(cell.fee)}"` : "";
    return `<th${mark}>${cell.label}</th><td${mark}>${cell.control}</td>`;
  }).join("");
  return `<tr>${html}</tr>`;
}

function fitFormRows(form) {
  form.querySelectorAll("table.form tr").forEach((tr) => {
    const kids = [...tr.children];
    const pairs = [];
    for (let i = 0; i < kids.length; i += 2) {
      const th = kids[i];
      const td = kids[i + 1];
      if (!th || !td || th.tagName !== "TH" || td.tagName !== "TD") return;
      pairs.push([th, td]);
    }
    if (!pairs.length) return;
    const visible = pairs.filter(([th, td]) => !th.hidden && !td.hidden);
    tr.hidden = pairs.every(([th]) => th.dataset.fee) && visible.length === 0;
    for (const [, td] of pairs) td.colSpan = 1;
    if (visible.length === 1) visible[0][1].colSpan = 3;
  });
}

function boxInput(name, value, money, placeholder) {
  const extra = money ? ' inputmode="decimal"' : "";
  const hint = placeholder ? ` placeholder="${esc(placeholder)}"` : "";
  return `<input name="${esc(name)}" value="${esc(value)}"${extra}${hint}>`;
}

function boxArea(name, value, rows, placeholder) {
  const hint = placeholder ? ` placeholder="${esc(placeholder)}"` : "";
  return `<textarea name="${esc(name)}" rows="${rows || 3}"${hint}>${esc(value)}</textarea>`;
}

function boxSelect(name, options) {
  return `<select name="${esc(name)}">${options}</select>`;
}

function entryBlocks(key) {
  if (!key) return [];
  const item = (catalog.fees || []).find((row) => row.key === key);
  return item && Array.isArray(item.blocks) ? item.blocks : [];
}

function applyFeePanels(form) {
  const select = form.elements.namedItem("B-报销模板");
  const key = select ? String(select.value || "") : "";
  const blocks = new Set(entryBlocks(key));
  form.querySelectorAll("[data-fee]").forEach((el) => {
    const name = el.dataset.fee;
    el.hidden = name === "hint" ? !!key : !blocks.has(name);
  });
  fitFormRows(form);
}

function textOf(fields, key) {
  const value = fields?.[key];
  return value == null ? "" : String(value);
}

function selectOptions(kind, selected) {
  const rows = catalog[kind] || [];
  const seen = new Set();
  let html = '<option value=""></option>';
  for (const item of rows) {
    const mark = item.key === selected ? " selected" : "";
    html += `<option value="${esc(item.key)}"${mark}>${esc(item.label)}</option>`;
    seen.add(item.key);
  }
  if (selected && !seen.has(selected)) {
    html += `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
  }
  return html;
}

function budgetOptions(selected) {
  let html = '<option value=""></option>';
  for (const name of meta.budgets) {
    const mark = name === selected ? " selected" : "";
    html += `<option value="${esc(name)}"${mark}>${esc(name)}</option>`;
  }
  return html;
}

function lineBlock(line) {
  return formTable(`
${formRow([
    { label: "人员", control: boxSelect("line_person", selectOptions("people", line["B-人员"] || "")) },
    { label: "人员类别", control: boxInput("line_category", line["A-人员类别"] || "") },
  ])}
${formRow([
    { label: "发放金额", control: boxInput("line_amount", line["A-发放金额"] || "", true) },
    { label: "个人所得税", control: boxInput("line_tax", line["A-个人所得税"] || "", true) },
  ])}
${formRow([
    { label: "工作内容", control: boxInput("line_work", line["A-工作内容"] || "") },
    { label: "成果", control: boxInput("line_result", line["A-成果"] || "") },
  ])}
${formRow([
    { label: "发放事由", control: boxInput("line_reason", line["A-发放事由"] || "") },
    { label: "备注", control: boxInput("line_note", line["A-备注"] || "") },
  ])}
`).replace("<table class=\"form\">", "<table class=\"form line\">");
}

function recordHint(data, mode) {
  if (data.id) return `编号 ${esc(data.id)}。名称可以改，编号不变。`;
  if (mode === "edit") {
    return `名称可以改。第一次改名时生成编号，例如 ${esc(data.idExample)}，已有引用会改认这个编号。`;
  }
  return `保存时生成编号，例如 ${esc(data.idExample)}。名称以后可以改，编号不变。`;
}

function recordFormMarkup(data, mode) {
  const fields = data.fields || {};
  const lines = data.lines && data.lines.length ? data.lines : [{}];
  return `
<p class="actions"><button type="button" data-back-list>回到列表</button></p>
<p class="error" data-error></p>
<form class="entry" method="post" data-list="/" data-save="record" data-mode="${esc(mode)}" data-stem="${esc(data.stem || "")}">
  <input type="hidden" name="after" value="">
  ${formTable(`
${formRow([
    { label: "记录名称", control: `<input name="name" required value="${esc(mode === "new" ? "" : data.stem)}" placeholder="例如 2026-11-数字化专班内部劳务费">` },
    { label: "任务模板", control: boxSelect("B-报销模板", selectOptions("fees", textOf(fields, "B-报销模板"))) },
  ])}
${formRow([
    { label: "单据编号", control: boxInput("A-单据编号", textOf(fields, "A-单据编号")) },
    { label: "报销人", control: boxSelect("B-报销人", selectOptions("people", textOf(fields, "B-报销人"))) },
  ])}
${formRow([
    { label: "报销项目", control: boxSelect("B-报销项目", selectOptions("grants", textOf(fields, "B-报销项目"))) },
    { label: "总金额", control: boxInput("A-总金额", textOf(fields, "A-总金额"), true) },
  ])}
${formRow([
    { label: "付款日期", control: boxInput("A-付款日期", textOf(fields, "A-付款日期")) },
    { label: "预算情况", control: boxSelect("A-预算情况", budgetOptions(textOf(fields, "A-预算情况"))) },
  ])}
${formRow([
    { label: "预算项目", control: boxInput("A-预算项目", textOf(fields, "A-预算项目")) },
    { label: "事由", control: boxArea("A-事由", textOf(fields, "A-事由"), 3) },
  ])}
${formRow([{ label: "供应商", control: boxSelect("B-供应商", selectOptions("vendors", textOf(fields, "B-供应商"))), fee: "供应商" }])}
<tbody data-fee="发放说明">
${formRow([
    { label: "发放时间", control: boxInput("A-发放时间", textOf(fields, "A-发放时间")) },
    { label: "阶段名称", control: boxInput("A-阶段名称", textOf(fields, "A-阶段名称")) },
  ])}
${formRow([
    { label: "成果形式", control: boxInput("A-成果形式", textOf(fields, "A-成果形式")) },
    { label: "阶段计划及目标", control: boxArea("A-阶段计划及目标", textOf(fields, "A-阶段计划及目标"), 3) },
  ])}
</tbody>
`)}
  <p class="muted">${recordHint(data, mode)}</p>
  <p class="muted" data-fee="hint">先选择任务模板。发放说明、劳务人员和供应商按该模板的录入配置出现。</p>
  <div data-fee="劳务人员">
    <h2>劳务人员</h2>
    <p class="muted">有几人加几行。身份证、工号、部门和银行账号从人员档案取，不在这里填。</p>
    <div id="lines">${lines.map(lineBlock).join("")}</div>
    <p class="actions"><button type="button" data-add-line>加一个人</button></p>
  </div>
  <p class="actions">
    <button class="primary" type="submit">保存并生成</button>
    <button type="button" data-back-list>回到列表</button>
  </p>
</form>`;
}

function renderRecordForm(data, mode) {
  const title = mode === "new" ? "新建报销" : data.stem;
  mount(`${pageKicker("records")}<h1>${esc(title)}</h1>${recordFormMarkup(data, mode)}`, title);
}

async function viewKind(kind, seq) {
  const table = await api("GET", href("api", "data", kind));
  if (seq !== routeSeq) return;
  const head = table.columns.map((column) => `<th>${esc(column.label)}</th>`).join("");
  const span = table.columns.length + 1;
  const body = table.rows.length
    ? table.rows.map((row) => (
      `<tr><td><a href="${href("data", kind, row.stem)}">${esc(row.stem)}</a></td>`
      + row.cells.map((cell) => `<td>${esc(cell)}</td>`).join("")
      + "</tr>"
    )).join("")
    : `<tr><td colspan='${span}'>还没有数据</td></tr>`;
  mount(`
${pageKicker("base")}
${baseTabs(kind)}
<p class="actions"><a class="button primary" href="${href("data", kind, "_new")}">新建</a>
<a class="button" href="${href("data", kind, "_template")}">标准模板</a></p>
<div class="table-wrap"><table class="data"><tr><th>名称</th>${head}</tr>
${body}
</table></div>`, table.label);
}

async function viewNote(kind, stem, seq) {
  try {
    const note = await api("GET", href("api", "data", kind, stem));
    if (seq !== routeSeq) return;
    renderNote(note);
  } catch (error) {
    if (seq !== routeSeq) return;
    if (error.status === 404) {
      mount(`${pageKicker("base")}<p>${esc(error.message)}</p>`, "没有这一页");
      return;
    }
    throw error;
  }
}

function baseTabs(kind) {
  const links = Object.entries(meta.kinds).map(([key, label]) => {
    const mark = key === kind ? ' class="active"' : "";
    return `<a href="${href("data", key)}"${mark}>${esc(label)}</a>`;
  });
  return `<div class="kind-tabs">${links.join("")}</div>`;
}

function wanted(key) {
  const name = key.trim();
  if (!name.startsWith("B-")) return null;
  return Object.prototype.hasOwnProperty.call(meta.linkKind, name) ? meta.linkKind[name] : "*";
}

function linkSelect(field, selected) {
  const catalogName = wanted(field) || "*";
  const kinds = catalogName === "*" ? Object.keys(meta.kinds) : [catalogName];
  let inner = '<option value=""></option>';
  const seen = new Set();
  for (const kind of kinds) {
    const items = catalog[kind] || [];
    if (!items.length) continue;
    const options = items.map((item) => {
      seen.add(item.key);
      const mark = item.key === selected ? " selected" : "";
      return `<option value="${esc(item.key)}"${mark}>${esc(item.label)}</option>`;
    }).join("");
    if (catalogName === "*") inner += `<optgroup label="${esc(meta.kinds[kind])}">${options}</optgroup>`;
    else inner += options;
  }
  if (selected && !seen.has(selected)) {
    inner += `<option value="${esc(selected)}" selected>${esc(selected)}</option>`;
  }
  return `<select name="value" data-catalog="${esc(catalogName)}">${inner}</select>`;
}

function valueControl(key, value) {
  if (String(key).startsWith("B-")) return linkSelect(key, value);
  return `<input name="value" value="${esc(value)}">`;
}

const NOTE_ORDER = {
  people: ["__name__", "A-姓名", "A-工号", "A-身份证号", "A-手机号", "B-所属部门", "A-收款开户支行", "A-收款银行账号"],
  departments: ["__name__", "A-部门全称", "A-部门简称", "A-部门简称2", "A-部门编号", "B-所属公司", "B-部门领导", "B-分管领导"],
  grants: ["__name__", "A-项目名称", "A-项目简称", "A-项目类型", "A-项目编号", "A-课题编号", "B-预算类别", "B-项目负责人"],
  companies: ["__name__", "A-公司全称", "A-公司简称", "A-公司编号", "A-税号", "B-总经理", "B-人力资源分管", "B-财务分管", "B-科研分管", "B-科管部门", "B-母公司"],
  fees: ["__name__", "B-费用类型", "B-个税科目", "B-预算类别", "A-录入", "A-ERP", "A-发放清单", "A-发放说明"],
  feetypes: ["__name__", "A-费用类型编号", "A-费用类型简称", "A-费用类型名称"],
  budgets: ["__name__", "A-类别编码", "A-类别名称"],
  taxes: ["__name__", "A-科目编码", "A-科目名称"],
  vendors: ["__name__", "A-供应商全称", "A-供应商简称", "A-税号", "A-开户行", "A-银行账号"],
};

function fieldCaption(key) {
  return String(key || "").replace(/^[AB]-/, "");
}

function layoutNote(note) {
  const fields = note.fields || [];
  const byKey = new Map(fields.map((field) => [field.key, field]));
  const used = new Set();
  const ordered = [];
  for (const key of NOTE_ORDER[note.kind] || []) {
    if (key === "__name__") {
      if (note.mode !== "template") ordered.push({ name: true });
      continue;
    }
    const field = byKey.get(key);
    if (!field) continue;
    used.add(key);
    ordered.push(field);
  }
  if (note.mode !== "template" && !ordered.some((item) => item.name)) ordered.unshift({ name: true });
  for (const field of fields) {
    if (!used.has(field.key)) ordered.push(field);
  }
  const rows = [];
  for (let i = 0; i < ordered.length; i += 2) rows.push(ordered.slice(i, i + 2));
  return rows;
}

function noteCells(field, note, span) {
  const col = span ? ' colspan="3"' : "";
  if (field.name) {
    return `<th>名称</th><td${col}><input name="name" required value="${esc(note.name || "")}"></td>`;
  }
  const head = note.mode === "template"
    ? `<th><input class="as-label" name="key" value="${esc(field.key)}"></th>`
    : `<th>${esc(fieldCaption(field.key))}</th>`;
  const hidden = note.mode === "template"
    ? ""
    : `<input type="hidden" name="key" value="${esc(field.key)}">`;
  return `${head}<td data-field${col}>${hidden}${valueControl(field.key, field.value)}</td>`;
}

function noteTableRows(note) {
  return layoutNote(note).map((fields) => (
    `<tr>${fields.map((field) => noteCells(field, note, fields.length < 2)).join("")}</tr>`
  )).join("");
}

function noteHint(note) {
  if (note.mode === "new") {
    return `字段来自标准模板，用不到的留空。B- 开头从已有档案里点选。要增减字段，先改标准模板。保存时生成编号，例如 ${esc(note.idExample)}。名称以后可以改，编号不变。`;
  }
  if (note.mode === "template") return "这里的字段留空。B- 开头是引用，新建时从已有档案里点选。";
  if (note.id) return `编号 ${esc(note.id)}。名称可以改，编号不变。B- 开头的字段是引用，从已有档案里点选。`;
  return `名称可以改。第一次改名时生成编号，例如 ${esc(note.idExample)}，已有引用会改认这个编号。B- 开头的字段是引用，从已有档案里点选。`;
}

function renderNote(note) {
  const listHref = href("data", note.kind);
  const roles = (meta.roles || []).join("、");
  const flowBlock = note.kind === "fees"
    ? `<tr><th>标准流程</th><td colspan="3"><textarea name="flowText" rows="12" placeholder="一行一步：键 | 单据 | 动作 | 角色 | 标题">${esc(note.flowText || "")}</textarea></td></tr>`
    : "";
  const flowHint = note.kind === "fees"
    ? `<p class="muted">角色须是角色表里的名字${roles ? "：" + esc(roles) : ""}。标题可空。</p>`
    : "";
  mount(`
${pageKicker("base")}
${baseTabs(note.kind)}
<h1>${esc(note.title)}</h1>
<p class="error" data-error></p>
<p class="muted">${noteHint(note)}</p>
<form class="entry" method="post" data-list="${listHref}" data-save="note" data-mode="${esc(note.mode)}" data-kind="${esc(note.kind)}" data-stem="${esc(note.mode === "edit" ? note.stem : "")}">
  <input type="hidden" name="after" value="">
  ${formTable(`${noteTableRows(note)}${flowBlock}`)}
  ${flowHint}
  <p class="actions">
    <button type="button" data-add-field>添加字段</button>
    <button type="button" data-back-list>回到列表</button>
    <button class="primary" type="submit">保存</button>
  </p>
</form>`, note.title);
}

function recordPayload(form) {
  const data = new FormData(form);
  const one = (name) => {
    const values = data.getAll(name);
    return values.length ? String(values[0]) : "";
  };
  const blockOn = (name) => {
    const el = form.querySelector(`[data-fee="${name}"]`);
    return !!(el && !el.hidden);
  };
  const laborOn = blockOn("发放说明");
  const peopleOn = blockOn("劳务人员");
  const vendorOn = blockOn("供应商");
  const people = peopleOn ? data.getAll("line_person").map(String) : [];
  const at = (name, index) => {
    const values = data.getAll(name).map(String);
    return index < values.length ? values[index] : "";
  };
  return {
    name: one("name"),
    "A-单据编号": one("A-单据编号"),
    "A-总金额": one("A-总金额"),
    "A-付款日期": one("A-付款日期"),
    "A-事由": one("A-事由"),
    "A-发放时间": laborOn ? one("A-发放时间") : "",
    "A-阶段名称": laborOn ? one("A-阶段名称") : "",
    "A-阶段计划及目标": laborOn ? one("A-阶段计划及目标") : "",
    "A-成果形式": laborOn ? one("A-成果形式") : "",
    "A-预算情况": one("A-预算情况"),
    "A-预算项目": one("A-预算项目"),
    "B-报销人": one("B-报销人"),
    "B-报销项目": one("B-报销项目"),
    "B-报销模板": one("B-报销模板"),
    "B-供应商": vendorOn ? one("B-供应商") : "",
    lines: people.map((person, index) => ({
      "B-人员": person,
      "A-人员类别": at("line_category", index),
      "A-工作内容": at("line_work", index),
      "A-成果": at("line_result", index),
      "A-发放事由": at("line_reason", index),
      "A-发放金额": at("line_amount", index),
      "A-个人所得税": at("line_tax", index),
      "A-备注": at("line_note", index),
    })),
  };
}

function fieldKeyInput(cell) {
  return cell.querySelector('[name="key"]') || cell.previousElementSibling?.querySelector('[name="key"]');
}

function noteFields(form) {
  const fields = {};
  form.querySelectorAll("[data-field]").forEach((row) => {
    const keyEl = fieldKeyInput(row);
    const valueEl = row.querySelector('[name="value"]');
    if (!keyEl || !valueEl) return;
    const key = keyEl.value.trim();
    if (!key || key === "id") return;
    fields[key] = valueEl.value;
  });
  return fields;
}

function setError(message) {
  const el = document.querySelector("[data-error]");
  if (el) el.textContent = message || "";
}

async function saveForm(form) {
  setError("");
  const mode = form.dataset.mode;
  const kind = form.dataset.kind || "";
  const stem = form.dataset.stem || "";
  try {
    let result;
    if (form.dataset.save === "record") {
      const payload = recordPayload(form);
      result = mode === "new"
        ? await api("POST", "/api/records", payload)
        : await api("PUT", href("api", "records", stem), payload);
    } else {
      const name = form.elements.namedItem("name");
      const payload = { fields: noteFields(form) };
      if (kind === "fees") {
        const flowText = form.elements.namedItem("flowText");
        payload.flowText = flowText ? flowText.value : "";
      }
      if (mode === "template") {
        result = await api("PUT", href("api", "data", kind, "_template"), payload);
      } else if (mode === "new") {
        payload.name = name ? name.value : "";
        result = await api("POST", href("api", "data", kind), payload);
      } else {
        payload.name = name ? name.value : "";
        result = await api("PUT", href("api", "data", kind, stem), payload);
      }
    }
    const after = form.elements.namedItem("after");
    if (after && after.value === "list") {
      await go(form.dataset.list || "/");
      return;
    }
    if (form.dataset.save === "record") {
      await go(href("r", result.stem));
      return;
    }
    if (mode === "template") {
      await go(href("data", kind, "_template"));
      return;
    }
    await go(href("data", kind, result.stem));
  } catch (error) {
    const after = form.querySelector('input[name="after"]');
    if (after) after.value = "";
    setError(error.message || "保存失败");
  }
}

function addLine() {
  const box = document.getElementById("lines");
  const source = box && box.querySelector(".line");
  if (!source) return;
  const copy = source.cloneNode(true);
  copy.querySelectorAll("input").forEach((el) => { el.value = ""; });
  copy.querySelectorAll("select").forEach((el) => { el.selectedIndex = 0; });
  box.appendChild(copy);
}

function buildSelect(catalogName, selected) {
  const select = document.createElement("select");
  select.name = "value";
  select.dataset.catalog = catalogName;
  const blank = document.createElement("option");
  blank.value = "";
  select.appendChild(blank);
  const add = (parent, item) => {
    const opt = document.createElement("option");
    opt.value = item.key;
    opt.textContent = item.label;
    if (item.key === selected) opt.selected = true;
    parent.appendChild(opt);
  };
  const kinds = catalogName === "*" ? Object.keys(meta.kinds) : [catalogName];
  const seen = new Set();
  for (const kind of kinds) {
    const names = catalog[kind] || [];
    if (!names.length) continue;
    const parent = catalogName === "*" ? document.createElement("optgroup") : select;
    if (catalogName === "*") {
      parent.label = meta.kinds[kind];
      select.appendChild(parent);
    }
    for (const item of names) {
      add(parent, item);
      seen.add(item.key);
    }
  }
  if (selected && !seen.has(selected)) add(select, { key: selected, label: selected });
  return select;
}

function addNoteField(form) {
  const table = form && form.querySelector("table.form");
  if (!table) return;
  const cell = '<th><input name="key" placeholder="例如 A-手机号"></th><td data-field><input name="value"></td>';
  const flowRow = table.querySelector('[name="flowText"]')?.closest("tr");
  const rows = [...table.querySelectorAll("tr")].filter((row) => row !== flowRow && row.querySelector("th"));
  const last = rows[rows.length - 1];
  if (last && last.querySelectorAll("th").length < 2) {
    const td = last.querySelector("td");
    if (td) td.colSpan = 1;
    last.insertAdjacentHTML("beforeend", cell);
    const keys = last.querySelectorAll('[name="key"]');
    keys[keys.length - 1]?.focus();
    return;
  }
  const row = document.createElement("tr");
  row.innerHTML = cell.replace("<td ", '<td colspan="3" ');
  if (flowRow) flowRow.before(row);
  else table.appendChild(row);
  row.querySelector('[name="key"]')?.focus();
}

function syncRow(row) {
  const keyInput = fieldKeyInput(row);
  const slot = row.querySelector('[name="value"]');
  if (!keyInput || !slot) return;
  const catalogName = wanted(keyInput.value);
  if (catalogName === null) {
    if (slot.tagName !== "INPUT") {
      const input = document.createElement("input");
      input.name = "value";
      slot.replaceWith(input);
    }
    return;
  }
  if (slot.tagName === "SELECT" && slot.dataset.catalog === catalogName) return;
  slot.replaceWith(buildSelect(catalogName, slot.value));
}

function onBack() {
  const form = document.querySelector("form[data-list]");
  if (!form) return;
  const next = form.getAttribute("data-list") || "/";
  if (snapshot(form) === form.dataset.clean) {
    go(next);
    return;
  }
  pendingForm = form;
  pendingHref = next;
  dialog.showModal();
}

document.body.addEventListener("click", (event) => {
  if (event.target.closest("[data-back-list]")) {
    onBack();
    return;
  }
  if (event.target.closest("[data-add-line]")) {
    addLine();
    return;
  }
  if (event.target.closest("[data-add-field]")) {
    addNoteField(event.target.closest("form"));
    return;
  }
  const flowSave = event.target.closest("[data-flow-save]");
  if (flowSave) {
    const box = flowSave.closest("[data-flow-stem]");
    if (box) saveFlowProgress(box);
    return;
  }
  const flowRework = event.target.closest("[data-flow-rework]");
  if (flowRework) {
    const box = flowRework.closest("[data-flow-stem]");
    if (box) reworkFlow(box);
    return;
  }
  const tab = event.target.closest("#record-tabs a[data-tab]");
  if (tab) {
    event.preventDefault();
    showRecordTab(tab.dataset.tab);
    return;
  }
  const link = event.target.closest("a");
  if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const url = new URL(link.href, location.origin);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/doc/") || url.pathname.startsWith("/api/") || url.pathname.startsWith("/assets/")) return;
  event.preventDefault();
  go(url.pathname);
});

document.body.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement) || target.name !== "B-报销模板") return;
  if (target.form) applyFeePanels(target.form);
});

document.body.addEventListener("input", (event) => {
  const keyInput = event.target;
  if (!(keyInput instanceof HTMLInputElement) || keyInput.name !== "key") return;
  const row = keyInput.closest("td[data-field]") || keyInput.closest("th")?.nextElementSibling;
  if (row) syncRow(row);
});

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.hasAttribute("data-list")) return;
  event.preventDefault();
  saveForm(form);
});

document.addEventListener("invalid", (event) => {
  const form = event.target.form;
  if (!form) return;
  const after = form.querySelector('input[name="after"]');
  if (after) after.value = "";
}, true);

document.getElementById("leave-save").addEventListener("click", () => {
  dialog.close();
  if (!pendingForm) return;
  const after = pendingForm.querySelector('input[name="after"]');
  if (after) after.value = "list";
  if (typeof pendingForm.requestSubmit === "function") pendingForm.requestSubmit();
  else pendingForm.submit();
});

document.getElementById("leave-discard").addEventListener("click", () => {
  dialog.close();
  go(pendingHref || "/");
});

document.getElementById("leave-cancel").addEventListener("click", () => {
  dialog.close();
});

window.addEventListener("popstate", () => {
  if (dialog.open) dialog.close();
  route();
});

route();
