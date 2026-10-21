# LocalShareFile

局域网文件共享工具 —— 在一台电脑上安装后，局域网内任何设备（手机 / 平板 / 电脑）用浏览器
打开 `http://IP:端口` 即可**浏览、下载、上传**文件；另提供 **`lsf` 终端命令**，
可在命令行直接列目录 / 下载 / 上传。纯 Python 标准库实现，**零第三方依赖**。

## 功能特性

- 🖥️ **终端 CLI（`lsf`）**：命令行直接列目录、下载（断点续传、目录自动打包 ZIP）、
  批量上传，带实时进度与速度显示
- 📁 **多目录共享**：同时共享任意多个目录，随时在网页上添加 / 移除
- 🌐 **网页远程配置**：首页即可添加共享目录，支持「浏览服务器磁盘」可视化选择目录，
  无需登录服务器改配置文件
- 🕘 **历史与常用**：自动记录访问历史；首页按访问次数排序展示「常用目录」与「最近访问」，
  浏览页顶部可从历史目录快速跳转
- ⬇️ **FTP 式下载**：点文件名直接下载；勾选多个文件/目录（或全选）一键打包 ZIP 下载；
  支持断点续传（Range），大文件流式传输
- ⬆️ **拖拽上传**：拖文件到页面任意位置上传到当前目录；拖到某个目录行直接上传到该目录，
  同名自动改名不覆盖
- 🔐 **可选口令**：`--token` 启用访问口令（覆盖浏览、上传与目录管理）
- 🚀 **开机自启动**：一条命令安装/卸载（Linux / Windows / macOS 全支持）
- 📦 **标准安装包**：打包为 wheel，`pip install` 即装

## 安装

```bash
# 从 PyPI 安装（任意机器，Python ≥ 3.8）
pip install localsharefile

# 从源码构建 wheel 安装包
./build.sh              # 产物在 dist/ 下
pip install dist/localsharefile-*.whl
```

安装后会得到两个命令：`localsharefile`（服务端）与 `lsf`（客户端）。

## 快速使用

```bash
# 临时启动（可先用 -d 指定第一个共享目录，更多目录在网页上添加）
localsharefile run -d ~/share --port 8080
```

启动后终端会打印访问入口：

```
 * LocalShareFile v0.2.0 已启动
 * 共享目录（1 个）：
     - share  →  /home/user/share
 * 本机访问:   http://127.0.0.1:8080
 * 局域网访问: http://192.168.1.10:8080
```

在同一局域网的手机/电脑浏览器打开「局域网访问」地址：

1. **首页**看到所有共享目录（按常用程度排序）、最近访问记录
2. 点 **➕ 添加共享目录** → 可手输服务器路径，或点 **📁 浏览服务器目录**
   在弹窗里逐级点开服务器磁盘，选定后一键共享
3. 进入目录后像 FTP 一样操作：点文件名下载、勾选多个条目点
   **⬇ 下载选中** 打包 ZIP、拖文件到页面或某个文件夹行上传

## 终端 CLI：lsf

在另一台机器（或本机）安装后，可直接在终端访问服务器：

```bash
# 列出服务器上的共享目录
lsf ls http://192.168.1.10:8000/

# 列出目录内容（名称/大小/时间/类型）
lsf ls http://192.168.1.10:8000/s/电影/

# 下载文件（实时进度+速度；-c 断点续传；-o 指定保存路径）
lsf get http://192.168.1.10:8000/s/电影/a.mp4
lsf get -c -o /tmp/续传.mp4 http://192.168.1.10:8000/s/电影/a.mp4

# 下载整个目录（服务端打包 ZIP，URL 以 / 结尾）
lsf get http://192.168.1.10:8000/s/电影/喜剧/

# 上传文件到该目录（可一次多个）
lsf put http://192.168.1.10:8000/s/电影/ 本地文件1.mp4 本地文件2.mkv

# 服务器启用口令时，任意子命令追加 --token 你的口令
lsf ls --token s3cret http://192.168.1.10:8000/
lsf get --token s3cret http://192.168.1.10:8000/s/电影/a.mp4
```

服务器脚本化示例（无需浏览器）：

```bash
SERVER=http://192.168.1.10:8000
lsf ls $SERVER/ | grep -v '^ ' | tail -n +2          # 共享名列表
lsf get "$SERVER/s/软件/ubuntu-24.04.iso"              # 下载 ISO
curl -sL "https://pypi.org/pypi/localsharefile/json"   # 查询最新版本
```

## 配置开机自启动

```bash
localsharefile install --port 8080 --token mysecret   # 保存配置并安装自启动
localsharefile status                                  # 查看配置/服务状态/访问入口
localsharefile uninstall                               # 卸载自启动
```

自启动实现按平台自动选择：

| 平台 | 机制 | 说明 |
|------|------|------|
| Linux | systemd 用户服务 | `~/.config/systemd/user/localsharefile.service`；如需未登录也运行：`loginctl enable-linger $USER` |
| Windows | 启动文件夹批处理 | 用 pythonw 静默启动（无黑窗口） |
| macOS | LaunchAgent | `~/Library/LaunchAgents/com.localsharefile.plist` |

配置文件（多目录列表、端口、口令等）：

- Linux：`~/.config/localsharefile/config.json`（访问统计在同目录 `state.json`）
- Windows：`%APPDATA%\LocalShareFile\config.json`
- macOS：`~/Library/Application Support/LocalShareFile/config.json`

网页上添加/移除共享目录会立即生效并写入配置文件；命令行 `install --port/--token`
等参数用于初始化，日常增删目录直接在网页操作即可。旧版 v0.1 的单目录配置会自动迁移。

## 命令一览

| 命令 | 作用 |
|------|------|
| `localsharefile run` | 前台启动服务（参数可临时覆盖配置） |
| `localsharefile install` | 保存配置并安装开机自启动 |
| `localsharefile uninstall` | 卸载自启动 |
| `localsharefile status` | 查看配置 / 服务状态 / 访问入口 |

通用参数：`--host`（默认 `0.0.0.0`）、`--port`（默认 `8000`）、`-d/--directory`
（初始共享目录，覆盖列表）、`--token`（口令）、`--no-upload`（禁用上传）、
`--show-hidden`（显示隐藏文件）。

## 安全须知

本工具面向**可信局域网**场景，未做传输加密（HTTP）与用户级权限控制。网页目录管理
（添加/移除共享、浏览服务器磁盘选目录）与普通页面受同一口令保护——**未配置 token 时，
局域网内任何人都可管理共享目录**，请务必在可信网络使用并建议启用 `--token`。

- 请勿将端口暴露到公网（路由器不要做端口映射）
- `--no-upload` 可关闭上传，将共享变为只读

## 开发与测试

```bash
python3 -m unittest discover -s tests    # 运行 20 个单元 / 集成测试
./build.sh                               # 构建 wheel
```

项目结构：

```
localsharefile/
├── __init__.py      # 版本信息
├── cli.py           # 服务端命令行入口（run/install/uninstall/status）
├── client.py        # 终端客户端 lsf（ls/get/put，进度/续传/token）
├── server.py        # HTTP 服务（多目录路由/管理 API/多选打包/上传/ls API）
├── page.py          # 内置网页模板（首页/浏览页/目录选择器，离线可用）
├── config.py        # 多目录配置读写 + v0.1 配置迁移
├── state.py         # 访问统计：历史目录 / 常用排序（state.json）
├── autostart.py     # 跨平台自启动管理
└── __main__.py      # python -m localsharefile
tests/test_all.py    # 单元 + 集成测试
```

## License

MIT
