# AGENTS.md

本文件用于指导 Codex / Agent 在 `musicdl` 项目中协作开发、分析和维护代码。所有协作说明默认使用简体中文。

## 项目概览

`musicdl` 是一个纯 Python 实现的音乐搜索与下载工具，核心能力包括：

- 多音乐平台搜索、歌单解析和音乐下载。
- 命令行交互式使用方式。
- 以 `SongInfo` 为统一数据结构封装不同平台的搜索与下载结果。
- 通过不同平台客户端适配官方接口、第三方解析接口、HLS/DASH 流、分片下载和标签写入。
- `examples/musicdlgui` 提供一个基于 PyQt5 的 GUI 示例，但主项目入口仍然是命令行。

项目用途以学习、研究和个人非商业使用为主。修改代码时必须保留 README 和 LICENSE 中的非商业与版权免责声明语义，不要添加规避平台授权、绕过 DRM 或批量分发版权内容的说明。

## 运行环境

默认开发环境：

- Windows 11
- PowerShell
- Python 3.12 或兼容版本
- `uv` 优先用于创建虚拟环境、安装依赖和执行命令
- 项目当前仍使用 `setup.py` / `requirements.txt` 风格管理 Python 包

推荐初始化命令：

```powershell
cd D:\Projects\opensource\musicdl
uv venv
uv pip install -e .
```

启动命令行主程序：

```powershell
uv run musicdl
```

搜索并选择下载：

```powershell
uv run musicdl -k "周杰伦"
```

指定平台：

```powershell
uv run musicdl -k "周杰伦" -m "NeteaseMusicClient,QQMusicClient,KuwoMusicClient"
```

解析歌单：

```powershell
uv run musicdl -p "https://music.163.com/#/playlist?id=7583298906" -m "NeteaseMusicClient"
```

## 技术栈

核心技术栈：

- Python 包：`musicdl`
- 命令行框架：`click`
- 终端表格与进度：`rich`、`prettytable`
- HTTP 请求：`requests`，部分场景可使用 `curl-cffi`
- HTML 解析：`beautifulsoup4`、`lxml`
- JSON 修复/解析：`json-repair`、`orjson`
- 加密/解密：`cryptography`、`pycryptodome`、`pycryptodomex`、`pywidevine`
- 音频元信息与标签：`mutagen`、`tinytag`
- HLS 解析与下载：`m3u8`、项目内 `HLSDownloader`
- YouTube Music：`ytmusicapi`，并包含项目内 YouTube 工具模块
- 可选外部工具：`ffmpeg`、`N_m3u8DL-RE`、`MP4Box`、`mp4decrypt`、`amdecrypt`
- GUI 示例：`PyQt5`
- 文档：Sphinx + Markdown 文档

## 目录结构

重点目录：

- `musicdl/musicdl.py`：命令行入口与 `MusicClient` 聚合逻辑。
- `musicdl/modules/sources`：主流音乐平台客户端实现。
- `musicdl/modules/audiobooks`：音频书、播客和 FM 类平台客户端。
- `musicdl/modules/common`：聚合源和多源网关客户端。
- `musicdl/modules/thirdpartysites`：第三方下载站点或网页解析客户端。
- `musicdl/modules/utils`：通用工具、命令构造、HLS、歌词、Cookie、平台辅助工具、`SongInfo` 等。
- `musicdl/modules/js/youtube`：YouTube 相关 JavaScript 辅助逻辑。
- `musicdl/modules/wvds`：Widevine 设备文件。
- `examples/musicdlgui`：PyQt5 GUI 示例。
- `docs`：用户文档。
- `scripts`：辅助脚本。

运行生成目录：

- `musicdl_outputs`：默认下载和搜索结果输出目录。
- `.venv`：本地虚拟环境。
- `musicdl.egg-info`：本地 editable 安装生成目录。

这些运行产物通常不应纳入代码变更。

## 架构约定

平台客户端通常继承 `BaseMusicClient`，并实现以下职责：

- `_constructsearchurls()`：根据关键词和规则构造搜索请求。
- `_search()`：请求平台接口，解析搜索结果，并构造 `SongInfo`。
- `parseplaylist()`：可选，解析歌单 URL 并返回 `SongInfo` 列表。
- `_download()`：可选，仅在普通 HTTP/HLS 下载无法覆盖时重写。

公共下载逻辑位于 `BaseMusicClient._download()`：

- `protocol == "HTTP"` 且 `downloaded_contents` 存在时，直接写入字节内容。
- `protocol == "HTTP"` 且 `download_url` 是字符串时，使用流式 HTTP 下载。
- `protocol == "HLS"` 时，使用 `HLSDownloader` 解析、下载、解密和合并分片。

所有平台都应尽量返回标准 `SongInfo`，不要在上层 `MusicClient` 中塞入平台专有逻辑。

## 编码规范

遵循项目现有风格：

- 保持当前模块化结构，不做无关大重构。
- 新增平台客户端优先继承 `BaseMusicClient`。
- 新增平台工具逻辑优先放在 `musicdl/modules/utils/{platform}utils.py`。
- 新增结构化数据优先复用或扩展 `SongInfo`，避免随意使用临时 dict 贯穿全流程。
- 文件路径和文件名必须经过合法化处理，优先复用 `legalizestring`、`sanitize_filepath`、`sanitize_filename`、`IOUtils.touchdir`。
- HTTP 请求优先使用 `self.get()` / `self.post()`，以复用重试、代理、UA、Cookie 和 `curl-cffi` 行为。
- 新增函数应写函数级注释，说明用途、关键参数和返回值；注释保持简洁。
- 不要把大量业务逻辑塞进单个函数。复杂平台解析应拆成独立 `_parsewith...`、工具函数或 utils 方法。
- 不要硬编码本机绝对路径。
- 不要把账号 Cookie、Token、API Key、会员凭据提交到仓库。

## 平台客户端开发建议

新增或修改平台时，优先按以下流程：

1. 在平台文件中设置 `source = 'XxxMusicClient'`。
2. 配置搜索、解析、下载三类默认 headers/cookies。
3. 实现 `_constructsearchurls()`。
4. 实现 `_search()`，每个有效结果构造 `SongInfo`。
5. 使用 `AudioLinkTester.test()` 验证直链、推断扩展名和文件大小。
6. 如支持歌单，实现 `parseplaylist()`，并在最后设置统一 `work_dir`。
7. 在 `musicdl/modules/sources/__init__.py` 注册客户端。
8. 如涉及特殊依赖或凭据，在 `docs/Clients.md` 和 README 支持表中同步说明。

对于会员、加密或流媒体平台：

- 优先使用用户合法提供的 Cookie/Token 或平台授权接口。
- 不要新增绕过 DRM、规避付费墙或未经授权访问内容的说明。
- 若需要外部工具，必须在文档中明确安装要求和失败降级行为。
- HLS 非 DRM AES 分片可使用项目内 `HLSDownloader`；DRM 场景不要手写规避逻辑。

## GUI 示例说明

`examples/musicdlgui/musicdlgui.py` 使用 PyQt5。

启动：

```powershell
cd D:\Projects\opensource\musicdl
uv pip install -e .
uv pip install -r examples\musicdlgui\requirements.txt
uv run python examples\musicdlgui\musicdlgui.py
```

注意：

- GUI 只是示例，不是主项目架构核心。
- 示例下载逻辑较旧，直接 `requests.get(song_info['download_url'])`，无法完整覆盖 HLS、Apple、TIDAL、YouTube 自定义流对象、预下载字节等情况。
- 若维护 GUI，建议改为调用 `MusicClient.download([song_info])`，复用核心下载逻辑。

## 测试与验证

当前仓库没有完整自动化测试套件。修改后至少做以下验证：

```powershell
uv run python -m compileall musicdl
```

针对 CLI 入口：

```powershell
uv run musicdl --help
```

针对具体平台，优先用较小搜索数量或单平台验证：

```powershell
uv run musicdl -k "test" -m "KuwoMusicClient"
```

涉及下载逻辑时，需要实际验证：

- 搜索结果能否构造有效 `SongInfo`。
- `download_url_status["ok"]` 是否为真。
- 文件是否写入 `musicdl_outputs`。
- 歌词、封面、基础标签写入失败时是否只降级为 warning。

## 打包说明

项目主包通过 `setup.py` 注册控制台命令：

```python
entry_points={'console_scripts': ['musicdl = musicdl.musicdl:MusicClientCMD']}
```

常规本地安装：

```powershell
uv pip install -e .
```

GUI 示例如需打包，可使用 PyInstaller，但打包前应先修复 GUI 示例中与当前核心 API 不一致的部分，并确认版权和 LICENSE 限制。

参考命令：

```powershell
uv pip install pyinstaller
uv run pyinstaller `
  --noconsole `
  --onefile `
  --icon examples\musicdlgui\icon.ico `
  --add-data "examples\musicdlgui\icon.ico;." `
  examples\musicdlgui\musicdlgui.py
```

启动速度优先（推荐 `onedir`）：

```powershell
uv run pyinstaller --clean -y musicdlgui.spec
```

注意：不要再用 `uv run pyinstaller ... examples\musicdlgui\musicdlgui.py ...` 这类“脚本参数模式”，会覆盖 `musicdlgui.spec`，导致 `musicdl` 包未被完整收集。

## 文档维护

涉及以下变更时必须同步文档：

- 新增平台客户端。
- 平台名称、支持搜索/下载能力变化。
- 新增必需 Cookie、Token、外部工具或环境变量。
- 修改 CLI 参数。
- 修改默认下载目录或输出文件结构。

优先更新：

- `README.md`
- `docs/Clients.md`
- `docs/Quickstart.md`
- `docs/Install.md`
- `docs/Changelog.md`

## 协作注意事项

- 默认使用简体中文交流。
- 命令优先给出 PowerShell 版本。
- 使用 `uv` 管理 Python 环境，除非项目已有更明确约定。
- 不要删除用户下载的音乐、`.venv`、`musicdl_outputs` 或其他运行数据，除非用户明确要求。
- 修改前先阅读相关平台客户端和对应 utils，不要凭接口名猜测行为。
- 不要把第三方解析服务的可用性视为稳定；这类接口可能随时失效。
- 不要在提交中包含真实 Cookie、Token、下载结果、搜索结果 pickle、音频文件或本地缓存。
