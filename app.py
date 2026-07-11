import os
import sys
import re
import time
import urllib.request
import traceback
import tempfile
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# PyQt6 Imports
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
    QSlider, QProgressBar, QMessageBox, QGroupBox, QScrollArea
)

# Monkey-patch PIL.Image.ANTIALIAS for MoviePy 1.0.3 compatibility with Pillow 10.0+
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

# MoviePy Imports
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
import moviepy.audio.fx.all as afx

# yt-dlp Import
import yt_dlp

def get_cache_dir():
    """Returns a directory where application data like fonts can be cached."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".shorts_video_generator")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_font_path():
    """Checks and returns a path to a Montserrat-Bold font, downloading if necessary."""
    # 1. Check if PyInstaller bundled it
    bundled_path = resource_path("Montserrat-Bold.ttf")
    if os.path.exists(bundled_path):
        return bundled_path

    # 2. Check local current working dir
    local_path = os.path.abspath("Montserrat-Bold.ttf")
    if os.path.exists(local_path):
        return local_path

    # 3. Check home directory cache
    cache_path = os.path.join(get_cache_dir(), "Montserrat-Bold.ttf")
    if os.path.exists(cache_path):
        return cache_path

    # Download if not found (try multiple candidate URLs)
    urls = [
        "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf",
        "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf",
        "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Bold.ttf"
    ]
    for url in urls:
        try:
            print(f"Attempting to download font from: {url}")
            urllib.request.urlretrieve(url, cache_path)
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
                print(f"Font successfully downloaded from: {url}")
                return cache_path
        except Exception as e:
            print(f"Failed to download font from {url}: {e}")
    
    return None

def load_truetype_font(size):
    """Loads Montserrat-Bold or falls back to system Arial-Bold or default font."""
    font_path = get_font_path()
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass

    # Fallback to system fonts
    system_fonts = [
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf",
        "C:\\Windows\\Fonts\\tahomabd.ttf"
    ]
    for path in system_fonts:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    # Generic lookups (Pillow searches system dirs automatically on Windows/macOS)
    for name in ["arialbd", "Arial-Bold", "Arial Bold", "arial", "impact"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass

    # Hard fallback to default
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def wrap_text(text, font, max_width):
    """Wraps text word-by-word to fit within a maximum pixel width."""
    words = text.split(' ')
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        img = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(img)
        try:
            bbox = draw.textbbox((0, 0), test_line, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(test_line) * (font.size // 2 if hasattr(font, 'size') else 10)
            
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
                
    if current_line:
        lines.append(' '.join(current_line))
    return lines

def draw_text_safely(draw, position, text, font, fill, stroke_width=0, stroke_fill=None):
    """Draws text on PIL image safely, ignoring stroke arguments if using fallback default font."""
    try:
        draw.text(position, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
    except TypeError:
        # Default font does not support stroke parameters
        draw.text(position, text, font=font, fill=fill)

def make_overlay_filter(title, ranking_lines, current_rank_index, title_font, rank_font, title_y, rank_x, rank_y):
    """Returns a function to overlay the main title and cumulative list onto a frame at custom coordinates."""
    def filter_func(image_np):
        # image_np is RGB numpy array of shape (1920, 1080, 3)
        img = Image.fromarray(image_np)
        draw = ImageDraw.Draw(img)

        # Draw Main Title (Centered Horizontally, Y from settings)
        if title:
            lines = wrap_text(title, title_font, 900)
            y_offset = title_y
            for line in lines:
                try:
                    bbox = draw.textbbox((0, 0), line, font=title_font)
                    w = bbox[2] - bbox[0]
                    x = (1080 - w) // 2
                    draw_text_safely(draw, (x, y_offset), line, title_font, (255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0))
                    y_offset += (bbox[3] - bbox[1]) + 15
                except Exception:
                    draw_text_safely(draw, (100, y_offset), line, title_font, (255, 255, 255))
                    y_offset += 80

        # Draw Cumulative Ranking List (X and Y from settings)
        for idx, (rank_num, name) in enumerate(ranking_lines):
            line_text = f"{rank_num}. {name}"
            is_current = (rank_num == current_rank_index)
            # Highlight current playing rank with gold/yellow, rest in white
            fill_color = (255, 223, 0) if is_current else (255, 255, 255)
            
            y_pos = rank_y + idx * 85
            draw_text_safely(draw, (rank_x, y_pos), line_text, rank_font, fill_color, stroke_width=5, stroke_fill=(0, 0, 0))

        return np.array(img)
    return filter_func


# Custom Proglog logger to send progress updates to UI
from proglog import ProgressBarLogger

class PyQtProgressBarLogger(ProgressBarLogger):
    def __init__(self, status_signal, progress_signal, initial_text=""):
        super().__init__()
        self.status_signal = status_signal
        self.progress_signal = progress_signal
        self.last_value = -1
        self.last_message = ""
        self.initial_text = initial_text

    def callback(self, **changes):
        pass

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar == 't':
            total = self.state.get('bars', {}).get('t', {}).get('total', 1)
            if total <= 0:
                total = 1
            if value != self.last_value:
                self.progress_signal.emit(int(value), int(total))
                percentage = int((value / total) * 100)
                msg = f"{self.initial_text}: Frame {int(value)}/{int(total)} ({percentage}%)"
                if msg != self.last_message:
                    self.status_signal.emit(msg)
                    self.last_message = msg
                self.last_value = value


class VideoGeneratorWorker(QThread):
    progress = pyqtSignal(int, int) # current, total
    status = pyqtSignal(str) # messages
    finished = pyqtSignal(str) # output path
    error = pyqtSignal(str) # error info

    def __init__(self, main_title, videos_data, bg_audio_path, bg_volume, output_dir, title_y, rank_x, rank_y):
        super().__init__()
        self.main_title = main_title
        # List of dicts: {"rank": int, "path": str, "url": str, "name": str}
        self.videos_data = videos_data 
        self.bg_audio_path = bg_audio_path
        self.bg_volume = bg_volume # float 0.0 to 1.0
        self.output_dir = output_dir
        # Coordinates
        self.title_y = title_y
        self.rank_x = rank_x
        self.rank_y = rank_y

    def run(self):
        raw_clips = []
        processed_clips = []
        temp_dir = None
        try:
            self.status.emit("Creating temporary directory...")
            temp_dir = tempfile.mkdtemp(prefix="shorts_generator_")

            self.status.emit("Initializing fonts...")
            title_font = load_truetype_font(70)
            rank_font = load_truetype_font(55)

            # Cumulative rankings container
            cumulative_rankings = []

            # Process clips: Rank 5 down to 1
            sorted_videos = sorted(self.videos_data, key=lambda x: x["rank"], reverse=True)

            for idx, video_info in enumerate(sorted_videos):
                rank = video_info["rank"]
                local_path = video_info["path"]
                url = video_info["url"]
                name = video_info["name"]

                path = None

                # 1. Determine and download if URL is provided
                if url:
                    self.status.emit(f"Downloading clip for Rank {rank} using yt-dlp...")
                    ydl_opts = {
                        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                        'outtmpl': os.path.join(temp_dir, f'download_rank_{rank}_%(epoch)s.%(ext)s'),
                        'quiet': True,
                        'no_warnings': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        filename = ydl.prepare_filename(info)
                        
                        # Fallback extensions checking if file is renamed (e.g. combined to .mkv)
                        if os.path.exists(filename):
                            path = filename
                        else:
                            base, _ = os.path.splitext(filename)
                            found = False
                            for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
                                if os.path.exists(base + ext):
                                    path = base + ext
                                    found = True
                                    break
                            if not found or not path:
                                raise FileNotFoundError(f"Could not locate downloaded file for Rank {rank}")
                else:
                    path = local_path

                if not path or not os.path.exists(path):
                    raise FileNotFoundError(f"Source file does not exist for Rank {rank}: {path}")

                self.status.emit(f"Loading and cropping video for Rank {rank}...")
                clip = VideoFileClip(path)
                raw_clips.append(clip)

                # Center crop and resize to 1080x1920
                orig_aspect = clip.w / clip.h
                target_aspect = 1080 / 1920

                if orig_aspect > target_aspect:
                    # Input is wider than 9:16 (landscape) -> scale height to 1920
                    resized = clip.resize(height=1920)
                else:
                    # Input is narrower/taller than 9:16 -> scale width to 1080
                    resized = clip.resize(width=1080)

                cropped = resized.crop(x_center=resized.w / 2, y_center=resized.h / 2, width=1080, height=1920)

                # Update cumulative list of rankings
                cumulative_rankings.append((rank, name))

                # Apply text overlay filter
                filter_func = make_overlay_filter(
                    self.main_title,
                    list(cumulative_rankings), # copy
                    rank, # current active rank index
                    title_font,
                    rank_font,
                    self.title_y,
                    self.rank_x,
                    self.rank_y
                )

                self.status.emit(f"Overlaying text on Video for Rank {rank}...")
                overlayed = cropped.fl_image(filter_func)

                # Fix audio tracks: if the video has no audio, construct silent audio
                if overlayed.audio is None:
                    from moviepy.audio.AudioClip import AudioClip
                    make_silent = lambda t: np.zeros(2) if np.isscalar(t) else np.zeros((len(t), 2))
                    silent_audio = AudioClip(make_silent, duration=overlayed.duration, fps=44100)
                    overlayed = overlayed.set_audio(silent_audio)

                processed_clips.append(overlayed)

            self.status.emit("Concatenating video segments...")
            final_clip = concatenate_videoclips(processed_clips, method="chain")

            # Audio Mixing
            if self.bg_audio_path and os.path.exists(self.bg_audio_path):
                self.status.emit("Mixing background audio track...")
                total_duration = final_clip.duration
                bg_music = AudioFileClip(self.bg_audio_path)
                
                # Apply volume multiplier
                bg_music = bg_music.volumex(self.bg_volume)

                # Loop if too short, otherwise crop
                if bg_music.duration < total_duration:
                    bg_music = afx.audio_loop(bg_music, duration=total_duration)
                else:
                    bg_music = bg_music.subclip(0, total_duration)

                # Smooth fadeout in the last 2 seconds
                bg_music = afx.audio_fadeout(bg_music, 2.0)

                # Combine with original clip audios
                video_audio = final_clip.audio
                if video_audio is not None:
                    mixed_audio = CompositeAudioClip([video_audio, bg_music])
                else:
                    mixed_audio = bg_music

                final_clip = final_clip.set_audio(mixed_audio)

            # Generate descriptive file name
            clean_title = re.sub(r'[^a-zA-Z0-9_\- ]', '', self.main_title).strip().replace(' ', '_')
            if not clean_title:
                clean_title = "ranking_video"

            base_name = clean_title
            counter = 1
            output_filename = f"{base_name}.mp4"
            output_path = os.path.join(self.output_dir, output_filename)

            # Atomically reserve the filename to prevent collision/overwriting
            while True:
                if not os.path.exists(output_path):
                    try:
                        with open(output_path, "xb") as f:
                            pass
                        break
                    except FileExistsError:
                        pass
                output_filename = f"{base_name}_{counter}.mp4"
                output_path = os.path.join(self.output_dir, output_filename)
                counter += 1

            # Render
            self.status.emit("Rendering final compilation...")
            custom_logger = PyQtProgressBarLogger(self.status, self.progress, "Exporting Video")
            
            final_clip.write_videofile(
                output_path,
                fps=30,
                codec="libx264",
                audio_codec="aac",
                threads=4,
                logger=custom_logger
            )

            self.finished.emit(output_path)

        except Exception as e:
            self.error.emit(f"{str(e)}\n\n{traceback.format_exc()}")
        finally:
            # Clean handles
            try:
                if 'final_clip' in locals():
                    final_clip.close()
            except Exception:
                pass
            for c in processed_clips:
                try:
                    c.close()
                except Exception:
                    pass
            for c in raw_clips:
                try:
                    c.close()
                except Exception:
                    pass
            try:
                if 'bg_music' in locals():
                    bg_music.close()
            except Exception:
                pass

            # Cleanup temp files safely
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass


class DragDropLineEdit(QLineEdit):
    """A standard LineEdit with modern Drag and Drop functionality."""
    def __init__(self, placeholder="", file_filter=None, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.file_filter = file_filter # e.g. '.mp4'
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                if not self.file_filter or path.lower().endswith(self.file_filter):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.setText(path)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TikTok & Shorts Ranking Video Generator")
        self.resize(880, 900)
        self.worker = None
        self.init_ui()

    def init_ui(self):
        # Apply dark premium QSS style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QWidget#centralWidget {
                background-color: #121212;
            }
            QLabel {
                color: #e0e0e0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QLabel#titleLabel {
                color: #ffffff;
                font-size: 22px;
                font-weight: bold;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00bcff, stop:1 #8a2be2);
                border-radius: 6px;
                padding: 12px;
                margin-bottom: 5px;
            }
            QGroupBox {
                border: 1px solid #2d2d2d;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #1a1a1a;
                color: #00bcff;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
            }
            QLineEdit {
                background-color: #2b2b2b;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #00bcff;
                background-color: #333333;
            }
            QPushButton {
                background-color: #2b2b2b;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #222222;
            }
            QPushButton#browseBtn {
                background-color: #222222;
                border: 1px solid #3d3d3d;
            }
            QPushButton#browseBtn:hover {
                background-color: #00bcff;
                color: #121212;
                border-color: #00bcff;
            }
            QPushButton#generateBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00bcff, stop:1 #8a2be2);
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 12px 24px;
                font-size: 16px;
                font-weight: bold;
                min-height: 45px;
            }
            QPushButton#generateBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #33ccff, stop:1 #9c4cff);
            }
            QPushButton#generateBtn:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0099cc, stop:1 #6b1cb0);
            }
            QPushButton#generateBtn:disabled {
                background: #2b2b2b;
                color: #777777;
                border: 1px solid #1e1e1e;
            }
            QProgressBar {
                border: 1px solid #2d2d2d;
                border-radius: 5px;
                background-color: #1a1a1a;
                text-align: center;
                color: #ffffff;
                font-weight: bold;
                height: 20px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00bcff, stop:1 #8a2be2);
                border-radius: 4px;
            }
            QSlider::groove:horizontal {
                border: 1px solid #2b2b2b;
                height: 6px;
                background: #2b2b2b;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #00bcff;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 1px solid #00bcff;
                width: 16px;
                height: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #00bcff;
            }
        """)

        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: transparent;")
        
        main_layout = QVBoxLayout(scroll_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # Title Label
        title_lbl = QLabel("Ranking Video Generator")
        title_lbl.setObjectName("titleLabel")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_lbl)

        # Headline Section
        headline_group = QGroupBox("Main Title Settings")
        headline_layout = QVBoxLayout(headline_group)
        headline_layout.setContentsMargins(15, 15, 15, 15)
        
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Enter the main video title (e.g. Top 5 Scariest Minecraft Blocks)")
        self.title_input.setStyleSheet("font-size: 14px; font-weight: 500;")
        headline_layout.addWidget(self.title_input)
        main_layout.addWidget(headline_group)

        # Text Position Customization Section
        text_pos_group = QGroupBox("Text Position Settings")
        text_pos_layout = QVBoxLayout(text_pos_group)
        text_pos_layout.setContentsMargins(15, 15, 15, 15)
        text_pos_layout.setSpacing(10)

        # 1. Title Y Position Slider
        title_y_container = QHBoxLayout()
        self.title_y_lbl = QLabel("Title Y Position: 150px")
        self.title_y_lbl.setFixedWidth(180)
        self.title_y_slider = QSlider(Qt.Orientation.Horizontal)
        self.title_y_slider.setRange(0, 1920)
        self.title_y_slider.setValue(150)
        self.title_y_slider.valueChanged.connect(lambda v: self.title_y_lbl.setText(f"Title Y Position: {v}px"))
        title_y_container.addWidget(self.title_y_lbl)
        title_y_container.addWidget(self.title_y_slider)
        text_pos_layout.addLayout(title_y_container)

        # 2. Ranking X Position Slider
        rank_x_container = QHBoxLayout()
        self.rank_x_lbl = QLabel("Ranking X Position: 100px")
        self.rank_x_lbl.setFixedWidth(180)
        self.rank_x_slider = QSlider(Qt.Orientation.Horizontal)
        self.rank_x_slider.setRange(0, 1080)
        self.rank_x_slider.setValue(100)
        self.rank_x_slider.valueChanged.connect(lambda v: self.rank_x_lbl.setText(f"Ranking X Position: {v}px"))
        rank_x_container.addWidget(self.rank_x_lbl)
        rank_x_container.addWidget(self.rank_x_slider)
        text_pos_layout.addLayout(rank_x_container)

        # 3. Ranking Y Position Slider
        rank_y_container = QHBoxLayout()
        self.rank_y_lbl = QLabel("Ranking Y Position: 1100px")
        self.rank_y_lbl.setFixedWidth(180)
        self.rank_y_slider = QSlider(Qt.Orientation.Horizontal)
        self.rank_y_slider.setRange(0, 1920)
        self.rank_y_slider.setValue(1100)
        self.rank_y_slider.valueChanged.connect(lambda v: self.rank_y_lbl.setText(f"Ranking Y Position: {v}px"))
        rank_y_container.addWidget(self.rank_y_lbl)
        rank_y_container.addWidget(self.rank_y_slider)
        text_pos_layout.addLayout(rank_y_container)

        main_layout.addWidget(text_pos_group)

        # 5 Video Cards Section (Rank 5 down to 1)
        slots_container = QGroupBox("Video Clips Settings")
        slots_layout = QVBoxLayout(slots_container)
        slots_layout.setContentsMargins(10, 15, 10, 15)
        slots_layout.setSpacing(15)

        self.video_slots = []
        for i in range(5, 0, -1):
            slot_group = QGroupBox(f"Video {i} (Rank {i})")
            slot_layout = QGridLayout(slot_group)
            slot_layout.setContentsMargins(12, 12, 12, 12)
            slot_layout.setSpacing(8)

            # Columns widths
            slot_layout.setColumnStretch(0, 1) # labels
            slot_layout.setColumnStretch(1, 4) # input edits
            slot_layout.setColumnStretch(2, 1) # browse button

            # 1. Rank name input
            slot_layout.addWidget(QLabel("Rank Name:"), 0, 0)
            name_edit = QLineEdit()
            name_edit.setPlaceholderText(f"Display name for Rank {i} (e.g. Diamond Ore)")
            slot_layout.addWidget(name_edit, 0, 1, 1, 2)

            # 2. Local File input
            slot_layout.addWidget(QLabel("Local File:"), 1, 0)
            path_edit = DragDropLineEdit(f"Path to Rank {i} MP4 clip (drag & drop here)", ".mp4")
            slot_layout.addWidget(path_edit, 1, 1)
            
            browse_btn = QPushButton("Browse")
            browse_btn.setObjectName("browseBtn")
            browse_btn.clicked.connect(lambda checked, pe=path_edit: self.browse_video(pe))
            slot_layout.addWidget(browse_btn, 1, 2)

            # 3. URL input
            slot_layout.addWidget(QLabel("Or Video URL:"), 2, 0)
            url_edit = QLineEdit()
            url_edit.setPlaceholderText(f"Paste YouTube/TikTok URL for Rank {i} (takes precedence)")
            slot_layout.addWidget(url_edit, 2, 1, 1, 2)

            slots_layout.addWidget(slot_group)
            
            self.video_slots.append({
                "rank": i,
                "name_widget": name_edit,
                "path_widget": path_edit,
                "url_widget": url_edit
            })

        main_layout.addWidget(slots_container)

        # Background Audio Settings
        audio_group = QGroupBox("Background Music Settings")
        audio_layout = QGridLayout(audio_group)
        audio_layout.setContentsMargins(15, 15, 15, 15)
        audio_layout.setSpacing(10)

        audio_layout.addWidget(QLabel("Audio File:"), 0, 0)
        self.audio_path_input = DragDropLineEdit("Path to background MP3/WAV file (Optional)", ".mp3")
        audio_layout.addWidget(self.audio_path_input, 0, 1)

        self.audio_browse_btn = QPushButton("Browse")
        self.audio_browse_btn.setObjectName("browseBtn")
        self.audio_browse_btn.clicked.connect(self.browse_audio)
        audio_layout.addWidget(self.audio_browse_btn, 0, 2)

        audio_layout.addWidget(QLabel("Music Volume:"), 1, 0)
        
        # Horizontal slider container
        vol_container = QHBoxLayout()
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(25)
        self.vol_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.vol_slider.setTickInterval(10)
        
        self.vol_lbl = QLabel("25%")
        self.vol_lbl.setFixedWidth(40)
        self.vol_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.vol_lbl.setStyleSheet("font-weight: bold; color: #00bcff;")
        
        self.vol_slider.valueChanged.connect(lambda v: self.vol_lbl.setText(f"{v}%"))
        
        vol_container.addWidget(self.vol_slider)
        vol_container.addWidget(self.vol_lbl)
        audio_layout.addLayout(vol_container, 1, 1, 1, 2)

        main_layout.addWidget(audio_group)

        # Output Section
        output_group = QGroupBox("Output Settings")
        output_layout = QGridLayout(output_group)
        output_layout.setContentsMargins(15, 15, 15, 15)
        output_layout.setSpacing(10)

        output_layout.addWidget(QLabel("Output Dir:"), 0, 0)
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Select directory to save final output video")
        output_layout.addWidget(self.output_dir_input, 0, 1)

        self.output_browse_btn = QPushButton("Browse")
        self.output_browse_btn.setObjectName("browseBtn")
        self.output_browse_btn.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(self.output_browse_btn, 0, 2)

        main_layout.addWidget(output_group)

        # Generate / Progress Area
        gen_layout = QVBoxLayout()
        gen_layout.setSpacing(10)

        self.generate_btn = QPushButton("GENERATE VIDEO")
        self.generate_btn.setObjectName("generateBtn")
        self.generate_btn.clicked.connect(self.start_generation)
        gen_layout.addWidget(self.generate_btn)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setStyleSheet("font-weight: 500; color: #a0a0a0; font-size: 13px;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gen_layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        gen_layout.addWidget(self.progress_bar)

        main_layout.addLayout(gen_layout)

        scroll_area.setWidget(scroll_widget)
        
        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll_area)

    def browse_video(self, target_line_edit):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select MP4 Video Clip", "", "Video Files (*.mp4 *.mov *.avi)"
        )
        if file_path:
            target_line_edit.setText(file_path)

    def browse_audio(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Background Audio File", "", "Audio Files (*.mp3 *.wav *.m4a)"
        )
        if file_path:
            self.audio_path_input.setText(file_path)

    def browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_input.setText(dir_path)

    def toggle_ui(self, enabled):
        """Enables or disables UI elements during generation."""
        self.title_input.setEnabled(enabled)
        self.title_y_slider.setEnabled(enabled)
        self.rank_x_slider.setEnabled(enabled)
        self.rank_y_slider.setEnabled(enabled)
        
        for slot in self.video_slots:
            slot["name_widget"].setEnabled(enabled)
            slot["path_widget"].setEnabled(enabled)
            slot["url_widget"].setEnabled(enabled)

        self.audio_path_input.setEnabled(enabled)
        self.vol_slider.setEnabled(enabled)
        self.output_dir_input.setEnabled(enabled)
        self.generate_btn.setEnabled(enabled)
        
        self.audio_browse_btn.setEnabled(enabled)
        self.output_browse_btn.setEnabled(enabled)
        # Find and disable all browse buttons within the layout
        for child in self.findChildren(QPushButton):
            if child.objectName() == "browseBtn":
                child.setEnabled(enabled)

    def validate_inputs(self):
        """Validates UI inputs before starting rendering."""
        # 1. Main Title
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Validation Error", "Main Title is required.")
            return False

        # 2. Videos: check either URL or local file path
        for slot in self.video_slots:
            path = slot["path_widget"].text().strip()
            url = slot["url_widget"].text().strip()
            name = slot["name_widget"].text().strip()
            rank = slot["rank"]

            if not path and not url:
                QMessageBox.warning(
                    self, 
                    "Validation Error", 
                    f"Either a local file path OR a video URL must be provided for Rank {rank}."
                )
                return False

            if path and not url and not os.path.exists(path):
                QMessageBox.warning(self, "Validation Error", f"Local video file for Rank {rank} does not exist:\n{path}")
                return False

            if not name:
                QMessageBox.warning(self, "Validation Error", f"Name label is required for Rank {rank}.")
                return False

        # 3. Audio (if provided)
        audio_path = self.audio_path_input.text().strip()
        if audio_path and not os.path.exists(audio_path):
            QMessageBox.warning(self, "Validation Error", f"Background music file does not exist:\n{audio_path}")
            return False

        # 4. Output Dir
        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "Validation Error", "Output Directory is required.")
            return False
        if not os.path.isdir(output_dir):
            QMessageBox.warning(self, "Validation Error", f"Output Directory is not a valid folder:\n{output_dir}")
            return False

        return True

    def start_generation(self):
        if not self.validate_inputs():
            return

        # Prepare arguments
        main_title = self.title_input.text().strip()
        
        videos_data = []
        for slot in self.video_slots:
            videos_data.append({
                "rank": slot["rank"],
                "path": slot["path_widget"].text().strip(),
                "url": slot["url_widget"].text().strip(),
                "name": slot["name_widget"].text().strip()
            })

        bg_audio_path = self.audio_path_input.text().strip()
        bg_volume = self.vol_slider.value() / 100.0
        output_dir = self.output_dir_input.text().strip()

        # Coordinates
        title_y = self.title_y_slider.value()
        rank_x = self.rank_x_slider.value()
        rank_y = self.rank_y_slider.value()

        # Update UI state
        self.toggle_ui(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Starting video generation...")

        # Initialize thread
        self.worker = VideoGeneratorWorker(
            main_title=main_title,
            videos_data=videos_data,
            bg_audio_path=bg_audio_path,
            bg_volume=bg_volume,
            output_dir=output_dir,
            title_y=title_y,
            rank_x=rank_x,
            rank_y=rank_y
        )

        # Connect signals
        self.worker.progress.connect(self.on_progress)
        self.worker.status.connect(self.on_status)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)

        # Run QThread
        self.worker.start()

    def on_progress(self, current, total):
        if total > 0:
            val = int((current / total) * 100)
            self.progress_bar.setValue(val)

    def on_status(self, msg):
        self.status_lbl.setText(msg)

    def on_finished(self, output_path):
        self.progress_bar.setValue(100)
        self.status_lbl.setText("Generation complete!")
        self.toggle_ui(True)
        
        QMessageBox.information(
            self,
            "Success",
            f"Successfully generated vertical ranking video!\n\nSaved to: {output_path}"
        )
        self.progress_bar.setVisible(False)
        self.status_lbl.setText("Ready")

    def on_error(self, err_details):
        self.toggle_ui(True)
        self.progress_bar.setVisible(False)
        self.status_lbl.setText("Error occurred during generation.")

        QMessageBox.critical(
            self,
            "Rendering Error",
            f"An error occurred during video rendering:\n\n{err_details}"
        )


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
