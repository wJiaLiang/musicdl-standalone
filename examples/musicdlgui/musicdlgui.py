'''
Function:
    Implementation of MusicdlGUI
Author:
    Zhenchao Jin
WeChat Official Account:
    Charles_pikachu
'''
from __future__ import annotations

import copy
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows 下优先使用 WMF 后端，降低打包后 QMediaPlayer 播放失败概率。
if sys.platform.startswith('win'):
    os.environ.setdefault('QT_MULTIMEDIA_PREFERRED_PLUGINS', 'windowsmediafoundation')

from PyQt5.QtCore import QObject, QSettings, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QCursor, QFont, QIcon
try:
    from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer, QMediaPlaylist
    MULTIMEDIA_AVAILABLE = True
except Exception:
    QMediaContent = QMediaPlayer = QMediaPlaylist = None
    MULTIMEDIA_AVAILABLE = False
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from musicdl import musicdl
from musicdl.modules import MusicClientBuilder, SongInfo
from musicdl.modules.utils.logger import LoggerHandle
from musicdl.modules.utils.misc import IOUtils, legalizestring, sanitize_filename, sanitize_filepath, get_default_work_dir


DEFAULT_SOURCES = [
    'MiguMusicClient',
    'NeteaseMusicClient',
    'QQMusicClient',
    'KuwoMusicClient',
    'QianqianMusicClient',
    'KugouMusicClient',
]
DEFAULT_FILENAME_TEMPLATE = '{song_name} - {identifier}.{ext}'
VALID_AUDIO_SUFFIXES = {'.aac', '.ape', '.flac', '.m4a', '.mp3', '.ogg', '.wav', '.wma'}
SOURCE_DISPLAY_NAMES = {
    'MiguMusicClient': '咪咕音乐',
    'NeteaseMusicClient': '网易云音乐',
    'QQMusicClient': 'QQ音乐',
    'KuwoMusicClient': '酷我音乐',
    'QianqianMusicClient': '千千音乐',
    'KugouMusicClient': '酷狗音乐',
    'YouTubeMusicClient': 'YouTube Music',
    'AppleMusicClient': 'Apple Music',
    'SpotifyMusicClient': 'Spotify',
    'TIDALMusicClient': 'TIDAL',
    'DeezerMusicClient': 'Deezer',
    'QobuzMusicClient': 'Qobuz',
    'SoundCloudMusicClient': 'SoundCloud',
    'FMAMusicClient': 'Free Music Archive',
    'JamendoMusicClient': 'Jamendo',
    'BilibiliMusicClient': '哔哩哔哩',
    'XimalayaMusicClient': '喜马拉雅',
    'LizhiMusicClient': '荔枝',
    'QingtingMusicClient': '蜻蜓FM',
    'LRTSMusicClient': '懒人听书',
    'ITunesMusicClient': 'iTunes',
}


class SafeFormatDict(dict):
    '''为文件名模板提供安全缺省值，避免缺失字段导致格式化失败。'''
    def __missing__(self, key: str) -> str:
        return 'NULL'


def stringify(value: Any, default: str = 'NULL') -> str:
    '''将任意值转换为适合 UI 展示和文件名模板使用的文本。'''
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def short_text(value: Any, limit: int = 48) -> str:
    '''截断过长文本，返回适合表格展示的字符串。'''
    text = stringify(value, '')
    return text if len(text) <= limit else f'{text[:limit - 3]}...'


def source_display_name(source: str) -> str:
    '''将平台类型名转换为中文展示名，未知平台则保留原始名称。'''
    return SOURCE_DISPLAY_NAMES.get(source, source.removesuffix('MusicClient'))


def format_millis(milliseconds: int) -> str:
    '''将毫秒转换为播放器时间文本。'''
    seconds = max(0, int(milliseconds / 1000))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'


def build_client_cfg(sources: list[str], work_dir: str) -> dict[str, dict[str, str]]:
    '''根据已选平台构造 MusicClient 初始化配置。'''
    return {source: {'work_dir': work_dir} for source in sources}


def build_download_path(song_info: SongInfo, base_dir: str, keyword: str, batch_stamp: str, template: str) -> str:
    '''根据目录、关键词、批次时间和模板生成单首歌曲保存路径。'''
    ext = stringify(song_info.ext, 'mp3').removeprefix('.') or 'mp3'
    template_data = SafeFormatDict({
        'song_name': stringify(song_info.song_name),
        'singers': stringify(song_info.singers),
        'album': stringify(song_info.album),
        'source': stringify(song_info.source),
        'identifier': stringify(song_info.identifier),
        'ext': ext,
    })
    try:
        raw_filename = template.format_map(template_data)
    except Exception:
        raw_filename = DEFAULT_FILENAME_TEMPLATE.format_map(template_data)
    filename = sanitize_filename(raw_filename.strip() or DEFAULT_FILENAME_TEMPLATE.format_map(template_data))
    if not Path(filename).suffix:
        filename = f'{filename}.{ext}'
    source_name = sanitize_filename(stringify(song_info.source, 'UnknownSource'))
    keyword_name = legalizestring(keyword or 'downloads', max_len=80)
    work_dir = sanitize_filepath(os.path.join(base_dir, source_name, f'{batch_stamp} {keyword_name}'))
    IOUtils.touchdir(work_dir)
    return sanitize_filepath(os.path.join(work_dir, filename))


def prepare_download_songs(song_infos: list[SongInfo], base_dir: str, keyword: str, template: str) -> list[SongInfo]:
    '''复制并设置待下载歌曲的最终保存路径，返回可交给核心下载器的 SongInfo 列表。'''
    batch_stamp = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
    prepared: list[SongInfo] = []
    used_paths: set[str] = set()
    for source_song in song_infos:
        song_info = copy.deepcopy(source_song)
        save_path = build_download_path(song_info, base_dir, keyword, batch_stamp, template)
        path_obj, duplicate_idx = Path(save_path), 1
        while save_path in used_paths or os.path.exists(save_path):
            save_path = sanitize_filepath(str(path_obj.with_name(f'{path_obj.stem} ({duplicate_idx}){path_obj.suffix}')))
            duplicate_idx += 1
        used_paths.add(save_path)
        song_info._save_path = save_path
        song_info.work_dir = os.path.dirname(save_path)
        prepared.append(song_info)
    return prepared


class SearchWorker(QObject):
    '''在后台线程执行音乐搜索并把结果返回主线程。'''
    finished = pyqtSignal(object, object)
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, keyword: str, sources: list[str], work_dir: str):
        super().__init__()
        self.keyword = keyword
        self.sources = sources
        self.work_dir = work_dir

    def run(self) -> None:
        '''执行搜索任务，成功时返回 MusicClient 和搜索结果。'''
        try:
            self.status.emit('正在初始化音乐平台...')
            client = musicdl.MusicClient(
                music_sources=self.sources,
                init_music_clients_cfg=build_client_cfg(self.sources, self.work_dir),
            )
            self.status.emit('正在搜索，请稍候...')
            self.finished.emit(client, client.search(keyword=self.keyword))
        except Exception as err:
            self.failed.emit(str(err))


class DownloadWorker(QObject):
    '''在后台线程执行下载任务，避免阻塞 GUI 主线程。'''
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, song_infos: list[SongInfo], keyword: str, sources: list[str], work_dir: str, template: str):
        super().__init__()
        self.song_infos = song_infos
        self.keyword = keyword
        self.sources = sources
        self.work_dir = work_dir
        self.template = template

    def run(self) -> None:
        '''准备保存路径并调用核心 MusicClient 下载歌曲。'''
        try:
            self.status.emit('正在准备下载路径...')
            prepared_songs = prepare_download_songs(self.song_infos, self.work_dir, self.keyword, self.template)
            client = musicdl.MusicClient(
                music_sources=self.sources,
                init_music_clients_cfg=build_client_cfg(self.sources, self.work_dir),
            )
            self.status.emit(f'正在下载 {len(prepared_songs)} 首音乐...')
            self.finished.emit(client.download(prepared_songs))
        except Exception as err:
            self.failed.emit(str(err))


class PlaylistScanWorker(QObject):
    '''后台扫描下载目录下音频文件，避免阻塞 GUI 启动。'''
    # 变更为发射文件列表与是否自动加载的标志，规避 lambda 的直接跨线程访问问题
    finished = pyqtSignal(list, bool)
    failed = pyqtSignal(str)

    def __init__(self, base_dir: str, autoload: bool):
        super().__init__()
        # 初始化保存下载根目录路径
        self.base_dir = base_dir
        # 初始化保存是否为程序启动自动加载
        self.autoload = autoload

    def run(self) -> None:
        '''扫描音频文件并返回文件路径列表。'''
        try:
            base_path = Path(self.base_dir)
            if not base_path.exists():
                # 若目录不存在，安全触发 finished 信号，返回空列表及原自动加载属性
                self.finished.emit([], self.autoload)
                return
            # 递归检索所有符合 VALID_AUDIO_SUFFIXES 支持的音频格式的本地文件路径
            files = [
                str(path) for path in base_path.rglob('*')
                if path.is_file() and path.suffix.lower() in VALID_AUDIO_SUFFIXES
            ]
            # 检索完成后安全发射 finished 信号，传递找到的文件列表和原自动加载属性
            self.finished.emit(files, self.autoload)
        except Exception as err:
            # 异常时发射 failed 信号将报错信息传递至主线程
            self.failed.emit(str(err))


class LogWindow(QWidget):
    '''
    日志显示窗口类，继承自 QWidget，负责增量读取并滚动展示 musicdl 系统运行日志。
    使用经典终端黑底绿字样式，并利用 QTimer 在显示状态下轮询日志文件。
    '''
    def __init__(self, parent=None):
        # 调用父类构造函数进行初始化
        super(LogWindow, self).__init__(parent)
        self.log_file_path = LoggerHandle.log_file_path  # 绑定底层 logger.py 自动生成的物理日志路径
        self._file_offset = 0  # 文件字节读取偏移量指针，记录增量读取状态
        self.setAttribute(Qt.WA_DeleteOnClose)  # 关闭窗口时自动彻底销毁 C++ 与 Python 实例以释放内存
        self.resize(900, 400)  # 设定日志窗口默认宽高为 900 * 400 像素，优化首屏阅读视野
        self._setup_ui()  # 初始化日志窗口控件架构与样式
        self._setup_timer()  # 启动 QTimer 开启增量检查轮询
        self.read_log_incremental(first_load=True)  # 首次呈现日志，防卡顿截断读取最近历史内容

    def _setup_ui(self) -> None:
        '''
        创建日志视窗中所需的布局及全部交互按钮。
        调用关系：由构造函数 __init__ 自动执行以实现界面搭建。
        '''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 创建用于日志展示的多行纯文本只读编辑框
        self.log_edit = QPlainTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(8000)  # 最大缓存 8000 行，多余部分自动丢弃保护内存

        # 纯黑极简现代命令行风格配色样式
        self.log_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #121212;
                color: #00ff66;
                font-family: 'Consolas', 'Courier New', 'Monospace', 'Microsoft YaHei UI';
                font-size: 13px;
                border: 1px solid #2e2e2e;
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.log_edit)

        # 底部控制工具条
        toolbar = QHBoxLayout()

        # 清空当前终端视窗展示的日志文本
        self.clear_btn = QPushButton('清空显示', self)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: #d9534f;
                color: white;
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #c9302c;
            }
        """)
        self.clear_btn.clicked.connect(self.clear_display)

        # 复制文本到系统剪贴板
        self.copy_btn = QPushButton('复制日志', self)
        self.copy_btn.setStyleSheet("""
            QPushButton {
                background: #337ab7;
                color: white;
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #286090;
            }
        """)
        self.copy_btn.clicked.connect(self.copy_log)

        # 关闭日志视窗本身
        self.close_btn = QPushButton('关闭视窗', self)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: #777777;
                color: white;
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #5e5e5e;
            }
        """)
        self.close_btn.clicked.connect(self.close)

        # 组装横向控制条，清空与复制靠左，关闭按钮紧靠右侧
        toolbar.addWidget(self.clear_btn)
        toolbar.addWidget(self.copy_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.close_btn)

        layout.addLayout(toolbar)

    def _setup_timer(self) -> None:
        '''
        初始化高灵敏度 QTimer 以在打开期间进行秒级文件检测。
        调用关系：由构造函数 __init__ 自动执行开启。
        '''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer_timeout)
        self.timer.start(300)  # 每 300 毫秒高灵敏度扫描一次，兼顾实时性与低 CPU 开销

    def clear_display(self) -> None:
        '''仅清空当前文本框内容，不影响磁盘文件。由 self.clear_btn.clicked 信号触发。'''
        self.log_edit.clear()

    def copy_log(self) -> None:
        '''将终端文本框中全部日志复制到系统剪贴板。由 self.copy_btn.clicked 信号触发。'''
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_edit.toPlainText())

    def on_timer_timeout(self) -> None:
        '''定时回调入口，触发下层实际的增量检测读取。由 self.timer.timeout 信号触发。'''
        self.read_log_incremental(first_load=False)

    def read_log_incremental(self, first_load: bool = False) -> None:
        '''
        高性能增量读取磁盘日志文件，并带有超大文件自动截断的内存防护。
        参数:
            first_load: 是否为新开窗口的首次读取，决定是否激活 50KB 截断保护。
        调用关系：
            1. 构造函数中首次执行（first_load=True）。
            2. 定时器 timeout 周期性轮询执行（first_load=False）。
        '''
        if not os.path.exists(self.log_file_path):
            return

        try:
            current_size = os.path.getsize(self.log_file_path)

            # 物理文件截断重置保护：如果日志物理文件由于其他原因被删除或清空导致比已读指针还小，重置指针
            if current_size < self._file_offset:
                self._file_offset = 0
                self.log_edit.appendPlainText(">>> 检测到日志物理文件被重建或截断，已重新从头部读取 <<<\n")

            # 内存防护机制：如果是窗口首次加载，且历史日志已经过大，只读取末尾 50KB，杜绝一次性渲染大量文本引起 UI 卡死
            if first_load and current_size > 51200:
                self._file_offset = current_size - 51200
                self.log_edit.appendPlainText(">>> 历史运行日志过大，已启动内存保护，仅显示最近 50KB 内容 <<<\n")

            # 有新内容写入时才发生文件读取
            if current_size > self._file_offset:
                with open(self.log_file_path, 'rb') as f:
                    f.seek(self._file_offset)  # 寻址到上次已读字节位置
                    new_bytes = f.read(current_size - self._file_offset)
                    self._file_offset = current_size  # 更新当前已读的最新文件指针

                    if new_bytes:
                        # 兼容处理解码，剔除 UTF-8 非法字节
                        new_text = new_bytes.decode('utf-8', errors='ignore')
                        # 通过正则消除 ANSI 颜色代码控制字符，将 \033[31m 还原为普通文字显示
                        clean_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', new_text)

                        # 检测当前滚动条状态。若用户当前正在最底端，则插入后强制跟随滚动
                        scrollbar = self.log_edit.verticalScrollBar()
                        was_at_bottom = scrollbar.value() == scrollbar.maximum()

                        self.log_edit.insertPlainText(clean_text)

                        if was_at_bottom:
                            scrollbar.setValue(scrollbar.maximum())

        except Exception as err:
            # 静默容错，将错误打印在日志文本中，防止其以致命 crash 形式爆出
            self.log_edit.appendPlainText(f"[日志异常提示] 增量读取磁盘文件失败: {str(err)}\n")

    def closeEvent(self, event) -> None:
        '''
        窗口关闭事件拦截。关闭视窗时必须显式停止轮询定时器，安全回收资源。
        调用关系：由 Qt 窗口框架在窗口收到 close 请求时自动触发。
        '''
        self.timer.stop()
        event.accept()


class MusicdlGUI(QMainWindow):
    '''musicdl 桌面 GUI 主窗口，提供搜索、下载和本地播放功能。'''
    def __init__(self):
        super(MusicdlGUI, self).__init__()
        self.search_results: dict[str, list[SongInfo]] = {}
        self.music_records: list[SongInfo] = []
        self.search_thread: QThread | None = None
        self.download_thread: QThread | None = None
        self.playlist_scan_thread: QThread | None = None
        self.music_client: musicdl.MusicClient | None = None
        self.log_window: LogWindow | None = None
        self.slider_pressed = False
        self.current_play_file_path: str = ''
        self.playback_mode_index = 2
        self.playback_modes = ['single_once', 'single_loop', 'list_loop']
        self.playback_mode_labels = {
            'single_once': '单曲播放',
            'single_loop': '单曲循环',
            'list_loop': '列表循环',
        }
        self.settings = QSettings('musicdl', 'musicdlgui')
        # 检测用户是否曾手动修改过下载路径标识
        # 调用关系：调用 self.settings.value() 获取布尔值标识
        is_custom = self.settings.value('is_custom_download_dir', False, type=bool)
        # 如果用户手动修改过，则加载自定义保存的路径；否则默认每次启动都加载 exe 同级或项目 dist 目录下的 musicdl_outputs
        # 调用关系：根据 is_custom 分支决定调用 self.settings.value() 还是 get_default_work_dir()
        if is_custom:
            # 加载用户手动保存过的路径，备选为默认输出目录
            # 调用关系：调用 self.settings.value() 并以 get_default_work_dir() 为缺省参数
            self.download_dir = self.settings.value('download_dir', get_default_work_dir(), type=str)
        else:
            # 没有手动更改过路径，每次启动均自动绑定默认的 exe 同级（打包）或项目 dist（开发）下的 outputs 文件夹
            # 调用关系：直接调用 get_default_work_dir() 解析绝对路径并赋值
            self.download_dir = get_default_work_dir()
        self.filename_template = self.settings.value('filename_template', DEFAULT_FILENAME_TEMPLATE, type=str)
        self.setWindowTitle('music 桌面音乐下载器')
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'icon.ico')))
        self.resize(1240, 760)
        self._setup_ui()
        self._setup_player()
        self._apply_style()
        self.load_download_records()
        # 启动时自动扫描下载目录
        QTimer.singleShot(150, self._autoload_existing_downloads)

    def _setup_ui(self) -> None:
        '''创建主界面布局、表格、下载设置和播放器区域。'''
        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 14)
        root_layout.setSpacing(12)

        root_layout.addWidget(self._build_header())
        splitter = QSplitter(Qt.Horizontal, central)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_player_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 700, 300])
        root_layout.addWidget(splitter, 1)
        root_layout.addWidget(self._build_status_bar())
        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        '''创建顶部搜索工具条。'''
        panel = QFrame(self)
        panel.setObjectName('HeaderPanel')
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 14)
        title_box = QVBoxLayout()
        title = QLabel('freeMusic')
        title.setObjectName('AppTitle')
        subtitle = QLabel('搜索、下载与播放本地音乐')
        subtitle.setObjectName('AppSubtitle')
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addSpacing(24)
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText('输入歌曲、歌手或专辑关键词')
        self.keyword_edit.returnPressed.connect(self.search)
        self.search_button = QPushButton('搜索')
        self.search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.search_button.clicked.connect(self.search)
        layout.addWidget(self.keyword_edit, 1)
        layout.addWidget(self.search_button)
        return panel

    def _build_left_panel(self) -> QWidget:
        '''创建左侧平台选择和下载设置面板。'''
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        source_group = QGroupBox('音乐平台')
        source_layout = QVBoxLayout(source_group)
        source_scroll = QScrollArea(source_group)
        source_scroll.setWidgetResizable(True)
        source_scroll.setFrameShape(QFrame.NoFrame)
        source_widget = QWidget(source_scroll)
        source_widget_layout = QVBoxLayout(source_widget)
        self.source_boxes: list[QCheckBox] = []
        available_sources = list(MusicClientBuilder.REGISTERED_MODULES.keys())
        ordered_sources = DEFAULT_SOURCES + [s for s in available_sources if s not in DEFAULT_SOURCES]
        for source in ordered_sources:
            display_name = source_display_name(source)
            checkbox = QCheckBox(f'{display_name}（{source}）')
            checkbox.setProperty('source_key', source)
            checkbox.setChecked(source in DEFAULT_SOURCES)
            self.source_boxes.append(checkbox)
            source_widget_layout.addWidget(checkbox)
        source_widget_layout.addStretch(1)
        source_scroll.setWidget(source_widget)
        source_layout.addWidget(source_scroll)

        settings_group = QGroupBox('下载设置')
        settings_layout = QVBoxLayout(settings_group)
        self.download_dir_edit = QLineEdit(self.download_dir)
        self.download_dir_edit.setReadOnly(True)
        choose_dir_button = QPushButton('选择目录')
        choose_dir_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        choose_dir_button.clicked.connect(self.choose_download_dir)
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.download_dir_edit, 1)
        dir_layout.addWidget(choose_dir_button)
        self.filename_template_edit = QLineEdit(self.filename_template)
        self.filename_template_edit.setPlaceholderText(DEFAULT_FILENAME_TEMPLATE)
        self.filename_template_edit.textChanged.connect(self.save_filename_template)
        settings_layout.addWidget(QLabel('基础目录'))
        settings_layout.addLayout(dir_layout)
        settings_layout.addWidget(QLabel('文件名模板'))
        settings_layout.addWidget(self.filename_template_edit)

        layout.addWidget(source_group, 3)
        layout.addWidget(settings_group, 0)
        return panel

    def _build_center_panel(self) -> QWidget:
        '''创建搜索结果和下载队列区域。'''
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.results_table = QTableWidget(0, 8)
        self.results_table.setHorizontalHeaderLabels(['ID', '歌曲', '歌手', '专辑', '大小', '时长', '格式', '来源'])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self.open_result_menu)
        self.results_table.doubleClicked.connect(self.download_selected)

        action_layout = QHBoxLayout()
        self.download_button = QPushButton('下载选中')
        self.download_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.download_button.clicked.connect(self.download_selected)
        self.open_dir_button = QPushButton('打开目录')
        self.open_dir_button.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.open_dir_button.clicked.connect(self.choose_download_dir)
        self.log_button = QPushButton('日志')
        self.log_button.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxInformation))
        self.log_button.clicked.connect(self.show_log_window)
        action_layout.addWidget(self.download_button)
        action_layout.addWidget(self.open_dir_button)
        action_layout.addWidget(self.log_button)
        action_layout.addStretch(1)

        self.download_table = QTableWidget(0, 5)
        self.download_table.setHorizontalHeaderLabels(['歌曲', '歌手', '来源', '状态', '文件路径'])
        self.download_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.download_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.download_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.download_table.customContextMenuRequested.connect(self.open_download_menu)
        self.download_table.doubleClicked.connect(self.play_selected_download)

        layout.addWidget(QLabel('搜索结果'))
        layout.addWidget(self.results_table, 3)
        layout.addLayout(action_layout)
        layout.addWidget(QLabel('下载记录'))
        layout.addWidget(self.download_table, 2)
        return panel

    def _build_player_panel(self) -> QWidget:
        '''创建右侧本地播放器和播放列表区域。'''
        panel = QGroupBox('本地播放器', self)
        layout = QVBoxLayout(panel)
        self.now_playing_label = QLabel('未播放')
        self.now_playing_label.setObjectName('NowPlaying')
        self.playlist_widget = QListWidget()
        self.playlist_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.playlist_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_widget.itemDoubleClicked.connect(self.play_playlist_item)
        self.playlist_widget.customContextMenuRequested.connect(self.open_playlist_menu)

        controls = QHBoxLayout()
        self.prev_button = QPushButton()
        self.prev_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.next_button = QPushButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        self.playback_mode_combo = QComboBox()
        for mode in self.playback_modes:
            self.playback_mode_combo.addItem(self.playback_mode_labels[mode], mode)
        self.playback_mode_combo.setCurrentIndex(self.playback_mode_index)
        self.playback_mode_combo.currentIndexChanged.connect(self.change_playback_mode)
        self.update_playback_mode_control()
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        controls.addWidget(self.playback_mode_combo)

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.sliderPressed.connect(self._on_slider_pressed)
        self.position_slider.sliderReleased.connect(self._on_slider_released)
        self.time_label = QLabel('00:00 / 00:00')
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setToolTip('音量')

        player_actions = QHBoxLayout()
        self.scan_button = QPushButton('扫描目录')
        self.scan_button.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.scan_button.clicked.connect(self.scan_download_dir)
        self.add_files_button = QPushButton('添加文件')
        self.add_files_button.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        self.add_files_button.clicked.connect(self.add_audio_files)
        self.remove_playlist_button = QPushButton('移除选中')
        self.remove_playlist_button.setIcon(self.style().standardIcon(QStyle.SP_DialogDiscardButton))
        self.remove_playlist_button.clicked.connect(self.remove_selected_playlist_items)
        player_actions.addWidget(self.scan_button)
        player_actions.addWidget(self.add_files_button)
        player_actions.addWidget(self.remove_playlist_button)

        layout.addWidget(self.now_playing_label)
        layout.addWidget(self.playlist_widget, 1)
        layout.addLayout(controls)
        layout.addWidget(self.position_slider)
        layout.addWidget(self.time_label)
        layout.addWidget(QLabel('音量'))
        layout.addWidget(self.volume_slider)
        layout.addLayout(player_actions)
        return panel

    def _build_status_bar(self) -> QWidget:
        '''创建底部状态栏和任务进度条。'''
        panel = QFrame(self)
        panel.setObjectName('FooterPanel')
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        self.status_label = QLabel('就绪')
        self.task_progress = QProgressBar()
        self.task_progress.setRange(0, 100)
        self.task_progress.setValue(0)
        self.task_progress.setTextVisible(False)
        self.task_progress.setFixedWidth(180)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.task_progress)
        return panel

    def _setup_player(self) -> None:
        '''初始化 QtMultimedia 播放器和相关信号。'''
        if not MULTIMEDIA_AVAILABLE:
            self.set_status('当前 PyQt5 环境缺少 QtMultimedia，播放器已禁用')
            for widget in [self.prev_button, self.play_button, self.next_button, self.playback_mode_combo, self.position_slider, self.volume_slider, self.scan_button, self.add_files_button, self.remove_playlist_button]:
                widget.setEnabled(False)
            return
        self.player = QMediaPlayer(self)
        self.playlist = QMediaPlaylist(self)
        self.player.setPlaylist(self.playlist)
        self.player.setVolume(self.volume_slider.value())
        self.apply_playback_mode()
        self.prev_button.clicked.connect(self.playlist.previous)
        self.next_button.clicked.connect(self.playlist.next)
        self.play_button.clicked.connect(self.toggle_playback)
        self.volume_slider.valueChanged.connect(self.player.setVolume)
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.stateChanged.connect(self.update_play_button)
        self.player.error.connect(self.handle_player_error)
        self.playlist.currentIndexChanged.connect(self.update_playlist_selection)

    def current_playback_mode(self) -> str:
        '''返回当前播放器模式键名。'''
        if hasattr(self, 'playback_mode_combo'):
            selected_mode = self.playback_mode_combo.currentData()
            if selected_mode in self.playback_modes:
                return selected_mode
        return self.playback_modes[self.playback_mode_index]

    def update_playback_mode_control(self) -> None:
        '''根据当前播放模式刷新按钮文案和提示。'''
        mode = self.current_playback_mode()
        label = self.playback_mode_labels[mode]
        self.playback_mode_index = self.playback_modes.index(mode)
        self.playback_mode_combo.setToolTip(f'当前播放模式：{label}')

    def apply_playback_mode(self) -> None:
        '''把当前播放模式应用到 Qt 播放列表。'''
        if not MULTIMEDIA_AVAILABLE:
            return
        mode_map = {
            'single_once': QMediaPlaylist.CurrentItemOnce,
            'single_loop': QMediaPlaylist.CurrentItemInLoop,
            'list_loop': QMediaPlaylist.Loop,
        }
        self.playlist.setPlaybackMode(mode_map[self.current_playback_mode()])

    def change_playback_mode(self, index: int) -> None:
        '''在单曲播放、单曲循环和列表循环之间切换。'''
        if index < 0:
            return
        self.playback_mode_index = index
        self.update_playback_mode_control()
        self.apply_playback_mode()
        self.set_status(f'播放模式：{self.playback_mode_labels[self.current_playback_mode()]}')

    def _apply_style(self) -> None:
        '''应用桌面端现代化视觉样式。'''
        self.setFont(QFont('Microsoft YaHei UI', 10))
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #f5f7fb;
                color: #1f2937;
            }
            #HeaderPanel, #FooterPanel, QGroupBox {
                background: #ffffff;
                border: 1px solid #d7dde8;
                border-radius: 8px;
            }
            #AppTitle {
                font-size: 28px;
                font-weight: 700;
                color: #111827;
            }
            #AppSubtitle {
                color: #64748b;
            }
            #NowPlaying {
                font-size: 15px;
                font-weight: 600;
                color: #0f172a;
            }
            QGroupBox {
                margin-top: 12px;
                padding: 14px 10px 10px 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #334155;
            }
            QLineEdit {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 10px;
            }
            QPushButton {
                background: #2563eb;
                color: white;
                border: 0;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QPushButton:disabled {
                background: #94a3b8;
            }
            QTableWidget, QListWidget, QScrollArea {
                background: #ffffff;
                border: 1px solid #d7dde8;
                border-radius: 6px;
                gridline-color: #e5e7eb;
                selection-background-color: #dbeafe;
                selection-color: #111827;
            }
            QHeaderView::section {
                background: #e8eef7;
                color: #334155;
                border: 0;
                padding: 8px;
                font-weight: 700;
            }
            QProgressBar {
                background: #e2e8f0;
                border: 0;
                border-radius: 5px;
                height: 10px;
            }
            QProgressBar::chunk {
                background: #22c55e;
                border-radius: 5px;
            }
        """)

    def selected_sources(self) -> list[str]:
        '''读取当前勾选的音乐平台列表。'''
        return [stringify(box.property('source_key'), box.text()) for box in self.source_boxes if box.isChecked()]

    def set_status(self, text: str, busy: bool = False) -> None:
        '''更新底部状态文本和任务进度条形态。'''
        self.status_label.setText(text)
        if busy:
            self.task_progress.setRange(0, 0)
        else:
            self.task_progress.setRange(0, 100)
            self.task_progress.setValue(0)

    def choose_download_dir(self) -> None:
        '''弹出目录选择框并更新基础下载目录。'''
        # 弹出系统原生目录选择框，让用户手动挑选新的音乐下载目标存储目录
        # 调用关系：调用 QFileDialog.getExistingDirectory 阻塞等待用户选择目录
        directory = QFileDialog.getExistingDirectory(self, '选择下载目录', self.download_dir)
        # 如果用户取消选择或路径为空，直接终止执行
        if not directory:
            # 退出当前函数
            return
        # 更新程序运行中的当前下载路径变量
        self.download_dir = directory
        # 在界面输入框中呈现最新选择的物理绝对目录路径
        # 调用关系：调用 self.download_dir_edit.setText 刷新文本内容
        self.download_dir_edit.setText(directory)
        # 将用户新挑选的物理目录持久化保存到设置中
        # 调用关系：调用 self.settings.setValue 写入键值 'download_dir'
        self.settings.setValue('download_dir', directory)
        # 核心逻辑：标记用户确实“手动修改过”路径，确保后续重启不会被动态默认路径所覆盖
        # 调用关系：调用 self.settings.setValue 写入键值 'is_custom_download_dir'
        self.settings.setValue('is_custom_download_dir', True)
        # 强行同步刷新设置内容至磁盘或注册表物理文件
        # 调用关系：调用 self.settings.sync() 物理写入
        self.settings.sync()
        # 底部状态栏展示最新操作详情
        # 调用关系：调用 self.set_status() 显示中文通知
        self.set_status(f'下载目录已设置为：{directory}')

    def _autoload_existing_downloads(self) -> None:
        '''程序启动时自动扫描历史下载音乐，同时加入播放列表和下载记录。'''
        if not MULTIMEDIA_AVAILABLE:
            return
        self._scan_playlist_files(autoload=True)

    def save_filename_template(self) -> None:
        '''保存文件名模板到持久化配置。'''
        template = self.filename_template_edit.text().strip()
        if template:
            self.settings.setValue('filename_template', template)
            self.settings.sync()

    def search(self) -> None:
        '''根据关键词和平台选择启动后台搜索。'''
        keyword = self.keyword_edit.text().strip()
        sources = self.selected_sources()
        if not keyword:
            QMessageBox.warning(self, '缺少关键词', '请输入歌曲、歌手或专辑关键词。')
            return
        if not sources:
            QMessageBox.warning(self, '缺少平台', '请至少选择一个音乐平台。')
            return
        self.search_button.setEnabled(False)
        self.results_table.setRowCount(0)
        self.download_table.setRowCount(0)
        self.music_records = []
        self.set_status('正在启动搜索任务...', busy=True)
        # 创建搜索专用后台线程
        self.search_thread = QThread(self)
        # 创建搜索工作器实例
        self.search_worker = SearchWorker(keyword, sources, self.download_dir)
        # 将工作器移至后台线程中运行
        self.search_worker.moveToThread(self.search_thread)
        # 绑定线程启动信号与工作器的具体执行逻辑
        self.search_thread.started.connect(self.search_worker.run)
        # 绑定进度更新信号，由于是常规成员方法绑定，由 PyQt 自动进行 QueuedConnection，确保主线程安全更新
        self.search_worker.status.connect(self._on_search_status)
        # 绑定成功后的回调，自动确保主线程更新
        self.search_worker.finished.connect(self.on_search_finished)
        # 绑定失败回调
        self.search_worker.failed.connect(self.on_search_failed)
        # 当工作器成功或失败完成时，指示线程安全退出
        self.search_worker.finished.connect(self.search_thread.quit)
        self.search_worker.failed.connect(self.search_thread.quit)
        # 线程完全结束后，通知 C++ 释放内存，并在主线程调用清理方法清空 Python 引用以防止野指针
        self.search_thread.finished.connect(self.search_thread.deleteLater)
        self.search_thread.finished.connect(self._cleanup_search_thread)
        # 启动线程
        self.search_thread.start()

    def on_search_finished(self, client: musicdl.MusicClient, results: dict[str, list[SongInfo]]) -> None:
        '''处理搜索成功结果并刷新结果表格。'''
        self.music_client = client
        self.search_results = results
        rows: list[SongInfo] = []
        for source_results in results.values():
            rows.extend(source_results)
        self.music_records = rows
        self.results_table.setRowCount(len(rows))
        for row, song_info in enumerate(rows):
            values = [
                str(row + 1),
                short_text(song_info.song_name),
                short_text(song_info.singers),
                short_text(song_info.album),
                short_text(song_info.file_size),
                short_text(song_info.duration),
                short_text(song_info.ext),
                short_text(song_info.source),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, row)
                self.results_table.setItem(row, column, item)
        self.search_button.setEnabled(True)
        self.set_status(f'搜索完成，共找到 {len(rows)} 条可下载结果')

    def on_search_failed(self, error: str) -> None:
        '''处理搜索失败并恢复按钮状态。'''
        self.search_button.setEnabled(True)
        self.set_status('搜索失败')
        QMessageBox.critical(self, '搜索失败', error)

    def open_result_menu(self) -> None:
        '''打开搜索结果右键菜单。'''
        menu = QMenu(self)
        download_action = menu.addAction('下载选中')
        action = menu.exec_(QCursor.pos())
        if action == download_action:
            self.download_selected()

    def selected_song_infos(self) -> list[SongInfo]:
        '''获取结果表格中当前选中的 SongInfo。'''
        selected_rows = sorted({index.row() for index in self.results_table.selectionModel().selectedRows()})
        return [self.music_records[row] for row in selected_rows if 0 <= row < len(self.music_records)]

    def download_selected(self) -> None:
        '''启动后台下载任务并记录待下载歌曲。'''
        song_infos = self.selected_song_infos()
        if not song_infos:
            QMessageBox.information(self, '未选择音乐', '请先在搜索结果中选择要下载的音乐。')
            return
        sources = sorted({stringify(song.source) for song in song_infos if song.source})
        template = self.filename_template_edit.text().strip() or DEFAULT_FILENAME_TEMPLATE
        keyword = self.keyword_edit.text().strip() or 'downloads'
        self.download_button.setEnabled(False)
        self.set_status('正在启动下载任务...', busy=True)
        self.append_download_rows(song_infos, '下载中')
        # 创建下载专用后台线程
        self.download_thread = QThread(self)
        # 创建下载工作器实例
        self.download_worker = DownloadWorker(song_infos, keyword, sources, self.download_dir, template)
        # 将工作器移至后台线程中运行
        self.download_worker.moveToThread(self.download_thread)
        # 绑定线程启动信号与工作器的下载逻辑
        self.download_thread.started.connect(self.download_worker.run)
        # 绑定下载状态通知信号，通过普通方法绑定实现队列化跨线程主线程状态更新
        self.download_worker.status.connect(self._on_download_status)
        # 绑定下载成功后的处理方法
        self.download_worker.finished.connect(self.on_download_finished)
        # 绑定下载失败异常的回调方法
        self.download_worker.failed.connect(self.on_download_failed)
        # 当工作完成或失败时，退让并通知下载线程退出事件循环
        self.download_worker.finished.connect(self.download_thread.quit)
        self.download_worker.failed.connect(self.download_thread.quit)
        # 线程彻底停止后，清空 C++ 物理内存，并利用主线程清理逻辑抹除 Python 的悬空引用
        self.download_thread.finished.connect(self.download_thread.deleteLater)
        self.download_thread.finished.connect(self._cleanup_download_thread)
        # 启动线程
        self.download_thread.start()

    def append_download_rows(self, song_infos: list[SongInfo], status: str) -> None:
        '''将待下载歌曲追加到下载记录表。'''
        for song_info in song_infos:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            values = [song_info.song_name, song_info.singers, song_info.source, status, '']
            for column, value in enumerate(values):
                item = QTableWidgetItem(short_text(value, 80))
                item.setData(Qt.UserRole, '')
                self.download_table.setItem(row, column, item)

    def on_download_finished(self, downloaded_songs: list[SongInfo]) -> None:
        '''处理下载完成结果，刷新下载记录并加入播放列表。'''
        self.download_button.setEnabled(True)
        valid_songs = [song for song in downloaded_songs if song and song.save_path and os.path.exists(song.save_path)]
        for song_info in valid_songs:
            self.upsert_download_record(song_info)
            self.add_to_playlist(song_info.save_path, song_info)
        self.save_download_records()
        self.set_status(f'下载完成，成功 {len(valid_songs)} 首')
        if not valid_songs:
            QMessageBox.warning(self, '下载完成', '没有成功写入的音乐文件，请查看终端日志了解失败原因。')

    def on_download_failed(self, error: str) -> None:
        '''处理下载任务异常并恢复按钮状态。'''
        self.download_button.setEnabled(True)
        self.set_status('下载失败')
        QMessageBox.critical(self, '下载失败', error)

    def add_download_record(self, song_info: SongInfo) -> None:
        '''把下载成功的歌曲写入下载记录表。'''
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        self.fill_download_record(row, song_info)

    def upsert_download_record(self, song_info: SongInfo) -> None:
        '''优先更新下载中的记录，找不到时追加新记录。'''
        for row in range(self.download_table.rowCount()):
            same_song = self.download_table.item(row, 0) and self.download_table.item(row, 0).text() == short_text(song_info.song_name, 80)
            same_source = self.download_table.item(row, 2) and self.download_table.item(row, 2).text() == short_text(song_info.source, 80)
            downloading = self.download_table.item(row, 3) and self.download_table.item(row, 3).text() == '下载中'
            if same_song and same_source and downloading:
                self.fill_download_record(row, song_info)
                return
        self.add_download_record(song_info)

    def fill_download_record(self, row: int, song_info: SongInfo) -> None:
        '''把单条下载记录写入指定表格行。'''
        values = [song_info.song_name, song_info.singers, song_info.source, '已下载', song_info.save_path]
        for column, value in enumerate(values):
            item = QTableWidgetItem(short_text(value, 120))
            item.setToolTip(stringify(value, ''))
            item.setData(Qt.UserRole, song_info.save_path)
            self.download_table.setItem(row, column, item)

    def save_download_records(self) -> None:
        '''把下载记录表持久化保存到 QSettings。'''
        records: list[dict] = []
        for row in range(self.download_table.rowCount()):
            path_item = self.download_table.item(row, 4)
            if not path_item:
                continue
            save_path = stringify(path_item.data(Qt.UserRole), '')
            if save_path and os.path.exists(save_path):
                song_name = stringify(self.download_table.item(row, 0).text()) if self.download_table.item(row, 0) else ''
                singers = stringify(self.download_table.item(row, 1).text()) if self.download_table.item(row, 1) else ''
                source = stringify(self.download_table.item(row, 2).text()) if self.download_table.item(row, 2) else ''
                records.append({
                    'save_path': save_path,
                    'song_name': song_name,
                    'singers': singers,
                    'source': source,
                })
        self.settings.setValue('download_records', records)
        self.settings.sync()

    def load_download_records(self) -> None:
        '''从 QSettings 加载历史下载记录到下载记录表，使用批量插入减少重绘。'''
        # 从 QSettings 读取历史记录列表
        records = self.settings.value('download_records', [], type=list)
        valid_records = []
        was_migrated = False  # 是否发生过路径修正，用于决定是否回写 settings
        
        for record in records:
            save_path = stringify(record.get('save_path', ''))
            if not save_path:
                continue

            # 核心策略：只要路径中含有 'musicdl_outputs' 特征目录，
            # 不论旧路径文件是否存在，都优先基于当前活跃的 self.download_dir 重新计算路径。
            # 这样可确保表格始终展示当前 exe 所在运行环境下的实际输出目录路径。
            # 调用关系：调用 split 截取 'musicdl_outputs' 之后的相对路径尾部
            if 'musicdl_outputs' in save_path:
                # 截取 'musicdl_outputs' 之后的歌曲相对分类路径，例如 'KuwoMusicClient\xxx.mp3'
                # 调用关系：调用 split + lstrip 清理路径前缀的斜杠或反斜杠
                relative_tail = save_path.split('musicdl_outputs', 1)[1].lstrip('\\/')
                # 基于当前运行的默认下载目录重新拼接绝对路径
                # 调用关系：调用 os.path.join 进行跨平台路径拼接
                remapped_path = os.path.abspath(os.path.join(self.download_dir, relative_tail))
                
                if os.path.exists(remapped_path):
                    # 重映射后的路径文件存在，优先使用新路径
                    if remapped_path != save_path:
                        # 路径发生了变化，记录需要回写 settings
                        record['save_path'] = remapped_path
                        was_migrated = True
                    save_path = remapped_path
                elif os.path.exists(save_path):
                    # 重映射后的路径文件不存在，但旧路径文件存在，使用旧路径（不替换显示）
                    pass
                else:
                    # 两个路径均不存在，跳过该记录
                    continue
            else:
                # 路径中没有 'musicdl_outputs' 特征（用户完全自定义目录），
                # 按原路径是否存在决定是否展示
                if not os.path.exists(save_path):
                    continue

            valid_records.append(record)

        # 若发生了路径自愈修正，立即回写 settings 以持久化新路径
        # 调用关系：调用 self.settings.setValue 写入，调用 self.settings.sync() 刷入磁盘
        if was_migrated:
            self.settings.setValue('download_records', records)
            self.settings.sync()

        if not valid_records:
            return

        self.download_table.blockSignals(True)
        self.download_table.setUpdatesEnabled(False)
        start_row = self.download_table.rowCount()
        self.download_table.setRowCount(start_row + len(valid_records))
        for i, record in enumerate(valid_records):
            row = start_row + i
            save_path = stringify(record.get('save_path', ''))
            values = [
                stringify(record.get('song_name', Path(save_path).stem)),
                stringify(record.get('singers', '')),
                stringify(record.get('source', 'Unknown')),
                '已下载',
                save_path,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(short_text(value, 120))
                item.setToolTip(stringify(value, ''))
                item.setData(Qt.UserRole, save_path)
                self.download_table.setItem(row, column, item)
        self.download_table.setUpdatesEnabled(True)
        self.download_table.blockSignals(False)

    def open_download_menu(self, position) -> None:
        '''显示下载记录右键菜单，支持删除记录。'''
        item = self.download_table.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.download_table.setCurrentItem(item)
        menu = QMenu(self)
        remove_action = menu.addAction('删除记录')
        action = menu.exec_(self.download_table.viewport().mapToGlobal(position))
        if action == remove_action:
            self.remove_selected_download_records()

    def remove_selected_download_records(self) -> None:
        '''从下载记录表中删除选中的行，仅移除表格记录，不删除本地文件。'''
        rows = sorted({index.row() for index in self.download_table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.download_table.removeRow(row)
        if rows:
            self.save_download_records()
            self.set_status(f'已删除 {len(rows)} 条下载记录')

    def add_to_playlist(self, file_path: str, song_info: SongInfo | None = None) -> None:
        '''把本地音频文件加入播放器列表。'''
        if not MULTIMEDIA_AVAILABLE or not file_path or not os.path.exists(file_path):
            return
        existing_paths = {
            self.playlist_widget.item(i).data(Qt.UserRole)
            for i in range(self.playlist_widget.count())
        }
        if file_path in existing_paths:
            return
        if song_info is not None and getattr(song_info, 'song_name', None):
            title = stringify(song_info.song_name)
        else:
            stem = Path(file_path).stem
            title = re.sub(r'\s*-\s*[a-zA-Z0-9]+$', '', stem).strip()
            if not title:
                title = stem
        singers = stringify(getattr(song_info, 'singers', None), '')
        label = f'{title} - {singers}' if singers else title
        existing_labels = {
            self.playlist_widget.item(i).text()
            for i in range(self.playlist_widget.count())
        }
        base_label = label
        duplicate_idx = 1
        while label in existing_labels:
            label = f'{base_label} ({duplicate_idx})'
            duplicate_idx += 1
        item = QListWidgetItem(label)
        item.setToolTip(file_path)
        item.setData(Qt.UserRole, file_path)
        self.playlist_widget.addItem(item)
        self.playlist.addMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
        if self.playlist.mediaCount() == 1:
            self.playlist.setCurrentIndex(0)

    def open_playlist_menu(self, position) -> None:
        '''显示播放列表右键菜单，提供仅从列表移除的操作。'''
        item = self.playlist_widget.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.playlist_widget.setCurrentItem(item)
        menu = QMenu(self)
        remove_action = menu.addAction('从列表移除')
        action = menu.exec_(self.playlist_widget.viewport().mapToGlobal(position))
        if action == remove_action:
            self.remove_selected_playlist_items()

    def remove_selected_playlist_items(self) -> None:
        '''移除播放列表中选中的曲目，只更新列表，不删除本地文件。'''
        rows = [index.row() for index in self.playlist_widget.selectedIndexes()]
        removed_count = self.remove_playlist_rows(rows)
        if removed_count > 0:
            self.set_status(f'已从播放列表移除 {removed_count} 首，文件未删除')

    def remove_playlist_rows(self, rows: list[int]) -> int:
        '''按行号移除播放列表曲目，返回实际移除数量。'''
        if not MULTIMEDIA_AVAILABLE:
            return 0
        valid_rows = sorted({
            row for row in rows
            if 0 <= row < self.playlist_widget.count()
        }, reverse=True)
        if not valid_rows:
            return 0
        current_index = self.playlist.currentIndex()
        if current_index in valid_rows:
            self.player.stop()
        for row in valid_rows:
            self.playlist.removeMedia(row)
            item = self.playlist_widget.takeItem(row)
            del item
        if self.playlist.mediaCount() == 0:
            self.now_playing_label.setText('未播放')
            self.current_play_file_path = ''
            self.position_slider.setValue(0)
            self.time_label.setText('00:00 / 00:00')
        elif current_index in valid_rows:
            self.playlist.setCurrentIndex(min(current_index, self.playlist.mediaCount() - 1))
        return len(valid_rows)

    def scan_download_dir(self) -> None:
        '''扫描当前下载目录下的音频文件并加入播放列表和下载记录。'''
        if not Path(self.download_dir).exists():
            QMessageBox.information(self, '目录不存在', '当前下载目录不存在。')
            return
        self._scan_playlist_files(autoload=False)

    def _scan_playlist_files(self, autoload: bool) -> None:
        '''启动后台线程扫描音频文件，并在完成后批量加入播放列表和下载记录。'''
        # 核心逻辑：若前次线程正在运转，直接阻断新运行，保护线程环境不被篡改
        if self.playlist_scan_thread and self.playlist_scan_thread.isRunning():
            return
        self.set_status('正在扫描本地音乐...', busy=True)
        # 实例化后台子线程，设置当前主类实例为父对象
        self.playlist_scan_thread = QThread(self)
        # 实例化扫描工作器，显式将 autoload 变量作为状态成员传参给工作器保存，代替 lambda 闭包作用域
        self.playlist_scan_worker = PlaylistScanWorker(self.download_dir, autoload)
        # 将工作器移至后台线程中运行
        self.playlist_scan_worker.moveToThread(self.playlist_scan_thread)
        # 连接线程的启动信号与工作器的执行逻辑
        self.playlist_scan_thread.started.connect(self.playlist_scan_worker.run)
        # 去除原 lambda 直接连接，绑定普通成员方法使其以 QueuedConnection 方式在主线程中安全回调
        self.playlist_scan_worker.finished.connect(self._on_playlist_scan_finished)
        # 连接失败异常回调
        self.playlist_scan_worker.failed.connect(self._on_playlist_scan_failed)
        # 扫描顺利完工或失败时，皆促使子线程退出事件循环
        self.playlist_scan_worker.finished.connect(self.playlist_scan_thread.quit)
        self.playlist_scan_worker.failed.connect(self.playlist_scan_thread.quit)
        # 线程运行生命周期圆满结束后，自动回收底层 C++ 对象，并在主线程把 Python 引用置空为 None 规避下一次点击的野指针闪退
        self.playlist_scan_thread.finished.connect(self.playlist_scan_thread.deleteLater)
        self.playlist_scan_thread.finished.connect(self._cleanup_playlist_scan_thread)
        # 启动后台线程执行
        self.playlist_scan_thread.start()

    def _cleanup_search_thread(self) -> None:
        '''在主线程安全清理搜索线程和工作器引用，避免下一次调用或程序关闭时造成野指针崩溃。'''
        self.search_thread = None
        self.search_worker = None

    def _cleanup_download_thread(self) -> None:
        '''在主线程安全清理下载线程和工作器引用，避免下一次调用或程序关闭时造成野指针崩溃。'''
        self.download_thread = None
        self.download_worker = None

    def _cleanup_playlist_scan_thread(self) -> None:
        '''在主线程安全清理扫描线程和工作器引用，避免下一次调用或程序关闭时造成野指针崩溃。'''
        self.playlist_scan_thread = None
        self.playlist_scan_worker = None

    def _on_search_status(self, text: str) -> None:
        '''在主线程安全更新搜索进度文本与状态栏。'''
        self.set_status(text, busy=True)

    def _on_download_status(self, text: str) -> None:
        '''在主线程安全更新下载进度文本与状态栏。'''
        self.set_status(text, busy=True)

    def _on_playlist_scan_finished(self, files: list[str], autoload: bool) -> None:
        '''处理扫描结果并将音频加入播放列表和下载记录。'''
        added_count = 0
        for file_path in files:
            before = self.playlist_widget.count()
            self.add_to_playlist(file_path)
            # 同时添加到下载记录（如果还没有的话）
            self._add_path_to_download_records(file_path)
            added_count += 1 if self.playlist_widget.count() > before else 0
        # 保存下载记录
        self.save_download_records()
        if autoload:
            self.set_status(f'已自动加载 {added_count} 首历史下载音乐' if added_count > 0 else '已就绪')
        else:
            self.set_status(f'已加入 {added_count} 个本地音频文件')

    def _on_playlist_scan_failed(self, error: str) -> None:
        '''处理扫描失败并显示状态。'''
        self.set_status(f'扫描失败：{error}')

    def _add_path_to_download_records(self, file_path: str) -> None:
        '''把单个文件路径添加到下载记录表（如果还没有的话）。'''
        existing_paths = {
            self.download_table.item(row, 4).data(Qt.UserRole)
            for row in range(self.download_table.rowCount())
            if self.download_table.item(row, 4)
        }
        if file_path in existing_paths:
            return
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        values = [
            Path(file_path).stem,
            '',
            '本地文件',
            '已下载',
            file_path,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(short_text(value, 120))
            item.setToolTip(stringify(value, ''))
            item.setData(Qt.UserRole, file_path)
            self.download_table.setItem(row, column, item)

    def add_audio_files(self) -> None:
        '''通过文件选择框向播放列表添加本地音频文件。'''
        files, _ = QFileDialog.getOpenFileNames(
            self,
            '添加音乐文件',
            self.download_dir,
            'Audio Files (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.wma *.ape);;All Files (*)',
        )
        for file_path in files:
            self.add_to_playlist(file_path)
            self._add_path_to_download_records(file_path)
        if files:
            self.save_download_records()
            self.set_status(f'已加入 {len(files)} 个文件')

    def play_selected_download(self) -> None:
        '''播放下载记录表中选中的本地文件。'''
        selected = self.download_table.selectionModel().selectedRows()
        if not selected:
            return
        path_item = self.download_table.item(selected[0].row(), 4)
        file_path = path_item.data(Qt.UserRole) if path_item else ''
        if file_path:
            self.play_file_path(file_path)

    def play_playlist_item(self, item: QListWidgetItem) -> None:
        '''播放播放列表中双击的曲目。'''
        row = self.playlist_widget.row(item)
        if row >= 0 and MULTIMEDIA_AVAILABLE:
            self.playlist.setCurrentIndex(row)
            self.current_play_file_path = stringify(item.data(Qt.UserRole), '')
            self.player.play()

    def play_file_path(self, file_path: str) -> None:
        '''根据本地路径定位播放列表曲目并开始播放。'''
        if not MULTIMEDIA_AVAILABLE or not os.path.exists(file_path):
            return
        for row in range(self.playlist_widget.count()):
            if self.playlist_widget.item(row).data(Qt.UserRole) == file_path:
                self.playlist.setCurrentIndex(row)
                self.current_play_file_path = file_path
                self.player.play()
                return
        self.add_to_playlist(file_path)
        self.playlist.setCurrentIndex(self.playlist.mediaCount() - 1)
        self.current_play_file_path = file_path
        self.player.play()

    def toggle_playback(self) -> None:
        '''切换播放器播放和暂停状态。'''
        if not MULTIMEDIA_AVAILABLE:
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_play_button(self, state: int) -> None:
        '''根据播放状态切换播放按钮图标。'''
        icon = QStyle.SP_MediaPause if state == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))

    def update_position(self, position: int) -> None:
        '''同步播放器当前位置到进度条。'''
        if not self.slider_pressed:
            self.position_slider.setValue(position)
        self.time_label.setText(f'{format_millis(position)} / {format_millis(self.player.duration())}')

    def update_duration(self, duration: int) -> None:
        '''同步播放器总时长到进度条范围。'''
        self.position_slider.setRange(0, max(0, duration))
        self.time_label.setText(f'{format_millis(self.player.position())} / {format_millis(duration)}')

    def update_playlist_selection(self, index: int) -> None:
        '''切歌时同步播放列表高亮和当前播放文本。'''
        if index < 0 or index >= self.playlist_widget.count():
            self.now_playing_label.setText('未播放')
            self.current_play_file_path = ''
            return
        self.playlist_widget.setCurrentRow(index)
        item = self.playlist_widget.item(index)
        self.current_play_file_path = stringify(item.data(Qt.UserRole), '')
        self.now_playing_label.setText(item.text())

    def handle_player_error(self) -> None:
        '''显示播放器错误信息。'''
        if MULTIMEDIA_AVAILABLE and self.player.error() != QMediaPlayer.NoError:
            err_text = self.player.errorString() or '未知错误'
            file_part = f'，文件: {self.current_play_file_path}' if self.current_play_file_path else ''
            self.set_status(f'播放器错误：{err_text}{file_part}')

    def _on_slider_pressed(self) -> None:
        '''标记用户正在拖动播放进度条。'''
        self.slider_pressed = True

    def _on_slider_released(self) -> None:
        '''用户释放进度条时跳转到目标播放位置。'''
        self.slider_pressed = False
        if MULTIMEDIA_AVAILABLE:
            self.player.setPosition(self.position_slider.value())

    def shutdown_player(self) -> None:
        '''快速释放播放器资源，减少窗口关闭时的多媒体后端阻塞。'''
        if not MULTIMEDIA_AVAILABLE:
            return
        self.player.blockSignals(True)
        if self.player.state() != QMediaPlayer.StoppedState:
            self.player.stop()
        self.player.setPlaylist(None)

    def shutdown_thread(self, thread: QThread | None, timeout_ms: int = 2000) -> None:
        '''请求后台线程退出并等待自然结束，超时后再强制终止。'''
        if not thread or not thread.isRunning():
            return
        thread.requestInterruption()
        thread.quit()
        if thread.wait(timeout_ms):
            return
        thread.terminate()
        thread.wait(500)

    def show_log_window(self) -> None:
        '''
        非模态弹出并置顶展示日志视窗，如果尚未实例化则新建并执行信号绑定。
        调用关系：由顶部/中部的“日志”按钮点击信号触发。
        '''
        if self.log_window is None:
            self.log_window = LogWindow()
            # 绑定销毁信号。当 LogWindow 收到 close 销毁自身时，将 self.log_window 置为 None，防 Python 野指针崩溃
            self.log_window.destroyed.connect(self._on_log_window_destroyed)
        self.log_window.show()
        self.log_window.raise_()
        self.log_window.activateWindow()
        self.set_status('已打开系统运行日志视窗')

    def _on_log_window_destroyed(self) -> None:
        '''
        当日志窗口由于 close 自动被销毁时，重置本地悬空引用为 None。
        调用关系：由 self.log_window.destroyed 信号触发。
        '''
        self.log_window = None

    def closeEvent(self, event) -> None:
        '''关闭窗口时先隐藏界面、释放播放器、等待事件循环处理异步资源，再停止后台线程并保存设置。'''
        self.hide()
        # 清爽退出机制：如果日志视窗当前仍开启，一并将其安全关闭释放定时器，确保没有孤儿窗口或悬挂线程运行
        if self.log_window is not None:
            self.log_window.close()
        self.shutdown_player()
        QApplication.processEvents()
        self.save_download_records()
        self.settings.sync()
        for thread in [self.search_thread, self.download_thread, self.playlist_scan_thread]:
            self.shutdown_thread(thread)
        event.accept()
        super().closeEvent(event)


if __name__ == '__main__':
    # 针对 Windows 系统设置独立的 AppUserModelID，以确保任务栏图标能正确加载我们的自定义 icon，而不是显示默认 python 图标。
    if sys.platform.startswith('win'):
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('musicdl.musicdlgui.1.0')

    app = QApplication(sys.argv)
    gui = MusicdlGUI()
    gui.show()
    sys.exit(app.exec_())
