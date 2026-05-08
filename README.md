# musicdl GUI 版

## 项目介绍

- 免费音乐下载器，带本地音乐播放器。
- 基于 [CharlesPikachu/musicdl](https://github.com/CharlesPikachu/musicdl) 修改。
- 项目仅用于学习、研究和个人非商业使用，请遵守音乐平台服务条款、版权要求以及本仓库 LICENSE。

## 环境要求

- Windows 11
- PowerShell
- Python 3.12 或兼容版本
- 已安装 `uv`

## 创建虚拟环境

```powershell
cd D:\Projects\opensource\musicdl
uv venv
```

## 安装依赖

安装主项目：

```powershell
uv pip install -e .
```

安装 GUI 依赖：

```powershell
uv pip install -r examples\musicdlgui\requirements.txt
```

如需打包 exe，再安装 PyInstaller：

```powershell
uv pip install pyinstaller
```

## 启动 GUI

```powershell
uv run python examples\musicdlgui\musicdlgui.py
```

## 打包为 exe

推荐使用仓库根目录下的 `musicdlgui.spec` 打包，确保 `musicdl` 包、图标和相关资源被完整收集：

```powershell
uv run pyinstaller --clean -y musicdlgui.spec
```

打包完成后，exe 默认输出到：

```powershell
dist\musicdlgui.exe
```

注意：不要使用 `uv run pyinstaller ... examples\musicdlgui\musicdlgui.py ...` 这类脚本参数模式重新打包 GUI，否则可能覆盖 `musicdlgui.spec`，导致资源收集不完整。

## 命令行使用

```powershell
uv run musicdl
uv run musicdl -k "周杰伦"
uv run musicdl -k "周杰伦" -m "NeteaseMusicClient,QQMusicClient,KuwoMusicClient"
uv run musicdl -p "https://music.163.com/#/playlist?id=7583298906" -m "NeteaseMusicClient"
```
