"""lsf —— LocalShareFile 命令行客户端：在终端直接访问服务器。

用法：
    lsf ls  http://192.168.1.10:8000/              # 列出服务器上的共享目录
    lsf ls  http://192.168.1.10:8000/s/电影/        # 列出目录内容
    lsf get http://192.168.1.10:8000/s/电影/a.mp4   # 下载文件（-c 断点续传，-o 指定保存名）
    lsf get http://192.168.1.10:8000/s/电影/喜剧/   # 下载整个目录（服务端打包为 ZIP）
    lsf put http://192.168.1.10:8000/s/电影/ a.mp4  # 上传文件到该目录（可多个）
    所有子命令均可用 --token 传递访问口令。

纯标准库实现，无需额外依赖。
"""
import argparse
import http.client
import json
import os
import sys
import time
import urllib.parse
from contextlib import contextmanager
from datetime import datetime

from . import __version__


class ClientError(Exception):
    """客户端错误（网络/认证/协议）。"""


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


class Client:
    """极简 HTTP 客户端：http.client 直连，token 登录后以 Cookie 鉴权。"""

    def __init__(self, base_url: str, token: str = ""):
        u = urllib.parse.urlparse(base_url if "://" in base_url else "http://" + base_url)
        if not u.hostname:
            raise ClientError(f"无效的服务器地址：{base_url}")
        self.host = u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.scheme = u.scheme or "http"
        self.token = (token or "").strip()
        self.cookie = ""
        if self.token:
            self._login()

    # ---- 基础 ----

    def _conn(self, timeout: int = 60) -> http.client.HTTPConnection:
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(self.host, self.port, timeout=timeout)

    @contextmanager
    def _open(self, timeout: int = 60):
        """HTTPConnection 不支持 with 语法，这里包一层。"""
        conn = self._conn(timeout)
        try:
            yield conn
        finally:
            conn.close()

    def _headers(self, extra: dict = None) -> dict:
        h = {"User-Agent": f"lsf/{__version__}"}
        if self.cookie:
            h["Cookie"] = self.cookie
        h.update(extra or {})
        return h

    def _login(self):
        with self._open(15) as conn:
            conn.request("GET", f"/?token={urllib.parse.quote(self.token)}",
                         headers=self._headers())
            resp = conn.getresponse()
            resp.read()
            if resp.status not in (200, 303):
                raise ClientError(f"口令校验失败（HTTP {resp.status}）")
            sc = resp.getheader("Set-Cookie") or ""
            if "lsf_token=" in sc:
                self.cookie = sc.split(";")[0]

    def _read_json(self, path: str) -> dict:
        with self._open() as conn:
            conn.request("GET", path, headers=self._headers())
            resp = conn.getresponse()
            body = resp.read()
        if resp.status != 200:
            try:
                err = json.loads(body).get("error", "")
            except ValueError:
                err = body[:120].decode("utf-8", "replace")
            raise ClientError(f"HTTP {resp.status}：{err}")
        return json.loads(body)

    # ---- API ----

    def list_shares(self) -> list:
        return self._read_json("/api/ls?p=/")["shares"]

    def list_dir(self, path: str) -> dict:
        """path 形如 /s/共享名/子路径（无需尾斜杠）。"""
        return self._read_json("/api/ls?p=" + urllib.parse.quote(path))

    def download_file(self, url_path: str, out: str, resume: bool = False,
                      progress=print) -> str:
        """流式下载文件；resume=True 时从本地已有大小续传。"""
        start = 0
        mode = "wb"
        if resume and os.path.exists(out):
            start = os.path.getsize(out)
            mode = "ab"
        headers = self._headers()
        if start:
            headers["Range"] = f"bytes={start}-"
        with self._open() as conn:
            conn.request("GET", urllib.parse.quote(url_path, safe="/"), headers=headers)
            resp = conn.getresponse()
            if resp.status == 404:
                resp.read()
                raise ClientError(f"文件不存在：{url_path}")
            if resp.status not in (200, 206):
                resp.read()
                raise ClientError(f"下载失败：HTTP {resp.status}")
            if resp.status == 200 and start:      # 服务器不支持续传，重写
                start, mode = 0, "wb"
            total = int(resp.getheader("Content-Length") or 0) + start
            done = start
            t0 = time.time()
            with open(out, mode) as f:
                while True:
                    buf = resp.read(256 * 1024)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    if progress and total:
                        speed = done / max(time.time() - t0, 0.001)
                        progress(f"\r{out}  {human_size(done)}/{human_size(total)}"
                                 f"  {human_size(speed)}/s", end="")
                if progress and total:
                    progress("")
        return out

    def download_zip(self, share_rel: str, out: str = None) -> str:
        """把目录（share_rel 形如 '共享名/子路径'）打包下载为 ZIP，默认存为 目录名.zip。"""
        if not out:
            out = (share_rel.rstrip("/").rsplit("/", 1)[-1] or share_rel) + ".zip"
        form = ("p=" + urllib.parse.quote(share_rel)).encode()
        headers = self._headers({"Content-Type": "application/x-www-form-urlencoded",
                                 "Content-Length": str(len(form))})
        with self._open(timeout=300) as conn:
            conn.request("POST", "/zip", body=form, headers=headers)
            resp = conn.getresponse()
            if resp.status != 200:
                resp.read()
                raise ClientError(f"打包下载失败：HTTP {resp.status}")
            disp = resp.getheader("Content-Disposition") or ""
            if "filename*=UTF-8''" in disp and not out:
                out = urllib.parse.unquote(disp.split("filename*=UTF-8''")[1].split(";")[0])
            out = out or "download.zip"
            total = int(resp.getheader("Content-Length") or 0)
            done = 0
            t0 = time.time()
            with open(out, "wb") as f:
                while True:
                    buf = resp.read(256 * 1024)
                    if not buf:
                        break
                    f.write(buf)
                    done += len(buf)
                    if total:
                        speed = done / max(time.time() - t0, 0.001)
                        print(f"\r{out}  {human_size(done)}/{human_size(total)}"
                              f"  {human_size(speed)}/s", end="")
            if total:
                print()
        return out

    def upload(self, dir_param: str, filepath: str) -> str:
        """上传本地文件到目录（dir_param 形如 '共享名/子路径'），流式发送带进度。"""
        size = os.path.getsize(filepath)
        name = os.path.basename(filepath)
        query = urllib.parse.quote(dir_param, safe="")
        url = f"/upload?dir={query}&name={urllib.parse.quote(name)}"
        headers = self._headers({"Content-Length": str(size)})
        done = 0
        t0 = time.time()
        with open(filepath, "rb") as f, self._open(timeout=300) as conn:
            conn.putrequest("PUT", url)
            for k, v in headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            while True:
                buf = f.read(256 * 1024)
                if not buf:
                    break
                conn.send(buf)
                done += len(buf)
                speed = done / max(time.time() - t0, 0.001)
                print(f"\r上传 {name}  {human_size(done)}/{human_size(size)}"
                      f"  {human_size(speed)}/s", end="")
            resp = conn.getresponse()
            body = resp.read()
        print()
        if resp.status != 200:
            raise ClientError(f"上传失败：HTTP {resp.status} {body[:120].decode('utf-8', 'replace')}")
        return json.loads(body).get("saved", name)


def _parse_share_path(url: str) -> tuple:
    """从 'http://host:port/s/共享名/子路径[/]' 提取 (共享名/子路径, 是否目录)。"""
    u = urllib.parse.urlparse(url if "://" in url else "http://" + url)
    p = u.path or "/"
    if not p.startswith("/s/"):
        raise ClientError("URL 需指向共享目录，形如 http://host:port/s/共享名/[子路径/]")
    rel = p[len("/s/"):].rstrip("/")
    return rel, p.endswith("/")


# ---- 子命令 ----

def cmd_ls(args):
    c = Client(args.url, args.token)
    u = urllib.parse.urlparse(args.url if "://" in args.url else "http://" + args.url)
    if (u.path or "/") in ("", "/"):
        shares = c.list_shares()
        print(f"共 {len(shares)} 个共享目录：")
        for s in shares:
            print(f"  /s/{s['name']}/".ljust(42) + s["path"])
        print("\n用 lsf ls http://<host>/s/<共享名>/ 查看目录内容")
        return 0
    data = c.list_dir(u.path)
    entries = data["entries"]
    if not entries:
        print("（空目录）")
        return 0
    print(f"{'名称':<40} {'大小':>10}  {'修改时间':<16} 类型")
    for e in entries:
        mtime = datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M")
        size = "—" if e["dir"] else human_size(e["size"])
        print(f"{(e['name'] + '/' if e['dir'] else e['name']):<40} {size:>10}  {mtime:<16} "
              f"{'目录' if e['dir'] else '文件'}")
    return 0


def cmd_get(args):
    rel, is_dir = _parse_share_path(args.url)
    c = Client(args.url, args.token)
    if is_dir:
        out = c.download_zip(rel, args.output)
        print(f"✅ 目录已打包下载：{out}")
        return 0
    u = urllib.parse.urlparse(args.url if "://" in args.url else "http://" + args.url)
    out = args.output or os.path.basename(u.path) or "download.bin"
    c.download_file(u.path, out, resume=args.continue_)
    print(f"✅ 已下载：{out}（{human_size(os.path.getsize(out))}）")
    return 0


def cmd_put(args):
    rel, is_dir = _parse_share_path(args.url)
    if not is_dir:
        print("提示：目标 URL 不以 / 结尾，已按目录处理（上传目录请以 / 结尾）", file=sys.stderr)
    c = Client(args.url, args.token)
    for fp in args.files:
        if not os.path.isfile(fp):
            print(f"❌ 跳过不存在的文件：{fp}", file=sys.stderr)
            return 1
        saved = c.upload(rel, fp)
        print(f"✅ 已上传：{fp} → {saved}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="lsf",
        description="LocalShareFile 命令行客户端 —— 在终端访问 LocalShareFile 服务器"
                    "（列目录 / 下载文件或目录 / 上传文件）")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(sp):
        sp.add_argument("url", help="服务器地址，如 http://192.168.1.10:8000/s/电影/")
        sp.add_argument("--token", default="", help="访问口令（服务器启用口令时需要）")

    sp = sub.add_parser("ls", help="列出共享目录 / 目录内容")
    add(sp)

    sp = sub.add_parser("get", help="下载文件（或目录，自动打包 ZIP）")
    add(sp)
    sp.add_argument("-o", "--output", help="保存路径（默认当前目录/原名）")
    sp.add_argument("-c", dest="continue_", action="store_true", help="断点续传")

    sp = sub.add_parser("put", help="上传文件到指定目录")
    add(sp)
    sp.add_argument("files", nargs="+", help="要上传的本地文件（可多个）")

    args = p.parse_args(argv)
    try:
        return {"ls": cmd_ls, "get": cmd_get, "put": cmd_put}[args.cmd](args)
    except ClientError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except (OSError, KeyboardInterrupt) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
