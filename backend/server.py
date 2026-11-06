# -*- coding: utf-8 -*-
"""本地网页服务。

/api 返回 JSON，/doc 返回单据，其余页面都是 frontend/ 里的静态文件。
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from openpyxl.utils.exceptions import InvalidFileException

from .api import HttpError, dispatch
from .excel_pdf import render_sheet, workbook_sheets
from .render_erp import META, esc
from .documents import DocumentError, open_doc
from .store import safe_stem

HOST = "127.0.0.1"
PORT = 8766
MAX_XLSX = 20 * 1024 * 1024
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

ASSETS = {
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/sheet.css": ("sheet.css", "text/css; charset=utf-8"),
}


class App(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path
        parts = [unquote(part) for part in path.split("/") if part]
        try:
            if path.startswith("/api/"):
                self._api("GET")
                return
            if path in ASSETS:
                self._asset(path)
                return
            if parts and parts[0] == "doc":
                self._doc(parts)
                return
            if parts and "." in parts[-1]:
                self._send("没有这一页".encode("utf-8"), 404, "text/plain; charset=utf-8")
                return
            self._file(FRONTEND / "index.html", "text/html; charset=utf-8")
        except Exception as exc:
            self._send(f"<p>{esc(exc)}</p>".encode("utf-8"), 500,
                       "text/html; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if path in {"/api/print/sheets", "/api/print/pdf"}:
            self._print(path)
            return
        self._api("POST")

    def do_PUT(self):
        self._api("PUT")

    def _api(self, method: str):
        parts = [
            unquote(part) for part in urlparse(self.path).path.split("/")
            if part
        ]
        try:
            payload = self._json() if method in {"POST", "PUT"} else None
            result = dispatch(method, parts, payload)
        except HttpError as exc:
            self._json_out({"error": str(exc)}, exc.status)
            return
        except ValueError as exc:
            self._json_out({"error": str(exc)}, 400)
            return
        except Exception as exc:
            self._json_out({"error": str(exc)}, 500)
            return
        self._json_out(result)

    def _doc(self, parts: list[str]):
        try:
            if len(parts) != 3:
                raise DocumentError("没有这一页")
            body = open_doc(parts[1], safe_stem(parts[2]))
        except DocumentError as exc:
            self._send(f"<p>{esc(exc)}</p>".encode("utf-8"), exc.status,
                       "text/html; charset=utf-8")
            return
        except ValueError as exc:
            self._send(f"<p>{esc(exc)}</p>".encode("utf-8"), 400,
                       "text/html; charset=utf-8")
            return
        except Exception as exc:
            self._send(f"<p>{esc(exc)}</p>".encode("utf-8"), 500,
                       "text/html; charset=utf-8")
            return
        self._send(body, 200, "text/html; charset=utf-8")

    def _asset(self, path: str):
        name, content_type = ASSETS[path]
        self._file(FRONTEND / name, content_type)

    def _file(self, path: Path, content_type: str):
        if not path.is_file():
            self._send("没有这一页".encode("utf-8"), 404, "text/plain; charset=utf-8")
            return
        self._send(path.read_bytes(), 200, content_type)

    def _print(self, path: str):
        query = parse_qs(urlparse(self.path).query)
        try:
            data = self._bytes(MAX_XLSX)
            if not data.startswith(b"PK"):
                raise ValueError("请上传 xlsx 文件")
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "book.xlsx"
                src.write_bytes(data)
                if path.endswith("/sheets"):
                    self._json_out(workbook_sheets(src))
                    return
                picked = (query.get("sheet") or [""])[0].strip()
                pdf = Path(tmp) / "out.pdf"
                info = render_sheet(src, picked or None, pdf)
                payload = pdf.read_bytes()
            name = _pdf_name((query.get("file") or [""])[0], info["sheet"])
        except HttpError as exc:
            self._json_out({"error": str(exc)}, exc.status)
            return
        except ValueError as exc:
            self._json_out({"error": str(exc)}, 400)
            return
        except KeyError:
            self._json_out({"error": "没有这个工作表"}, 400)
            return
        except (zipfile.BadZipFile, InvalidFileException):
            self._json_out({"error": "这个 xlsx 打不开"}, 400)
            return
        except Exception as exc:
            self._json_out({"error": str(exc)}, 500)
            return
        self._send(
            payload,
            200,
            "application/pdf",
            {"Content-Disposition": _attachment(name)},
        )

    def _bytes(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            raise ValueError("请上传 xlsx")
        if length > limit:
            raise ValueError("文件太大")
        return self.rfile.read(length)

    def _json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("请求格式不对")
        if not isinstance(data, dict):
            raise ValueError("请求格式不对")
        return data

    def _json_out(self, payload, status: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(body, status, "application/json; charset=utf-8")

    def _send(self, payload: bytes, status: int, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def _pdf_name(raw: str, sheet: str) -> str:
    stem = Path(raw).stem or "表格"
    stem = "".join("-" if ch in '\\/:*?"<>|' or ord(ch) < 32 else ch for ch in stem)
    stem = stem.strip(" .") or "表格"
    sheet_name = "".join("-" if ch in '\\/:*?"<>|' or ord(ch) < 32 else ch for ch in sheet)
    sheet_name = sheet_name.strip(" .") or "sheet"
    return f"{stem}-{sheet_name}.pdf"


def _attachment(name: str) -> str:
    return "attachment; filename=\"print.pdf\"; filename*=UTF-8''" + quote(name)


def main():
    if not META.is_dir():
        raise SystemExit(f"找不到数据仓库：{META}")
    server = ThreadingHTTPServer((HOST, PORT), App)
    print(f"数据仓库 {META}")
    print(f"http://{HOST}:{PORT}")
    server.serve_forever()
