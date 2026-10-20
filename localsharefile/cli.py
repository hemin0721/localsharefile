"""命令行入口：run / install / uninstall / status。

用法：
    localsharefile run [--port 8000] [-d /path] ...
    localsharefile install [--directory D] [--port P] [--token T] ...
    localsharefile uninstall
    localsharefile status

多目录管理主要在网页首页进行（添加/移除共享目录），命令行 -d 用于初始设置第一个目录。
"""
import argparse
import socket
import sys
from pathlib import Path

from . import __version__, autostart, config, server


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="localsharefile",
        description="LocalShareFile —— 局域网文件共享工具（浏览器访问 IP:端口 即可下载/上传，"
                    "支持配置多个共享目录、网页远程管理、开机自启动）",
    )
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    def add_common(sp):
        sp.add_argument("--host", help="监听地址（默认 0.0.0.0，局域网可访问）")
        sp.add_argument("--port", type=int, help="监听端口（默认 8000）")
        sp.add_argument("-d", "--directory",
                        help="初始共享目录（覆盖已有列表；更多目录请在网页首页添加）")
        sp.add_argument("--token", help="访问口令，访问网页时需附加 ?token=口令")
        sp.add_argument("--no-upload", action="store_true", help="禁止网页上传（只读共享）")
        sp.add_argument("--show-hidden", action="store_true", help="在网页中显示隐藏文件")

    run_p = sub.add_parser("run", help="前台启动共享服务")
    add_common(run_p)

    inst_p = sub.add_parser("install", help="保存配置并安装系统自启动")
    add_common(inst_p)

    sub.add_parser("uninstall", help="卸载系统自启动")
    sub.add_parser("status", help="查看配置与运行状态")

    return p


def _merge_config(cfg: dict, args) -> dict:
    """把命令行参数覆盖进配置。"""
    if args.host:
        cfg["host"] = args.host
    if args.port:
        cfg["port"] = args.port
    if args.directory:
        real = config.normalize_directories([{"name": "", "path": args.directory}])
        cfg["directories"] = real if real else cfg["directories"]
    if args.token is not None:
        cfg["token"] = args.token
    if args.no_upload:
        cfg["allow_upload"] = False
    if args.show_hidden:
        cfg["show_hidden"] = True
    return cfg


def _check_port(cfg: dict) -> bool:
    """端口被其他进程占用时给出提示，返回是否可用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((cfg.get("host") or "0.0.0.0", int(cfg.get("port") or 8000)))
            return True
        except OSError:
            return False


def cmd_run(args):
    cfg = _merge_config(config.load(), args)
    if not _check_port(cfg):
        print(f"警告：端口 {cfg['port']} 已被占用，服务可能启动失败"
              f"（可用 --port 换端口，或 localsharefile install --port N 修改默认配置）")
    server.serve_forever(cfg)
    return 0


def cmd_install(args):
    cfg = _merge_config(config.load(), args)
    path = config.save(cfg)
    print(f"配置已保存：{path}")
    print(f"共享目录（{len(cfg['directories'])} 个）：")
    for d in cfg["directories"]:
        print(f"  - {d['name']}  →  {d['path']}")
    print(autostart.install(cfg))
    for ip in server.local_ips():
        print(f"现在即可在局域网设备浏览器打开：http://{ip}:{cfg['port']}")
    if not server.local_ips():
        print("提示：未探测到局域网 IP，请检查网络连接")
    return 0


def cmd_uninstall(_args):
    print(autostart.uninstall())
    return 0


def cmd_status(_args):
    cfg = config.load()
    print(f"LocalShareFile v{__version__}")
    print(f"配置文件：{config.config_path()}")
    print(f"共享目录（{len(cfg['directories'])} 个）：")
    for d in cfg["directories"]:
        mark = "✓" if Path(d["path"]).is_dir() else "⚠ 路径不存在"
        print(f"  [{mark}] {d['name']}  →  {d['path']}")
    print(f"监听地址：{cfg['host']}:{cfg['port']}")
    print(f"网页上传：{'允许' if cfg['allow_upload'] else '禁止'}    "
          f"口令校验：{'已启用' if cfg['token'] else '未启用'}")
    print(autostart.status())
    print(f"端口占用：{'空闲' if _check_port(cfg) else '被占用（服务未运行或端口冲突）'}")
    for ip in server.local_ips():
        print(f"局域网访问入口：http://{ip}:{cfg['port']}")
    return 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {"run": cmd_run, "install": cmd_install,
                "uninstall": cmd_uninstall, "status": cmd_status}
    handler = handlers.get(args.command)
    if not handler:
        _build_parser().print_help()
        return 2
    return handler(args)
