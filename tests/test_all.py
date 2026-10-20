"""LocalShareFile v0.2 单元 + 集成测试（标准库 unittest）。

覆盖：路径安全、多目录配置与迁移、访问状态统计、多目录 HTTP 行为、
网页远程目录管理 API、多选打包、上传、口令。
"""
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from localsharefile import config, server, state
from localsharefile.server import human_size, rel_time, sanitize_filename, sanitize_rel_path


class TestUtils(unittest.TestCase):
    def test_sanitize_rel_path_blocks_traversal(self):
        """路径穿越（../..、编码分隔符）必须被拒绝。"""
        for bad in ["../../etc/passwd", "/a/../../b", "a/../../.."]:
            with self.assertRaises(ValueError, msg=bad):
                sanitize_rel_path(bad)

    def test_sanitize_rel_path_normalizes(self):
        self.assertEqual(sanitize_rel_path("/sub//dir/"), "sub/dir")
        self.assertEqual(sanitize_rel_path("a/b/../c"), "a/c")
        self.assertEqual(sanitize_rel_path(""), "")
        self.assertEqual(sanitize_rel_path("%E4%B8%AD%E6%96%87"), "中文")

    def test_sanitize_filename_strips_dirs_and_bad_chars(self):
        self.assertEqual(sanitize_filename("../../evil.sh"), "evil.sh")
        self.assertEqual(sanitize_filename("a/b\\c:d"), "c_d")
        self.assertEqual(sanitize_filename("dir/file.txt"), "file.txt")
        self.assertEqual(sanitize_filename("..."), "unnamed")

    def test_human_size_and_rel_time(self):
        import time
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(5 * 1024 * 1024), "5.0 MB")
        self.assertEqual(rel_time(time.time()), "刚刚")
        self.assertEqual(rel_time(time.time() - 3600), "1 小时前")


def _start_server(cfg, state_path=None) -> tuple:
    """在随机端口启动测试服务器，返回 (server, port)。"""
    st = state.ShareState(Path(state_path) if state_path else Path(cfg["_state_tmp"]))
    srv = server.make_server(cfg, st)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


@contextmanager
def _client(port):
    """HTTPConnection 不支持 with 语法，这里包一层上下文管理器。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        yield conn
    finally:
        conn.close()


def _raw_request(port, request_line, body=b""):
    """发送未 percent-encode 的原始 UTF-8 请求行（http.client 不接受非 ASCII 路径）。"""
    import socket as _socket
    with _socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall((f"{request_line} HTTP/1.1\r\nHost: t\r\n"
                   f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode("utf-8") + body)
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, payload = data.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), payload


def _request(port, method, path, body=None, headers=None):
    """发起请求并返回 (status, headers, body_bytes)。"""
    with _client(port) as c:
        c.request(method, path, body=body, headers=headers or {})
        resp = c.getresponse()
        data = resp.read()
        return resp.status, dict(resp.getheaders()), data


class TestConfig(unittest.TestCase):
    def test_save_load_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as td:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = td    # 重定向配置目录，避免污染真实环境
            try:
                cfg = {"port": 9001, "directories": [
                    {"name": "电影", "path": td},
                    {"name": "电影", "path": td},        # 相同路径 → 去重
                ], "token": "abc"}
                path = config.save(cfg)
                self.assertTrue(path.is_file())
                loaded = config.load()
                self.assertEqual(loaded["port"], 9001)
                self.assertEqual([d["name"] for d in loaded["directories"]], ["电影"])
                # 重名不同路径 → 自动加序号
                (sub := Path(td) / "sub").mkdir(exist_ok=True)
                loaded["directories"].append({"name": "电影", "path": str(sub)})
                config.save(loaded)
                names = [d["name"] for d in config.load()["directories"]]
                self.assertEqual(names, ["电影", "电影 (2)"])
                # 旧版 v0.1 单目录配置迁移
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"directory": "/tmp", "port": 7000}, f)
                migrated = config.load()
                self.assertEqual(migrated["directories"],
                                 [{"name": "tmp", "path": "/tmp"}])
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_add_remove_directory(self):
        cfg = {"directories": [], **{k: v for k, v in config.DEFAULTS.items() if k != "directories"}}
        with tempfile.TemporaryDirectory() as td:
            ok, msg, dirs = config.add_directory(cfg, " 临时 ", td)
            self.assertTrue(ok)
            self.assertEqual(dirs[-1]["name"], "临时")
            ok2, _m2, dirs2 = config.add_directory(cfg, "", td + "/nope")
            self.assertFalse(ok2)                       # 不存在的路径被拒绝
            ok3, msg3 = config.remove_directory(cfg, "临时")
            self.assertTrue(ok3)
            self.assertEqual(cfg["directories"], [])
            ok4, _m4 = config.remove_directory(cfg, "不存在")
            self.assertFalse(ok4)


class TestShareState(unittest.TestCase):
    def test_record_top_recent_and_drop(self):
        with tempfile.TemporaryDirectory() as td:
            st = state.ShareState(Path(td) / "s.json")
            for _ in range(3):
                st.record("影视")
            st.record("影视/喜剧")
            st.record("文档")
            self.assertEqual(st.top(2), [("影视", 3), ("影视/喜剧", 1)])
            self.assertEqual(st.recent_keys(), ["文档", "影视/喜剧", "影视"])
            self.assertEqual(st.last_time("影视") > 0, True)
            # 持久化恢复
            st2 = state.ShareState(Path(td) / "s.json")
            self.assertEqual(st2.count("影视"), 3)
            st2.drop_share("影视")
            self.assertEqual(st2.top(), [("文档", 1)])
            self.assertNotIn("影视/喜剧", st2.recent_keys())


class TestHTTPIntegration(unittest.TestCase):
    """多目录路由 / 浏览 / 下载 / 续传 / 上传 / 多选打包 / 管理 API / 状态记录。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "movies").mkdir()
        (root / "movies" / "子目录").mkdir()
        (root / "movies" / "hello.txt").write_bytes(b"0123456789" * 100)
        (root / "movies" / "子目录" / "same.txt").write_bytes(b"B")
        (root / "docs").mkdir()
        (root / "docs" / "same.txt").write_bytes(b"A")  # 与另一个共享里的同名文件
        (root / "docs" / ".hidden").write_text("secret")
        cls.state_file = root / "state.json"
        cls.cfg = {"host": "127.0.0.1", "port": 0,
                   "directories": [{"name": "影视", "path": str(root / "movies")},
                                   {"name": "文档", "path": str(root / "docs")}],
                   "allow_upload": True, "show_hidden": False, "token": ""}
        cls.srv, cls.port = _start_server(cls.cfg, cls.state_file)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def test_home_lists_all_shares(self):
        status, _h, body = _request(self.port, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("影视".encode(), body)
        self.assertIn("文档".encode(), body)
        self.assertIn(b"cardwrap", body)

    def test_share_browse_and_download(self):
        status, _h, body = _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86/")
        self.assertEqual(status, 200)
        self.assertIn(b"hello.txt", body)
        self.assertIn(b"rowdir", body)                   # 子目录行
        # 文件下载（多目录路由）
        status, _h, body = _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86/hello.txt")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"0123456789" * 100)
        # 子目录浏览
        status, _h, body = _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86/%E5%AD%90%E7%9B%AE%E5%BD%95/")
        self.assertEqual(status, 200)
        self.assertIn(b"same.txt", body)

    def test_range_and_404(self):
        status, h, body = _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86/hello.txt",
                                   headers={"Range": "bytes=0-99"})
        self.assertEqual(status, 206)
        self.assertEqual(h["Content-Range"], "bytes 0-99/1000")
        status, _h, _b = _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86/nope")
        self.assertEqual(status, 404)
        status, _h, _b = _request(self.port, "GET", "/s/noshare/")
        self.assertEqual(status, 404)
        # 目录无尾斜杠 → 301
        status, h, _b = _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86")
        self.assertEqual(status, 301)
        self.assertTrue(h["Location"].endswith("/"))

    def test_state_records_visits_and_recent_order(self):
        _request(self.port, "GET", "/s/%E6%96%87%E6%A1%A3/")
        _request(self.port, "GET", "/s/%E6%96%87%E6%A1%A3/")
        _request(self.port, "GET", "/s/%E5%BD%B1%E8%A7%86/%E5%AD%90%E7%9B%AE%E5%BD%95/")
        st = state.ShareState(self.state_file)
        top = dict(st.top(5))
        self.assertGreaterEqual(top.get("文档", 0), 2)
        self.assertEqual(st.recent_keys()[0], "影视/子目录")   # 最近访问在最前

    def test_upload_put_roundtrip(self):
        status, _h, body = _request(
            self.port, "PUT",
            "/upload?dir=%E5%BD%B1%E8%A7%86/%E5%AD%90%E7%9B%AE%E5%BD%95&name=new%20file.bin",
            body=b"UPLOADDATA")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual((Path(self.cfg["directories"][0]["path"]) / "子目录" / "new file.bin")
                         .read_bytes(), b"UPLOADDATA")
        # 穿越目标目录 → 400；不存在共享 → 400
        status, _h, _b = _request(self.port, "PUT", "/upload?dir=../../&name=x", body=b"x")
        self.assertEqual(status, 400)
        status, _h, _b = _request(self.port, "PUT", "/upload?dir=noshare&name=x", body=b"x")
        self.assertEqual(status, 400)

    def test_multi_select_zip(self):
        form = ("p=" + server.quote("影视/hello.txt") + "&p=" + server.quote("文档/same.txt")
                + "&p=" + server.quote("影视/子目录"))
        status, h, body = _request(self.port, "POST", "/zip", body=form.encode(),
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 200)
        self.assertEqual(h["Content-Type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            names = sorted(zf.namelist())
            self.assertIn("hello.txt", names)
            # 两个共享里的同名 same.txt：一个为顶层、另一个随其目录名归档，不互相覆盖
            flat = [n for n in names if n.count("/") == 0]
            self.assertEqual(sorted(flat), ["hello.txt", "same.txt"])
            dir_entries = [n for n in names if n.startswith("子目录/")]
            self.assertIn("子目录/same.txt", dir_entries)
            self.assertEqual(zf.read("same.txt"), b"A")           # 顶层为文档/same.txt
            self.assertEqual(zf.read("子目录/same.txt"), b"B")
        # 无效条目 → 400
        status, _h, _b = _request(self.port, "POST", "/zip", body=b"p=noshare/x",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 400)

    def test_manage_api_add_list_remove(self):
        new_dir = Path(self.tmp.name) / "added"
        new_dir.mkdir()
        # 网页远程添加共享目录
        payload = json.dumps({"name": "新增", "path": str(new_dir)})
        status, _h, body = _request(self.port, "PUT", "/api/dirs", body=payload.encode(),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        status, _h, body = _request(self.port, "GET", "/s/%E6%96%B0%E5%A2%9E/")
        self.assertEqual(status, 200)
        # 重复添加相同路径 → 幂等（同一路径只保留一个共享条目）
        status, _h, body = _request(self.port, "PUT", "/api/dirs", body=payload.encode(),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["name"], "新增")
        names = [d["name"] for d in self.cfg["directories"]]
        self.assertEqual(names.count("新增"), 1)
        # 路径不存在 → 400
        status, _h, body = _request(self.port, "PUT", "/api/dirs",
                                    body=json.dumps({"name": "x", "path": "/no/such"}).encode(),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        # 删除（URL 编码的共享名）
        status, _h, body = _request(self.port, "DELETE", "/api/dirs/%E6%96%B0%E5%A2%9E")
        self.assertEqual(status, 200)
        status, _h, _b = _request(self.port, "GET", "/s/%E6%96%B0%E5%A2%9E/")
        self.assertEqual(status, 404)
        status, _h, _b = _request(self.port, "DELETE", "/api/dirs/%E6%96%B0%E5%A2%9E")
        self.assertEqual(status, 404)

    def test_browse_api_lists_server_dirs(self):
        status, _h, body = _request(self.port, "GET",
                                    "/api/browse?path=" + server.quote(self.tmp.name))
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["path"], str(Path(self.tmp.name)))
        self.assertIn("movies", data["dirs"])
        self.assertIn("docs", data["dirs"])
        self.assertTrue(any(c["name"] == "/" for c in data["crumbs"]))
        # 不存在的路径 → 400 + error
        status, _h, body = _request(self.port, "GET", "/api/browse?path=/no/such/dir")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_traversal_protection(self):
        for p in ["/s/%E5%BD%B1%E8%A7%86/../../etc", "/s/%2e%2e/%2e%2e/etc"]:
            status, _h, _b = _request(self.port, "GET", p)
            self.assertIn(status, (400, 404), p)
        # 原始 UTF-8（未 percent-encode）的 URL 与 query 也能正确路由（curl 场景）
        status, body = _raw_request(self.port, "GET /s/影视/hello.txt")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"0123456789" * 100)
        status, _b = _raw_request(self.port, "PUT /upload?dir=影视/子目录&name=raw.txt",
                                  body=b"raw")
        self.assertEqual(status, 200)
        self.assertTrue((Path(self.cfg["directories"][0]["path"]) / "子目录" / "raw.txt").exists())
        # 上传文件名带路径 → 被清洗为纯文件名，落在本共享目录内
        status, _h, _b = _request(self.port, "PUT",
                                  "/upload?dir=%E6%96%87%E6%A1%A3&name=..%2Fevil.sh",
                                  body=b"x")
        self.assertEqual(status, 200)
        docs = Path(self.cfg["directories"][1]["path"])
        self.assertTrue((docs / "evil.sh").exists())
        self.assertFalse((docs.parent / "evil.sh").exists())


class TestTokenAndUploadDisabled(unittest.TestCase):
    def test_token_guards_pages_and_manage_api(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "f.txt").write_text("data")
            cfg = {"host": "127.0.0.1", "port": 0,
                   "directories": [{"name": "s", "path": td}],
                   "allow_upload": True, "show_hidden": False, "token": "s3cret"}
            state_file = Path(td) / "st.json"
            srv, port = _start_server(cfg, state_file)
            try:
                status, _h, _b = _request(port, "GET", "/")
                self.assertEqual(status, 401)
                status, h, _b = _request(port, "GET", "/?token=s3cret")
                self.assertEqual(status, 303)                    # 首次种 Cookie
                self.assertIn("lsf_token=s3cret", h["Set-Cookie"])
                cookie = {"Cookie": "lsf_token=s3cret"}
                status, _h, _b = _request(port, "GET", "/", headers=cookie)
                self.assertEqual(status, 200)
                status, _h, _b = _request(port, "PUT", "/api/dirs", body=b"{}",
                                           headers={**cookie,
                                                    "Content-Type": "application/json"})
                self.assertEqual(status, 400)                    # 放行但参数非法
                status, _h, _b = _request(port, "PUT", "/api/dirs", body=b"{}",
                                           headers={"Content-Type": "application/json"})
                self.assertEqual(status, 401)                    # 无口令则拒绝管理
            finally:
                srv.shutdown()
                srv.server_close()

    def test_upload_disabled_403(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"host": "127.0.0.1", "port": 0,
                   "directories": [{"name": "s", "path": td}],
                   "allow_upload": False, "show_hidden": False, "token": ""}
            srv, port = _start_server(cfg, Path(td) / "st.json")
            try:
                status, _h, _b = _request(port, "PUT", "/upload?dir=s&name=x.bin", body=b"data")
                self.assertEqual(status, 403)
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
