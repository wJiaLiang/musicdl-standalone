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
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows 下优先使用 WMF 后端，降低打包后 QMediaPlayer 播放失败概率。
if sys.platform.startswith('win'):
    os.environ.setdefault('QT_MULTIMEDIA_PREFERRED_PLUGINS', 'windowsmediafoundation')

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, QUrl, pyqtSignal
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
from musicdl.modules.utils.misc import IOUtils, legalizestring, sanitize_filename, sanitize_filepath


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
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, base_dir: str):
        super().__init__()
        self.base_dir = base_dir

    def run(self) -> None:
        '''扫描音频文件并返回文件路径列表。'''
        try:
            base_path = Path(self.base_dir)
            if not base_path.exists():
                self.finished.emit([])
                return
            files = [
                str(path) for path in base_path.rglob('*')
                if path.is_file() and path.suffix.lower() in VALID_AUDIO_SUFFIXES
            ]
            self.finished.emit(files)
        except Exception as err:
            self.failed.emit(str(err))


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
        self.slider_pressed = False
        self.current_play_file_path: str = ''
        self.playback_mode_index = 2
        self.playback_modes = ['single_once', 'single_loop', 'list_loop']
        self.playback_mode_labels = {
            'single_once': '单曲播放',
            'single_loop': '单曲循环',
            'list_loop': '列表循环',
        }
        self.download_dir = os.path.abspath('musicdl_outputs')
        self.setWindowTitle('musicdl 桌面音乐下载器')
        self.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), 'icon.ico')))
        self.resize(1240, 760)
        self._setup_ui()
        self._setup_player()
        self._apply_style()
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
        title = QLabel('musicdl')
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
        self.filename_template_edit = QLineEdit(DEFAULT_FILENAME_TEMPLATE)
        self.filename_template_edit.setPlaceholderText(DEFAULT_FILENAME_TEMPLATE)
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
        action_layout.addWidget(self.download_button)
        action_layout.addWidget(self.open_dir_button)
        action_layout.addStretch(1)

        self.download_table = QTableWidget(0, 5)
        self.download_table.setHorizontalHeaderLabels(['歌曲', '歌手', '来源', '状态', '文件路径'])
        self.download_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.download_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
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
        directory = QFileDialog.getExistingDirectory(self, '选择下载目录', self.download_dir)
        if not directory:
            return
        self.download_dir = directory
        self.download_dir_edit.setText(directory)
        self.set_status(f'下载目录已设置为：{directory}')

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
        self.search_thread = QThread(self)
        self.search_worker = SearchWorker(keyword, sources, self.download_dir)
        self.search_worker.moveToThread(self.search_thread)
        self.search_thread.started.connect(self.search_worker.run)
        self.search_worker.status.connect(lambda text: self.set_status(text, busy=True))
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.failed.connect(self.on_search_failed)
        self.search_worker.finished.connect(self.search_thread.quit)
        self.search_worker.failed.connect(self.search_thread.quit)
        self.search_thread.finished.connect(self.search_thread.deleteLater)
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
        self.append_download_rows(song_infos, '等待下载')
        self.download_thread = QThread(self)
        self.download_worker = DownloadWorker(song_infos, keyword, sources, self.download_dir, template)
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.status.connect(lambda text: self.set_status(text, busy=True))
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.failed.connect(self.on_download_failed)
        self.download_worker.finished.connect(self.download_thread.quit)
        self.download_worker.failed.connect(self.download_thread.quit)
        self.download_thread.finished.connect(self.download_thread.deleteLater)
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
        '''优先更新等待中的下载记录，找不到时追加新记录。'''
        for row in range(self.download_table.rowCount()):
            same_song = self.download_table.item(row, 0) and self.download_table.item(row, 0).text() == short_text(song_info.song_name, 80)
            same_source = self.download_table.item(row, 2) and self.download_table.item(row, 2).text() == short_text(song_info.source, 80)
            pending = self.download_table.item(row, 3) and self.download_table.item(row, 3).text() == '等待下载'
            if same_song and same_source and pending:
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
        title = stringify(getattr(song_info, 'song_name', None), Path(file_path).stem)
        singers = stringify(getattr(song_info, 'singers', None), '')
        label = f'{title} - {singers}' if singers else title
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

    def _autoload_existing_downloads(self) -> None:
        '''程序启动时自动加载历史下载歌曲到本地播放列表。'''
        if not MULTIMEDIA_AVAILABLE:
            return
        self._scan_playlist_files(autoload=True)

    def scan_download_dir(self) -> None:
        '''扫描当前下载目录下的音频文件并加入播放列表。'''
        if not Path(self.download_dir).exists():
            QMessageBox.information(self, '目录不存在', '当前下载目录不存在。')
            return
        self._scan_playlist_files(autoload=False)

    def _scan_playlist_files(self, autoload: bool) -> None:
        '''启动后台线程扫描音频文件，并在完成后批量加入播放列表。'''
        if self.playlist_scan_thread and self.playlist_scan_thread.isRunning():
            return
        self.set_status('正在扫描本地音乐...', busy=True)
        self.playlist_scan_thread = QThread(self)
        self.playlist_scan_worker = PlaylistScanWorker(self.download_dir)
        self.playlist_scan_worker.moveToThread(self.playlist_scan_thread)
        self.playlist_scan_thread.started.connect(self.playlist_scan_worker.run)
        self.playlist_scan_worker.finished.connect(lambda files: self._on_playlist_scan_finished(files, autoload))
        self.playlist_scan_worker.failed.connect(self._on_playlist_scan_failed)
        self.playlist_scan_worker.finished.connect(self.playlist_scan_thread.quit)
        self.playlist_scan_worker.failed.connect(self.playlist_scan_thread.quit)
        self.playlist_scan_thread.finished.connect(self.playlist_scan_thread.deleteLater)
        self.playlist_scan_thread.start()

    def _on_playlist_scan_finished(self, files: list[str], autoload: bool) -> None:
        '''处理扫描结果并将音频加入播放列表。'''
        added_count = 0
        for file_path in files:
            before = self.playlist_widget.count()
            self.add_to_playlist(file_path)
            added_count += 1 if self.playlist_widget.count() > before else 0
        if autoload:
            self.set_status(f'已自动加载 {added_count} 首历史下载音乐' if added_count > 0 else '已就绪')
        else:
            self.set_status(f'已加入 {added_count} 个本地音频文件')

    def _on_playlist_scan_failed(self, error: str) -> None:
        '''处理扫描失败并显示状态。'''
        self.set_status(f'扫描失败：{error}')

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
        if files:
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

    def shutdown_thread(self, thread: QThread | None, timeout_ms: int = 80) -> None:
        '''请求后台线程退出，短暂等待后强制终止，避免关闭窗口长时间卡顿。'''
        if not thread or not thread.isRunning():
            return
        thread.requestInterruption()
        thread.quit()
        if thread.wait(timeout_ms):
            return
        thread.terminate()
        thread.wait(timeout_ms)

    def closeEvent(self, event) -> None:
        '''关闭窗口时停止后台线程和播放器。'''
        self.hide()
        self.shutdown_player()
        for thread in [self.search_thread, self.download_thread, self.playlist_scan_thread]:
            self.shutdown_thread(thread)
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = MusicdlGUI()
    gui.show()
    sys.exit(app.exec_())
