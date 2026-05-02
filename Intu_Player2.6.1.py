import sys
import os
import json
import re 
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QLabel, QSlider, QListWidget, QStyle,
    QSizePolicy, QDialog, QAbstractItemView, QComboBox, QListWidgetItem,QMessageBox,QMenu
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices
from PyQt6.QtCore import Qt, QUrl, QDir, QTime, QByteArray
from PyQt6.QtGui import QPixmap, QResizeEvent, QCloseEvent,QAction
import urllib.request
import json
from pypinyin import lazy_pinyin

SETTINGS_FILE = "settings.json"

DARK_STYLE_SHEET = """
QMainWindow, QDialog, QWidget {background-color: #2b2b2b; color: #f0f0f0;}

QPushButton {background-color: #505050; color: #f0f0f0; border: 1px solid #606060; padding: 5px 10px; border-radius: 4px;}

QPushButton:hover {background-color: #606060;}

QPushButton:pressed {background-color: #707070;}

QLabel {color: #f0f0f0;}

QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #3a3a3a;
    margin: 0px;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #43ba73;
    border: none;
    width: 14px;
    height: 14px;
    margin: -4px 0; /* 垂直居中穿在横条上 */
    border-radius: 7px;
}

QSlider::sub-page:horizontal {
    background: #43ba73;
    border-radius: 2px;
}

QSlider::add-page:horizontal {
    background: #3a3a3a;
    border-radius: 2px;
}





QListWidget {background-color: #3c3c3c; color: #f0f0f0; border: 1px solid #505050; selection-background-color: #0078d4; selection-color: #ffffff;}

QListWidget::item:hover {background-color: #555555;}

"""

# =================== 进度条点击跳转：1 ===================
class ClickableSlider(QSlider):
    """支持点击跳转和拖动的 QSlider（不显示预览标签）"""
    def __init__(self, parent=None):
        super().__init__(parent)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_slider(event)
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._update_slider(event)
            event.accept()
        super().mouseMoveEvent(event)

    def _update_slider(self, event):
        try:
            x = max(0, min(event.position().toPoint().x(), self.width()))
            ratio = x / self.width()
            value = self.minimum() + ratio * (self.maximum() - self.minimum())
            self.setValue(int(value))
            self.sliderMoved.emit(int(value))
        except Exception as e:
            print("_update_slider error:", e)

# =================== 图片显示标签 ===================
class ImageDisplayLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(1, 1)
        self.setStyleSheet("background-color: #3c3c3c; border: 1px solid #505050;")
        self._original_pixmap = QPixmap()

    def setOriginalPixmap(self, pixmap: QPixmap):
        self._original_pixmap = pixmap
        if not self._original_pixmap.isNull():
            super().setText("")
            self._scale_pixmap()
        else:
            super().setPixmap(QPixmap())
            super().setText("无图片")

    def _scale_pixmap(self):
        if self._original_pixmap.isNull(): return
        label_size = self.size()
        if label_size.width() <= 0 or label_size.height() <= 0: return
        scaled_pixmap = self._original_pixmap.scaled(
            label_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        super().setPixmap(scaled_pixmap)

    def resizeEvent(self, event: QResizeEvent):
        if event.oldSize() != event.size():
            self._scale_pixmap()
        super().resizeEvent(event)

# =================== 播放列表 ===================
class PlaylistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("播放列表")
        self.setGeometry(200, 200, 300, 400)
        self.parent = parent
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.playlist_widget = QListWidget()
        self.playlist_widget.itemDoubleClicked.connect(self.item_double_clicked)
        self.playlist_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.playlist_widget)
        
        button_layout = QHBoxLayout()
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.refresh_list)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(close_button)
        layout.addLayout(button_layout)

    def item_double_clicked(self, item):
        if self.parent:
            file_path = item.data(Qt.ItemDataRole.UserRole)
            if file_path:
                self.parent.playlist_file_double_clicked(file_path)
                self.close()

    def refresh_list(self):
        if self.parent:
            self.parent.reload_current_directory_playlist()

# =================== 主播放器 ===================
class AudioPlayer(QMainWindow):
    AUDIO_EXTENSIONS = ('.mp3', '.wav', '.flac', '.ogg', '.m4a')
    IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif')

    def __init__(self):
        super().__init__()
        self.setWindowTitle("音图播放器")
        from PyQt6.QtGui import QIcon
        # 获取运行时路径（兼容打包后）
        def resource_path(relative_path):
            if hasattr(sys, '_MEIPASS'):
                return os.path.join(sys._MEIPASS, relative_path)
            return os.path.join(os.path.abspath("."), relative_path)
        # 使用打包后的路径加载图标
        self.setWindowIcon(QIcon(resource_path("huamao.ico")))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.image_timeline = [] 
        self.current_image_index = -1 
        
        self.last_dir = ""
        self.last_device_desc = ""
        self.playlist_memory = []
        self.current_file_path = None
        self.window_geometry = None 
        
        self.load_settings()

        if self.window_geometry:
            self.restoreGeometry(self.window_geometry)
        else:
            self.setGeometry(200, 200, 800, 500)

        self.player = QMediaPlayer()
        self.audio_devices = sorted(QMediaDevices.audioOutputs(), key=lambda d: d.description()) 

        if self.audio_devices:
            default_device = next((d for d in self.audio_devices if d.description() == self.last_device_desc),
                                  self.audio_devices[0])
            self.audio_output = QAudioOutput(default_device)
        else:
            self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)

        self.playlist = []
        self.current_index = -1

        main_container = QWidget()
        full_layout = QVBoxLayout(main_container)
        full_layout.setContentsMargins(10, 10, 10, 10)
        full_layout.setSpacing(10)
        self.setCentralWidget(main_container)

        self.image_label = ImageDisplayLabel("无图片")
        full_layout.addWidget(self.image_label, 20)

        control_container = QVBoxLayout()
        progress_layout = QHBoxLayout()
        self.position_label = QLabel("00:00")
        self.duration_label = QLabel("00:00")
        
        self.position_slider = ClickableSlider(self)
        self.position_slider.setOrientation(Qt.Orientation.Horizontal)

        
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.set_position)
        progress_layout.addWidget(self.position_label)
        progress_layout.addWidget(self.position_slider, 1)
        progress_layout.addWidget(self.duration_label)
        control_container.addLayout(progress_layout)

        self.open_button = QPushButton("打开文件")
        self.open_button.clicked.connect(self.open_file)
        self.previous_button = QPushButton()
        self.previous_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipBackward))
        self.previous_button.clicked.connect(self.play_previous)
        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_button.clicked.connect(self.play_pause)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.clicked.connect(self.stop)
        self.next_button = QPushButton()
        self.next_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaSkipForward))
        self.next_button.clicked.connect(self.play_next)
        self.playlist_button = QPushButton("列表")
        self.playlist_button.clicked.connect(self.show_playlist)

        # ========== 新增：关于按钮 ==========
        self.about_button = QPushButton("关于")
        self.about_button.setStyleSheet("QPushButton::menu-indicator { image: none; }")
        
        self.about_menu = QMenu(self.about_button)
        
        self.contact_action = QAction("联系作者", self)
        self.contact_action.triggered.connect(self.show_contact)
        self.about_menu.addAction(self.contact_action)
        
        self.update_action = QAction("检查更新", self)
        self.update_action.triggered.connect(self.check_update_manual)
        self.about_menu.addAction(self.update_action)
        
        self.about_button.setMenu(self.about_menu)
        # ========== 关于按钮结束 ==========
        self.device_button = QPushButton("声卡")
        self.device_button.clicked.connect(self.toggle_device_combo) 
        self.device_combo = QComboBox()
        self.device_combo.addItems([d.description() for d in self.audio_devices])
        if self.last_device_desc in [d.description() for d in self.audio_devices]:
            self.device_combo.setCurrentText(self.last_device_desc)
        self.device_combo.currentIndexChanged.connect(self.change_audio_device)
        self.device_combo.currentIndexChanged.connect(self.device_combo.hide) 
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(lambda val: self.audio_output.setVolume(val/100))

        control_layout = QHBoxLayout()
        for w in [self.open_button, self.previous_button, self.play_button, self.stop_button,
                  self.next_button, self.playlist_button, self.device_button, self.volume_slider]:
            control_layout.addWidget(w)
            
        control_layout.addStretch()  # 弹性空间，把 about_button 推到右边
        control_layout.addWidget(self.about_button)  # 关于按钮放最右边

        control_container.addLayout(control_layout)
        full_layout.addLayout(control_container)
        self.device_combo.hide() 

        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.handle_media_status_change)
        self.player.playbackStateChanged.connect(self.update_play_button_icon)

        self.playlist_dialog = PlaylistDialog(self)

        if self.playlist_memory:
            self.playlist = self.playlist_memory
            self.playlist_dialog.playlist_widget.clear()
            for f in self.playlist:
                item = QListWidgetItem(os.path.basename(f))
                item.setData(Qt.ItemDataRole.UserRole, f)
                self.playlist_dialog.playlist_widget.addItem(item)
            if self.current_file_path in self.playlist:
                self.current_index = self.playlist.index(self.current_file_path)
                # 修改这里：只加载文件但不播放
                self.player.setSource(QUrl.fromLocalFile(self.current_file_path))
                self.load_image(self.current_file_path)
                self.playlist_dialog.playlist_widget.setCurrentRow(self.current_index)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_pause()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        self.save_settings()
        super().closeEvent(event)

    def format_time(self, ms):
        t = QTime(0, 0, 0).addMSecs(ms)
        return t.toString("mm:ss") if ms < 3600000 else t.toString("hh:mm:ss")
        
    def _parse_time_to_ms(self, match):
        """
        根据正则表达式匹配结果，将 mmss 格式的时间转换为毫秒 (ms)。
        match 包含两个捕获组：(分钟数，可多位) 和 (秒数，2位)。
        """
        try:
            # 捕获组 1 是分钟数，捕获组 2 是秒数
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            
            # 确保秒数不超过 59
            if seconds > 59:
                 return -1 
            return (minutes * 60 + seconds) * 1000
        except ValueError:
            return -1

    def set_position(self, pos):
        self.player.setPosition(pos)
        self.switch_image_by_time(pos)

    def update_position(self, pos):
        if not self.position_slider.isSliderDown(): 
            self.position_slider.setValue(pos)
        self.position_label.setText(self.format_time(pos))
        self.switch_image_by_time(pos)

    def update_duration(self, dur):
        self.position_slider.setRange(0, dur)
        self.duration_label.setText(self.format_time(dur))

    def toggle_device_combo(self):
        self.device_combo.showPopup() 

    def open_file(self):
        filter_str = f"音频文件 ({' '.join(['*' + ext for ext in self.AUDIO_EXTENSIONS])})"
        file_path, _ = QFileDialog.getOpenFileName(self, "选择音频文件", self.last_dir, filter_str)
        if not file_path: return
        self.last_dir = os.path.dirname(file_path)
        normalized = os.path.abspath(file_path).replace(os.sep, '/')
        self.load_directory_to_playlist(os.path.dirname(normalized))
        self.play_file(normalized)
        try:
            self.current_index = self.playlist.index(normalized)
            self.playlist_dialog.playlist_widget.setCurrentRow(self.current_index)
        except ValueError:
            self.current_index = -1
        self.save_settings()

    def reload_current_directory_playlist(self):
        current_dir = None
        if self.current_file_path:
            current_dir = os.path.dirname(self.current_file_path)
        elif self.last_dir:
            current_dir = self.last_dir

        if current_dir and os.path.isdir(current_dir):
            was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            current_pos = self.player.position() if was_playing else 0
            
            self.load_directory_to_playlist(current_dir)
            
            if self.current_file_path in self.playlist:
                self.current_index = self.playlist.index(self.current_file_path)
                self.playlist_dialog.playlist_widget.setCurrentRow(self.current_index)
                self.player.setSource(QUrl.fromLocalFile(self.current_file_path))
                self.player.setPosition(current_pos)
                
                if was_playing:
                    self.player.play()
                
                self.load_image(self.current_file_path)
                self.switch_image_by_time(current_pos)
            else:
                self.stop()
                self.current_index = -1
                self.current_file_path = None
        
        self.save_settings()

    def load_directory_to_playlist(self, directory):
        self.playlist.clear()
        self.playlist_dialog.playlist_widget.clear()
        dir_obj = QDir(directory)
        name_filters = [f"*{ext}" for ext in self.AUDIO_EXTENSIONS]
        files = [f.absoluteFilePath().replace(os.sep, '/') for f in dir_obj.entryInfoList(name_filters, QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)]
        files.sort(key=lambda path: ''.join(lazy_pinyin(os.path.basename(path))))
        self.playlist = files
        self.playlist_memory = files 
        
        for f in self.playlist:
            item = QListWidgetItem(os.path.basename(f))
            item.setData(Qt.ItemDataRole.UserRole, f)
            self.playlist_dialog.playlist_widget.addItem(item)
            
    def play_file(self, file_path):
        self.current_file_path = file_path
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(file_path))
        self.load_image(file_path)
        # 移除了自动播放的代码，现在只有用户点击播放按钮才会播放
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.save_settings()

    def playlist_file_double_clicked(self, file_path):
        try:
            index = self.playlist.index(file_path)
            if 0 <= index < len(self.playlist):
                self.current_index = index
                self.play_file(self.playlist[index])
                self.playlist_dialog.playlist_widget.setCurrentRow(self.current_index)
                # 双击列表项时自动播放
                self.player.play()
                self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        except ValueError:
            pass

    def play_pause(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        else:
            if self.player.source().isEmpty() and self.current_file_path:
                self.player.setSource(QUrl.fromLocalFile(self.current_file_path))
            self.player.play()
            self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def stop(self):
        self.player.stop()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.image_timeline = []
        self.current_image_index = -1
        self.image_label.setOriginalPixmap(QPixmap())

    def play_previous(self):
        if not self.playlist: return
        self.current_index = (self.current_index - 1) % len(self.playlist)
        self.play_file(self.playlist[self.current_index])
        self.playlist_dialog.playlist_widget.setCurrentRow(self.current_index)
        self.player.play()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def play_next(self):
        if not self.playlist: return
        self.current_index = (self.current_index + 1) % len(self.playlist)
        self.play_file(self.playlist[self.current_index])
        self.playlist_dialog.playlist_widget.setCurrentRow(self.current_index)
        self.player.play()
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def show_playlist(self):
        self.playlist_dialog.show()

    def handle_media_status_change(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.play_next()

    def update_play_button_icon(self, state):
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        elif state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))

    def change_audio_device(self, index):
        if 0 <= index < len(self.audio_devices):
            device = self.audio_devices[index]
            self.last_device_desc = device.description()
            new_output = QAudioOutput(device)
            new_output.setVolume(self.audio_output.volume())
            self.audio_output = new_output
            self.player.setAudioOutput(self.audio_output)
            if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState and self.current_file_path:
                pos = self.player.position()
                self.player.setSource(QUrl.fromLocalFile(self.current_file_path))
                self.player.setPosition(pos)
                self.player.play()
            self.save_settings()

    # ************************** 切换图片核心逻辑 **************************

    def switch_image_by_time(self, current_pos):
        """根据当前播放位置 (ms) 检查并切换图片"""
        if not self.image_timeline:
            return

        next_index = self.current_image_index
        
        # 1. 正常播放时，检查下一张图片 (容错 50ms)
        # 避免列表越界，并检查是否已超过下一张图片的切换时间
        if next_index + 1 < len(self.image_timeline) and current_pos >= self.image_timeline[next_index + 1]['start_time'] - 50:
            next_index += 1
        
        # 2. 用户拖动滑块或跳转时，需要重新搜索 (检查当前图片是否正确)
        elif next_index == -1 or current_pos < self.image_timeline[next_index]['start_time'] - 50: 
            found_index = -1
            # 从后向前查找，找到第一个时间点小于等于当前位置的图片
            for i in range(len(self.image_timeline) - 1, -1, -1):
                if current_pos >= self.image_timeline[i]['start_time']:
                    found_index = i
                    break
            next_index = found_index


        if next_index != -1 and next_index != self.current_image_index:
            self.current_image_index = next_index
            image_info = self.image_timeline[self.current_image_index]
            image_path = image_info['full_path']
            
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                self.image_label.setOriginalPixmap(pixmap)
            else:
                self.image_label.setOriginalPixmap(QPixmap())

    def load_image(self, audio_path):
        """
        加载图片配置。
        扫描所有符合 [音频文件名] + [可选分隔符] + [可选时间戳mmSS] + [扩展名] 格式的图片。
        例如：aF.jpg, aF_0120.jpg
        """
        audio_filename = os.path.basename(audio_path)
        base_name, _ = os.path.splitext(audio_filename)
        audio_dir = os.path.dirname(audio_path)
        
        self.image_timeline = []
        self.current_image_index = -1
        
        # 预先转义 base_name，以安全地用于正则表达式
        # 这确保了 base_name 中的 #、. 等特殊字符被正确匹配
        escaped_base_name = re.escape(base_name)
        
        # 遍历音频文件所在目录下的所有文件
        for file_name in os.listdir(audio_dir):
            full_path = os.path.join(audio_dir, file_name).replace(os.sep, '/')
            file_base, file_ext = os.path.splitext(file_name)
            
            # 1. 检查是否为标准 0ms 首图 (例如：aF.jpg 或 苹果香#F.jpg)
            if file_ext.lower() in self.IMAGE_EXTENSIONS and file_base.lower() == base_name.lower():
                # 检查是否已存在 0ms 的图（防止重复添加）
                if not any(item['start_time'] == 0 and item['original_filename'] == file_name for item in self.image_timeline):
                    self.image_timeline.append({
                        'start_time': 0, # 默认时间 0ms
                        'full_path': full_path,
                        'original_filename': file_name
                    })
                continue
            
            # 2. 匹配带有 mmss 时间戳的图片 (例如：aF_0120.jpg)
            # 正则解释：
            # ^                      : 字符串开头
            # {escaped_base_name}    : 严格匹配音频文件名主体 (已转义，如 苹果香\#F)
            # _                      : 匹配下划线分隔符
            # (\d+)                  : 捕获组1：分钟数 (mm 或 mmm...)
            # (\d{2})                : 捕获组2：秒数 (ss)
            # \.                     : 匹配点号
            # (?:...)                : 匹配任意图片扩展名 (非捕获组)
            
            # 注意：这里要求必须是 base_name 后面紧跟着 _mmSS
            ext_patterns = "|".join(re.escape(ext.lstrip('.')) for ext in self.IMAGE_EXTENSIONS)
            time_pattern = rf'^{escaped_base_name}_(\d+)(\d{{2}})\.({ext_patterns})$'
            
            match = re.search(time_pattern, file_name, re.IGNORECASE)

            if match:
                start_time_ms = self._parse_time_to_ms(match)
                
                # 只有带有效时间戳的图片 (start_time_ms > 0) 才加入时间轴
                if start_time_ms > 0:
                    self.image_timeline.append({
                        'start_time': start_time_ms,
                        'full_path': full_path,
                        'original_filename': file_name
                    })

        # --- 清理和排序逻辑 ---
        
        # 1. 如果没有 0ms 的图
        if not any(item['start_time'] == 0 for item in self.image_timeline):
            # 尝试查找 aF_0000.jpg 这种文件作为 0ms 补充
            for ext in self.IMAGE_EXTENSIONS:
                 temp_path = os.path.join(audio_dir, base_name + '_0000' + ext).replace(os.sep, '/')
                 if os.path.exists(temp_path):
                     self.image_timeline.append({'start_time': 0, 'full_path': temp_path, 'original_filename': os.path.basename(temp_path)})
                     break # 找到就够了

        # 2. 排序时间轴（确保 0ms 位于第一位，并且时间点按升序排列）
        self.image_timeline.sort(key=lambda x: x['start_time'])
        
        # 3. 如果时间轴不为空，显示第一张图片 (0ms)
        if self.image_timeline:
            self.current_image_index = 0
            zero_ms_path = self.image_timeline[0]['full_path']
            
            pixmap = QPixmap(zero_ms_path)
            self.image_label.setOriginalPixmap(pixmap)
        else:
            self.image_label.setOriginalPixmap(QPixmap())


# =============增加关于按钮=========================
    def show_contact(self):
        QMessageBox.information(
            self,
            "联系作者",
            "邮箱：je833kg@163.com\n\n微信：lsl548748\n\n欢迎反馈问题或建议！"
        )


    def check_update_manual(self):
        import urllib.request
        import json
        
        try:
            req = urllib.request.Request(
                "https://intu.iandyou.dpdns.org",
                headers={"User-Agent": f"intu-player/{CURRENT_VERSION}"}
            )
            
            # timeout 放在 urlopen 里
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                latest = data.get("version", CURRENT_VERSION)
                total = data.get("total_users", 0)
                url = data.get("latest_url", "")
                
                if latest != CURRENT_VERSION:
                    msg = QMessageBox(self)
                    msg.setWindowTitle("发现新版本")
                    msg.setTextFormat(Qt.TextFormat.RichText)
                    msg.setText(
                        f"<p>当前版本：<b>{CURRENT_VERSION}</b></p>"
                        f"<p>最新版本：<b style='color:red;'>{latest}</b></p>"
                        f"<p>已有 {total:,} 位小伙伴在使用</p>"
                        f"<p><a href='{url.strip()}'>{url.strip()}</a></p>"
                    )
                    msg.setInformativeText("建议更新以获得更好体验")
                    msg.setStandardButtons(QMessageBox.Ok)
                    msg.exec()
                else:
                    QMessageBox.information(
                        self,
                        "检查更新",
                        f"当前版本 {CURRENT_VERSION}\n\n已经是最新版本！\n\n已有 {total:,} 位小伙伴在使用本工具"
                    )
                    
        except Exception as e:
            QMessageBox.warning(
                self,
                "检查失败",
                f"无法连接到更新服务器：{str(e)}\n\n请检查网络后重试。"
            )
# ================== 保存/加载设置 ==================
    def save_settings(self):
        data = {
            "last_dir": self.last_dir,
            "last_device_desc": self.last_device_desc,
            "playlist_memory": self.playlist_memory,
            "current_file_path": self.current_file_path,
            "window_geometry": self.saveGeometry().toBase64().data().decode('utf-8')
        }
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.last_dir = data.get("last_dir", "")
                    self.last_device_desc = data.get("last_device_desc", "")
                    self.playlist_memory = data.get("playlist_memory", [])
                    self.current_file_path = data.get("current_file_path", None)
                    geometry_base64 = data.get("window_geometry")
                    if geometry_base64:
                        self.window_geometry = QByteArray.fromBase64(geometry_base64.encode('utf-8'))
            except json.JSONDecodeError:
                pass


CURRENT_VERSION = "2.6"  # ← 必须与 Worker 返回的 version 一致
#API_URL = "https://intu.iandyou.dpdns.org"



# =================== 运行程序 ===================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE_SHEET)
    player = AudioPlayer()
    player.show()
    sys.exit(app.exec())
