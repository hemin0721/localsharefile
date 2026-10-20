"""HTTP 服务器核心：多目录浏览、FTP 式多选下载、流式上传、网页远程目录管理。

仅使用 Python 标准库，无任何第三方依赖。

路由一览：
    GET  /                        首页：共享目录卡片 / 常用 / 最近访问
    GET  /s/{共享名}/[子路径/]     目录浏览页（或文件下载，支持 Range）
    PUT  /upload?dir=共享名/子目录&name=文件名    流式上传
    POST /zip                     多选条目打包 ZIP 下载（表单字段 p，可多个）
    GET  /api/browse?path=        浏览服务器磁盘目录（供"添加共享目录"选择器使用）
    PUT  /api/dirs                添加共享目录（JSON: name, path）
    DELETE /api/dirs/{共享名}      移除共享目录
"""
import html
import json
import mimetypes
import os
import re
import shutil
import socket
import tempfile
import threading
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, parse_qs

from . import __version__, config
from . import page as _page
from .state import ShareState

CHUNK = 256 * 1024
TOKEN_COOKIE = "lsf_token"
MAX_ZIP_ITEMS = 2000
MANAGE_LOCK = threading.Lock()   # 保护 cfg/shares 的管理性修改


# ---------------------------------------------------------------- 工具函数

def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def rel_time(epoch: int) -> str:
    """把时间戳渲染为『x 分钟前』式相对时间。"""
    delta = max(int(datetime.now().timestamp()) - int(epoch), 0)
    for span, label in ((86400 * 365, "年"), (86400 * 30, "个月"), (86400 * 7, "周"),
                        (86400, "天"), (3600, "小时"), (60, "分钟")):
        if delta >= span:
            return f"{delta // span} {label}前"
    return "刚刚"


def local_ips() -> list:
    """获取本机所有局域网 IPv4 地址（用于启动时打印访问入口）。"""
    ips = set()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if "." in ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # 不会真正发包，仅用于探测默认路由
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def _fix_latin1(s: str) -> str:
    """修复 http.server 以 latin-1 误读的原始 UTF-8 URL 字节。

    浏览器总是 percent-encode 中文（unquote 后即正确 UTF-8 str，此处原样返回）；
    curl 等工具直接放原始 UTF-8 字节时会被 latin-1 误读，这里尝试还原。
    """
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def sanitize_rel_path(raw: str) -> str:
    """清洗相对路径：解码 URL、去首尾空白与多余分隔符，禁止逃逸共享根目录。

    返回以 / 分隔的规范化相对路径；检测到穿越时抛出 ValueError。
    """
    rel = unquote((raw or "").strip().replace("\\", "/")).lstrip("/")
    parts = []
    for seg in rel.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not parts:
                raise ValueError("path traversal detected")
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


_SAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """清洗上传文件名：去目录部分与非法字符，防止覆盖任意路径。"""
    name = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip().lstrip(".")
    name = _SAFE_NAME.sub("_", name)
    return name[:200] or "unnamed"


def split_share_key(key: str, shares: dict) -> tuple:
    """把 '共享名/子路径' 拆为 (共享名, 规范化相对路径)；共享名不存在抛 ValueError。"""
    key = (key or "").strip("/")
    name, _, rel = key.partition("/")
    if name not in shares:
        raise ValueError(f"unknown share: {name}")
    return name, sanitize_rel_path(rel)


# ---------------------------------------------------------------- 页面渲染

def _share_href(name: str, rel: str = "", is_dir: bool = True) -> str:
    """共享内条目的 URL；目录带尾斜杠（相对链接解析需要），文件不带。"""
    if not rel:
        return f"/s/{quote(name)}/"
    return f"/s/{quote(name)}/{quote(rel)}" + ("/" if is_dir else "")


def _render_home(shares: dict, cfg: dict, state: ShareState) -> bytes:
    counts = {name: state.count(name) for name in shares}

    top_chips = "".join(
        f'<a class="chip" href="{html.escape(_share_href(*k.split("/", 1)))}">'
        f'{html.escape(k.replace("/", " / "))} <b>{n}</b></a>'
        for k, n in state.top(8))

    cards = ""
    for d in sorted(cfg["directories"], key=lambda d: -counts.get(d["name"], 0)):
        name, path = d["name"], d["path"]
        ok = Path(path).is_dir()
        note = f"访问 {counts.get(name, 0)} 次" if ok else "⚠ 服务器上目录不存在"
        cards += (
            f'<div class="cardwrap">'
            f'<a class="card" href="{html.escape(_share_href(name))}" title="{html.escape(path)}">'
            f'<span class="t">{_page.ICON_DIR}{html.escape(name)}</span>'
            f'<span class="p">{html.escape(path)}</span>'
            f'<span class="n">{note}</span></a>'
            f'<button class="del" title="移除共享（不删除文件）" '
            f'data-n="{html.escape(name, quote=True)}" onclick="delDir(this.dataset.n)">✕</button>'
            f'</div>')

    if not cards:
        cards = ('<div class="empty">还没有共享目录。<br>点击右上角 <b>➕ 添加共享目录</b>，'
                 '可以直接浏览服务器磁盘来选择要共享的文件夹。</div>')

    recent = ""
    for key in state.recent_keys(10):
        name, _, rel = key.partition("/")
        if name not in shares:
            continue
        last = state.last_time(key)
        recent += (f'<li><a href="{html.escape(_share_href(name, rel))}">'
                   f'{html.escape(name + ("/" + rel if rel else ""))}</a>'
                   f'<span>{rel_time(last)}</span></li>')
    recent = f'<ul class="recent">{recent}</ul>' if recent else \
        '<div class="empty" style="padding:18px">暂无记录，去目录里逛逛吧</div>'

    doc = _page.render(_page.HOME_PAGE,
                       CSS=_page.BASE_CSS,
                       VERSION=__version__,
                       TOP_CHIPS=top_chips or '<span class="muted" style="font-size:13px">暂无数据</span>',
                       DIR_COUNT=len(cfg["directories"]),
                       DIR_CARDS=cards,
                       RECENT=recent,
                       DATA=_page.json_script({"home": str(Path.home())}))
    return doc.encode("utf-8")


def _render_browse(shares: dict, name: str, rel: str, cfg: dict, state: ShareState) -> bytes:
    cur = shares[name] / rel if rel else shares[name]
    show_hidden = cfg.get("show_hidden", False)
    rows_parts, n_dirs, n_files = [], 0, 0
    try:
        entries = list(os.scandir(cur))
    except OSError:
        entries = []
    for entry in entries:
        if not show_hidden and entry.name.startswith("."):
            continue
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        child = f"{rel}/{entry.name}" if rel else entry.name
        esc_name = html.escape(entry.name)
        pick_val = html.escape(f"{name}/{child}", quote=True)   # /zip 接口的 p 字段格式
        if entry.is_dir(follow_symlinks=False):
            n_dirs += 1
            rows_parts.append((
                entry.name.lower(),
                f'<tr class="rowdir" data-n="{esc_name.lower()}" data-dir="{html.escape(child, quote=True)}">'
                f'<td><input type="checkbox" value="{pick_val}"></td>'
                f'<td class="name"><a href="{html.escape(_share_href(name, child))}">{_page.ICON_DIR}{esc_name}</a></td>'
                f'<td class="muted">—</td><td class="muted">{mtime}</td>'
                f'<td class="op"><button class="linkish" onclick="downloadOne(this.closest(\'tr\').querySelector(\'input\').value)">打包</button></td></tr>'))
        else:
            n_files += 1
            rows_parts.append((
                entry.name.lower(),
                f'<tr data-n="{esc_name.lower()}">'
                f'<td><input type="checkbox" value="{pick_val}"></td>'
                f'<td class="name"><a href="{html.escape(_share_href(name, child, is_dir=False))}" download>{_page.ICON_FILE}{esc_name}</a></td>'
                f'<td>{human_size(stat.st_size)}</td><td class="muted">{mtime}</td>'
                f'<td class="op"><a href="{html.escape(_share_href(name, child, is_dir=False))}" download>下载</a></td></tr>'))

    rows_parts.sort(key=lambda t: t[0])
    rows_html = "".join(r for _, r in rows_parts) or \
        '<tr><td></td><td colspan="4" class="muted" style="text-align:center;padding:30px">（空目录）</td></tr>'

    crumbs = [f'<a href="/">🏠</a> / <a href="/s/{quote(name)}/">{html.escape(name)}</a>']
    acc = []
    for seg in filter(None, rel.split("/")):
        acc.append(seg)
        crumbs.append(f' / <a href="/s/{quote(name)}/{quote("/".join(acc))}/">{html.escape(seg)}</a>')

    hist_opts = ""
    for key in state.recent_keys(10):
        kname, _, krel = key.partition("/")
        if kname not in shares:
            continue
        label = key if len(key) <= 40 else key[:37] + "…"
        hist_opts += f'<option value="{html.escape(_share_href(kname, krel))}">{html.escape(label)}</option>'

    allow_upload = cfg.get("allow_upload", True)
    doc = _page.render(_page.BROWSE_PAGE,
                       CSS=_page.BASE_CSS,
                       TITLE=html.escape(f"{name}/{rel}".rstrip("/")),
                       CRUMBS="".join(crumbs),
                       HIST_OPTIONS=hist_opts,
                       STAT=f"{n_dirs} 个目录 · {n_files} 个文件",
                       UPLOAD_STATE="允许上传" if allow_upload else "只读",
                       UPLOAD_DISABLED="" if allow_upload else "disabled",
                       ROWS=rows_html,
                       VERSION=__version__,
                       DATA=_page.json_script({"share": name, "rel": rel}))
    state.record(f"{name}/{rel}" if rel else name)   # 记录访问历史/频次
    return doc.encode("utf-8")


# ---------------------------------------------------------------- 请求处理

class ShareHandler(BaseHTTPRequestHandler):
    server_version = f"LocalShareFile/{__version__}"
    protocol_version = "HTTP/1.1"
    # 由 make_server 注入：
    shares: dict = None      # 共享名 -> Path（与 cfg["directories"] 同步）
    cfg: dict = None
    state: ShareState = None

    # ---- 基础 ----

    def log_message(self, fmt, *args):  # 精简日志输出
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.client_address[0]} {fmt % args}",
              flush=True)

    def _send_bytes(self, code: int, body: bytes, ctype: str, headers: dict = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send_bytes(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                         "application/json")

    def _error(self, code: int, msg: str):
        self._send_bytes(code, f"<h1>{code}</h1><p>{html.escape(msg)}</p>".encode("utf-8"),
                         "text/html; charset=utf-8")

    def _route_path(self) -> str:
        """解码后的请求路径（兼容 percent-encode 与原始 UTF-8 两种形式）。"""
        return unquote(_fix_latin1(urlparse(self.path).path))

    def _query(self) -> dict:
        qs = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        return {k: _fix_latin1(v[0]) for k, v in qs.items()}

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self) -> dict:
        try:
            return json.loads(self._read_body().decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---- 口令校验 ----

    def _check_token(self) -> bool:
        """校验访问令牌：合法放行；首次携带 ?token= 时种下 Cookie 并重定向。"""
        token = str(self.cfg.get("token") or "")
        if not token:
            return True
        cookies = {}
        for pair in self.headers.get("Cookie", "").split(";"):
            if "=" in pair:
                k, _, v = pair.strip().partition("=")
                cookies[k] = v
        if cookies.get(TOKEN_COOKIE) == token or self._query().get("token") == token:
            if cookies.get(TOKEN_COOKIE) != token:   # 首次：种 Cookie 后重定向到干净 URL
                path = urlparse(self.path).path or "/"
                self.send_response(303)
                self.send_header("Location", quote(path))
                self.send_header("Set-Cookie", f"{TOKEN_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", "0")
                self.end_headers()
            return True
        self._error(401, "访问被拒绝：请在 URL 后附加 ?token=你的口令")
        return False

    # ---- GET ----

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._check_token():
            return
        raw_path = self._route_path()
        q = self._query()

        if raw_path == "/":
            return self._send_bytes(200, _render_home(self.shares, self.cfg, self.state),
                                    "text/html; charset=utf-8")
        if raw_path == "/api/browse":
            return self._api_browse(q.get("path") or str(Path.home()))
        if raw_path.startswith("/s/"):
            return self._serve_share(raw_path)
        self._error(404, "未找到该页面")

    def _serve_share(self, raw_path: str):
        rest = raw_path[len("/s/"):]
        name, _, rel = rest.partition("/")
        if name not in self.shares:
            return self._error(404, f"共享目录「{html.escape(name)}」不存在")
        try:
            rel = sanitize_rel_path(rel)
        except ValueError:
            return self._error(400, "非法路径")
        target = self.shares[name] / rel if rel else self.shares[name]
        if not target.exists():
            return self._error(404, "文件或目录不存在")
        if target.is_dir():
            if not raw_path.endswith("/"):    # 目录规范 URL 带尾斜杠（相对链接依赖）
                self.send_response(301)
                self.send_header("Location", quote(raw_path) + "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._send_bytes(200, _render_browse(self.shares, name, rel, self.cfg, self.state),
                                    "text/html; charset=utf-8")
        return self._serve_file(target)

    def _serve_file(self, target: Path):
        """发送文件，支持 Range 断点续传。"""
        try:
            size = target.stat().st_size
        except OSError:
            return self._error(404, "文件不可访问")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        headers = {"Accept-Ranges": "bytes"}
        if ctype.startswith("application/octet-stream"):
            headers["Content-Disposition"] = \
                f"attachment; filename*=UTF-8''{quote(target.name)}"

        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng or "") if rng else None
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:                                        # bytes=-N（末尾 N 字节）
                start = max(size - int(m.group(2)), 0)
            if start > end or start >= size:
                headers["Content-Range"] = f"bytes */{size}"
                return self._send_bytes(416, b"", "application/octet-stream", headers)
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            code = 206
        else:
            code = 200

        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(target, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                buf = f.read(min(CHUNK, remaining))
                if not buf:
                    break
                self.wfile.write(buf)
                remaining -= len(buf)

    def _api_browse(self, raw: str):
        """列出服务器上某路径的子目录（仅目录名，供添加共享目录的选择器使用）。"""
        p = Path(raw).expanduser()
        try:
            real = p.resolve()
            names = sorted(e.name for e in os.scandir(real)
                           if e.is_dir(follow_symlinks=False)
                           and not e.name.startswith(".") and e.name not in ("$RECYCLE.BIN",))
        except OSError as exc:
            return self._json(400, {"error": f"无法读取：{exc}"})
        crumbs, acc = [], []
        parts = real.parts
        for i, part in enumerate(parts):
            acc.append(part)
            crumbs.append({"name": part or "/", "path": str(Path(*acc))})
        return self._json(200, {"path": str(real), "dirs": names, "crumbs": crumbs})

    # ---- PUT（上传）----

    def do_PUT(self):
        if not self._check_token():
            return
        if self._route_path() == "/api/dirs":   # 网页端添加共享目录
            return self._api_dirs_add()
        if self._route_path() != "/upload":
            return self._error(404, "上传接口为 /upload")
        if not self.cfg.get("allow_upload", True):
            return self._error(403, "服务端已禁用上传")
        q = self._query()
        try:
            share, rel = split_share_key(q.get("dir", ""), self.shares)
        except ValueError as exc:
            return self._error(400, f"非法目标目录：{exc}")
        dest_dir = self.shares[share] / rel if rel else self.shares[share]
        if not dest_dir.is_dir():
            return self._error(404, "目标目录不存在")
        name = sanitize_filename(q.get("name", ""))

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._error(400, "请求体为空")

        dest = dest_dir / name
        n, stem, suffix = 1, dest.stem, dest.suffix
        while dest.exists():                            # 同名冲突自动改名，不覆盖
            dest = dest_dir / f"{stem} ({n}){suffix}"
            n += 1

        received = 0
        try:
            with open(dest, "wb") as f:
                while received < length:
                    buf = self.rfile.read(min(CHUNK, length - received))
                    if not buf:
                        break
                    f.write(buf)
                    received += len(buf)
        except OSError as exc:
            dest.unlink(missing_ok=True)
            return self._error(500, f"写入失败：{exc}")
        if received != length:
            dest.unlink(missing_ok=True)
            return self._error(400, f"上传不完整（{received}/{length}），已丢弃")
        self._json(200, {"ok": True, "saved": dest.name})

    # ---- POST（多选打包 / 目录管理）----

    def do_POST(self):
        if not self._check_token():
            return
        raw_path = self._route_path()
        if raw_path == "/zip":
            return self._serve_zip_multi()
        self._error(404, "未找到该接口")

    def _serve_zip_multi(self):
        """把表单提交的多个路径（字段 p，值 '共享名/相对路径'）打包为 ZIP 下载。"""
        try:
            form = parse_qs(self._read_body().decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return self._error(400, "表单编码错误")
        picks, seen = [], set()
        for raw in form.get("p", [])[:MAX_ZIP_ITEMS]:
            try:
                share, rel = split_share_key(raw, self.shares)
            except ValueError:
                continue
            if (share, rel) in seen:
                continue
            seen.add((share, rel))
            target = self.shares[share] / rel if rel else self.shares[share]
            if target.exists():
                picks.append(target)
        if not picks:
            return self._error(400, "未选择任何有效条目")

        used = set()

        def arcname(p: Path) -> str:
            base = p.name or "share"
            if base not in used:
                used.add(base)
                return base
            stem, suffix = p.stem, p.suffix     # 同名条目自动加序号：name (1).ext
            i = 1
            while True:
                cand = f"{stem} ({i}){suffix}"
                if cand not in used:
                    used.add(cand)
                    return cand
                i += 1

        try:
            with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as tmp:
                with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                    for target in picks:
                        if target.is_file():
                            zf.write(target, arcname(target))
                        else:
                            prefix = arcname(target)   # 先注册目录名，再归档其中文件
                            for p in target.rglob("*"):
                                if p.is_file():
                                    zf.write(p, f"{prefix}/{p.relative_to(target)}")
                size = tmp.seek(0, os.SEEK_END)
                tmp.seek(0)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition",
                                 f"attachment; filename*=UTF-8''{quote('download_' + stamp)}.zip")
                self.end_headers()
                shutil.copyfileobj(tmp, self.wfile, CHUNK)
        except (OSError, zipfile.BadZipFile) as exc:
            self._error(500, f"打包失败：{exc}")

    # ---- 管理接口 ----

    def do_DELETE(self):
        if not self._check_token():
            return
        raw_path = self._route_path()
        if not raw_path.startswith("/api/dirs/"):
            return self._error(404, "未找到该接口")
        name = raw_path[len("/api/dirs/"):]
        with MANAGE_LOCK:
            ok, msg = config.remove_directory(self.cfg, name)
            if ok:
                config.save(self.cfg)
                self.shares.pop(name, None)
                self.state.drop_share(name)
        return self._json(200 if ok else 404, {"ok": ok, "message": msg})

    def _api_dirs_add(self):
        payload = self._read_json()
        with MANAGE_LOCK:
            ok, msg, dirs = config.add_directory(self.cfg,
                                                 payload.get("name", ""), payload.get("path", ""))
            if not ok:
                return self._json(400, {"error": msg})
            self.cfg["directories"] = dirs
            config.save(self.cfg)
            self.shares.clear()
            self.shares.update({d["name"]: Path(d["path"]) for d in dirs})
            return self._json(200, {"ok": True, "message": msg, "name": dirs[-1]["name"]})


# ---------------------------------------------------------------- 服务器装配

class ShareServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(cfg: dict, state: ShareState = None) -> ShareServer:
    """根据配置构建服务器实例；shares/cfg/state 注入 handler 类属性供所有线程共享。"""
    shares = {d["name"]: Path(d["path"]) for d in cfg.get("directories", [])}
    handler = type("BoundHandler", (ShareHandler,),
                   {"shares": shares, "cfg": cfg, "state": state or ShareState()})
    return ShareServer((cfg.get("host") or "0.0.0.0", int(cfg.get("port") or 8000)), handler)


def serve_forever(cfg: dict) -> None:
    """启动服务器并打印访问入口，Ctrl+C 优雅退出。"""
    server = make_server(cfg)
    _, port = server.server_address[:2]
    print(f" * LocalShareFile v{__version__} 已启动")
    dirs = cfg.get("directories", [])
    print(f" * 共享目录（{len(dirs)} 个）：")
    for d in dirs:
        print(f"     - {d['name']}  →  {d['path']}")
    if not dirs:
        print("     （暂无，请在网页首页点击「添加共享目录」配置）")
    print(" * 本机访问:   " + f"http://127.0.0.1:{port}")
    for ip in local_ips():
        print(f" * 局域网访问: http://{ip}:{port}")
    if cfg.get("token"):
        print(" * 已启用口令: 在上述地址后附加 ?token=你的口令")
    print(" * 按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n * 正在停止服务…")
    finally:
        server.server_close()
