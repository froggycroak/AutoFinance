"use strict";

const vscode = require("vscode");

const LINK_RE = /\[\[([^\[\]\n]+)\]\]/g;
const NOTE_GLOB = "data/repo.*/**/*.md";

function stemOf(uri) {
  const base = decodeURIComponent(uri.path.split("/").pop() || "");
  return base.replace(/\.md$/i, "");
}

function frontmatterId(text) {
  if (!text.startsWith("---")) return "";
  const end = text.indexOf("\n---", 3);
  if (end < 0) return "";
  const match = text.slice(3, end).match(/^id:[ \t]*(.*)$/m);
  if (!match) return "";
  let value = match[1].trim();
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    value = value.slice(1, -1).trim();
  }
  return value;
}

function linkKey(body) {
  let target = body.split("|", 1)[0].trim();
  const cut = target.search(/[#^]/);
  if (cut >= 0) target = target.slice(0, cut).trim();
  target = target.replace(/\\/g, "/");
  if (target.toLowerCase().endsWith(".md")) target = target.slice(0, -3);
  if (target.includes("/")) target = target.split("/").pop();
  return target;
}

function fenceSpans(text) {
  const spans = [];
  let open = -1;
  const fence = /^[ \t]{0,3}(`{3,}|~{3,})/gm;
  let match;
  while ((match = fence.exec(text))) {
    if (open < 0) {
      open = match.index;
      continue;
    }
    const lineEnd = text.indexOf("\n", match.index);
    spans.push([open, lineEnd < 0 ? text.length : lineEnd + 1]);
    open = -1;
  }
  if (open >= 0) spans.push([open, text.length]);
  return spans;
}

function inside(spans, index) {
  return spans.some(([start, end]) => index >= start && index < end);
}

class WikiLinks {
  constructor() {
    this.generation = 0;
    this.cached = null;
  }

  invalidate() {
    this.generation += 1;
    this.cached = null;
  }

  async index() {
    const generation = this.generation;
    if (this.cached && this.cached.generation === generation) return this.cached.map;
    const files = await vscode.workspace.findFiles(NOTE_GLOB, "**/{node_modules,.git}/**");
    const map = new Map();
    for (const uri of files) {
      const stem = stemOf(uri);
      if (!stem || stem.startsWith("_")) continue;
      const bytes = await vscode.workspace.fs.readFile(uri);
      const text = Buffer.from(bytes).toString("utf8");
      const ident = frontmatterId(text);
      map.set(stem, uri);
      if (ident) map.set(ident, uri);
    }
    if (this.generation === generation) this.cached = { generation, map };
    return map;
  }

  async linksIn(document) {
    const map = await this.index();
    const text = document.getText();
    const skip = fenceSpans(text);
    const found = [];
    LINK_RE.lastIndex = 0;
    let match;
    while ((match = LINK_RE.exec(text))) {
      if (inside(skip, match.index)) continue;
      const key = linkKey(match[1]);
      if (!key || key === "") continue;
      const uri = map.get(key);
      if (!uri) continue;
      found.push({
        start: match.index,
        end: match.index + match[0].length,
        uri,
      });
    }
    return found;
  }

  async provideDocumentLinks(document) {
    const links = [];
    for (const item of await this.linksIn(document)) {
      const link = new vscode.DocumentLink(
        new vscode.Range(document.positionAt(item.start), document.positionAt(item.end)),
        item.uri
      );
      link.tooltip = vscode.workspace.asRelativePath(item.uri);
      links.push(link);
    }
    return links;
  }

  async provideDefinition(document, position) {
    const offset = document.offsetAt(position);
    for (const item of await this.linksIn(document)) {
      if (offset >= item.start && offset < item.end) {
        return new vscode.Location(item.uri, new vscode.Position(0, 0));
      }
    }
    return null;
  }
}

function activate(context) {
  const wiki = new WikiLinks();
  const selector = [{ language: "markdown" }, { language: "yaml" }];
  context.subscriptions.push(
    vscode.languages.registerDocumentLinkProvider(selector, wiki),
    vscode.languages.registerDefinitionProvider(selector, wiki),
    vscode.workspace.onDidCreateFiles(() => wiki.invalidate()),
    vscode.workspace.onDidDeleteFiles(() => wiki.invalidate()),
    vscode.workspace.onDidRenameFiles(() => wiki.invalidate()),
    vscode.workspace.onDidSaveTextDocument((document) => {
      if (document.languageId === "markdown" || document.languageId === "yaml") {
        wiki.invalidate();
      }
    })
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
