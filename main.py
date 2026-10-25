import sys
import os
import time
import math
import random
import threading
import webbrowser
import urllib.parse
import logging
from datetime import datetime
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple

import speech_recognition as sr
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QHBoxLayout, QInputDialog, QTextEdit, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QMovie, QPixmap, QPainter, QFont, QCursor, QTransform

from brain import ConfigManager, DragonBrain
from app_scanner import AbsoluteAppScanner
from settings_ui import SettingsDialog

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    filename="dragon.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)


def exception_hook(exctype, value, tb):
    logging.critical("КРИТИЧЕСКИЙ СБОЙ!", exc_info=(exctype, value, tb))
    sys.__excepthook__(exctype, value, tb)


sys.excepthook = exception_hook

# --- ЗАПРОС ПРАВ АДМИНИСТРАТОРА ---


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


if not is_admin():
    params = " ".join([f'"{arg}"' for arg in sys.argv])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

# --- WIN32 API ---
user32 = ctypes.windll.user32


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG)
    ]


def get_foreground_window() -> Tuple[Optional[int], Optional[Tuple[int, int, int, int]]]:
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindow(hwnd):
            return None, None
        rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w > 200 and h > 150:
                return hwnd, (rect.left, rect.top, w, h)
    except Exception:
        pass
    return None, None


def send_key_event(vk_code: int) -> None:
    user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_code, 0, 2, 0)


def minimize_all_windows() -> None:
    user32.keybd_event(0x5B, 0, 0, 0)
    user32.keybd_event(0x44, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(0x44, 0, 2, 0)
    user32.keybd_event(0x5B, 0, 2, 0)


VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_PLAY_PAUSE = 0xB3


# --- УГЛОВАЯ ПАНЕЛЬ HUD ---
class CornerChatHUD(QWidget):
    mic_toggled = pyqtSignal()
    settings_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    text_command_sent = pyqtSignal(str)

    def __init__(self, cfg: ConfigManager, user_name: str) -> None:
        super().__init__()
        self.cfg = cfg
        self.user_name = user_name
        self.chat_visible = True
        self.init_ui()
        self.apply_dynamic_styles()

    def init_ui(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QWidget()
        self.c_layout = QVBoxLayout(self.container)
        self.c_layout.setContentsMargins(12, 8, 12, 10)
        self.c_layout.setSpacing(6)

        header = QHBoxLayout()
        self.title_label = QLabel(
            f"🐲 {self.cfg.settings.get('pet_name', 'Игнис')}")
        header.addWidget(self.title_label)

        self.status_label = QLabel("Слушает...")
        header.addWidget(self.status_label)
        header.addStretch()

        self.mic_btn = QPushButton("🎙️")
        self.mic_btn.setFixedSize(28, 24)
        self.mic_btn.clicked.connect(self.mic_toggled.emit)
        header.addWidget(self.mic_btn)

        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setToolTip("Открыть настройки с ползунками")
        self.settings_btn.setFixedSize(28, 24)
        self.settings_btn.setStyleSheet(
            "QPushButton { background: rgba(70, 70, 90, 220); color: white; border-radius: 5px; }")
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        header.addWidget(self.settings_btn)

        self.toggle_chat_btn = QPushButton("💬")
        self.toggle_chat_btn.setFixedSize(28, 24)
        self.toggle_chat_btn.setStyleSheet(
            "QPushButton { background: rgba(55, 60, 100, 220); color: white; border-radius: 5px; }")
        self.toggle_chat_btn.clicked.connect(self.toggle_chat_view)
        header.addWidget(self.toggle_chat_btn)

        self.exit_btn = QPushButton("❌")
        self.exit_btn.setFixedSize(28, 24)
        self.exit_btn.setStyleSheet(
            "QPushButton { background: rgba(130, 30, 30, 220); color: white; border-radius: 5px; }")
        self.exit_btn.clicked.connect(self.exit_requested.emit)
        header.addWidget(self.exit_btn)

        self.c_layout.addLayout(header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "background: transparent; color: #ECEFF1; border: none; font-size: 12px;")
        self.c_layout.addWidget(self.log_text)

        self.input_widget = QWidget()
        in_layout = QHBoxLayout(self.input_widget)
        in_layout.setContentsMargins(0, 0, 0, 0)
        in_layout.setSpacing(6)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Команда, вопрос или программа...")
        self.text_input.setStyleSheet(
            "QLineEdit { background: rgba(30, 30, 45, 230); color: #FFF; border: 1px solid #555; border-radius: 6px; padding: 4px 8px; }"
        )
        self.text_input.returnPressed.connect(self.send_text_message)
        in_layout.addWidget(self.text_input)

        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(30, 26)
        self.send_btn.setStyleSheet(
            "QPushButton { background: rgba(220, 120, 20, 220); color: white; border-radius: 6px; font-weight: bold; }")
        self.send_btn.clicked.connect(self.send_text_message)
        in_layout.addWidget(self.send_btn)

        self.c_layout.addWidget(self.input_widget)
        self.main_layout.addWidget(self.container)
        self.update_mic_status(False)
        self.reposition(True)

    def apply_dynamic_styles(self) -> None:
        s = self.cfg.settings
        cols = s.get("colors", {})
        opacity = s.get("hud_opacity", 240)
        bg_rgb = cols.get("hud_bg_rgb", "18, 18, 28")
        border = cols.get("hud_border", "#FF00FF")
        title_c = cols.get("hud_title", "#FF008C")
        status_c = cols.get("hud_status", "#00E5FF")

        self.container.setStyleSheet(
            f"background-color: rgba({bg_rgb}, {opacity}); border: 1.5px solid {border}; border-radius: 12px;"
        )
        self.title_label.setStyleSheet(
            f"color: {title_c}; font-weight: bold; font-size: 13px; border: none;")
        self.status_label.setStyleSheet(
            f"color: {status_c}; font-size: 11px; border: none;")

    def reposition(self, expanded: bool) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        hud_w, hud_h = 390, (250 if expanded else 56)
        self.resize(hud_w, hud_h)
        self.move(screen.width() - hud_w - 20, screen.height() - hud_h - 20)

    def toggle_chat_view(self) -> None:
        self.chat_visible = not self.chat_visible
        self.log_text.setVisible(self.chat_visible)
        self.input_widget.setVisible(self.chat_visible)
        self.reposition(self.chat_visible)

    def send_text_message(self) -> None:
        t = self.text_input.text().strip()
        if t:
            self.text_input.clear()
            self.text_command_sent.emit(t)

    def update_mic_status(self, is_muted: bool) -> None:
        if is_muted:
            self.mic_btn.setText("🔇")
            self.mic_btn.setStyleSheet(
                "QPushButton { background: rgba(110, 35, 35, 220); color: white; border-radius: 5px; }")
            self.status_label.setText("Микрофон ВЫКЛ")
        else:
            self.mic_btn.setText("🎙️")
            self.mic_btn.setStyleSheet(
                "QPushButton { background: rgba(35, 95, 45, 220); color: white; border-radius: 5px; }")
            self.status_label.setText("Слушает...")

    def append_user(self, text: str, timestamp: str = "") -> None:
        ts = timestamp or datetime.now().strftime("%H:%M")
        col = self.cfg.settings.get("colors", {}).get("hud_user", "#AFA04C")
        self.status_label.setText("Думает...")
        self.log_text.append(
            f"<span style='color:#888;font-size:10px;'>[{ts}]</span> <b style='color:{col};'>👤 {self.user_name}:</b> {text}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum())

    def append_dragon(self, text: str, timestamp: str = "") -> None:
        ts = timestamp or datetime.now().strftime("%H:%M")
        col = self.cfg.settings.get("colors", {}).get("hud_dragon", "#FF0000")
        name = self.cfg.settings.get("pet_name", "Игнис")
        self.status_label.setText("Готов")
        self.log_text.append(
            f"<span style='color:#888;font-size:10px;'>[{ts}]</span> <b style='color:{col};'>🐲 {name}:</b> {text}<br>")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum())


# --- ФОНОВЫЙ СЛУШАТЕЛЬ РЕЧИ ---
class VoiceListener(QObject):
    user_spoke_signal = pyqtSignal(str, str)
    dragon_reply_signal = pyqtSignal(str, str, str, str)
    status_signal = pyqtSignal(str)

    def __init__(self, brain: DragonBrain) -> None:
        super().__init__()
        self.brain = brain
        self.running = True
        self.is_muted = False

    def toggle_mute(self) -> bool:
        self.is_muted = not self.is_muted
        return self.is_muted

    def start_listening(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def process_input(self, text: str) -> None:
        t_in = datetime.now().strftime("%H:%M")
        self.user_spoke_signal.emit(text, t_in)
        self.status_signal.emit("Думаю... 🧠")
        action, payload, reply = self.brain.process(text)
        t_out = datetime.now().strftime("%H:%M")
        self.dragon_reply_signal.emit(action, payload, reply, t_out)

    def _loop(self) -> None:
        rec = sr.Recognizer()
        rec.dynamic_energy_threshold = True
        rec.pause_threshold = 1.0
        rec.phrase_threshold = 0.3
        rec.non_speaking_duration = 0.5

        while self.running:
            if self.is_muted:
                time.sleep(0.4)
                continue
            try:
                with sr.Microphone() as source:
                    rec.adjust_for_ambient_noise(source, duration=0.8)
                    while not self.is_muted and self.running:
                        try:
                            audio = rec.listen(
                                source, timeout=4, phrase_time_limit=15)
                            text = rec.recognize_google(
                                audio, language="ru-RU").strip()
                            if text:
                                self.process_input(text)
                        except (sr.WaitTimeoutError, sr.UnknownValueError):
                            continue
                        except Exception:
                            time.sleep(0.3)
            except Exception:
                time.sleep(2)


# --- ГЛАВНЫЙ КЛАСС ПИТОМЦА ---
class DragonPet(QWidget):
    def __init__(self, cfg: ConfigManager, scanner: AbsoluteAppScanner, brain: DragonBrain, hud: CornerChatHUD) -> None:
        super().__init__()
        self.cfg = cfg
        self.scanner = scanner
        self.brain = brain
        self.hud = hud
        self.settings_dlg: Optional[SettingsDialog] = None

        self.state = "FLYING"
        self.facing_right = True
        self.pos_x, self.pos_y = 300.0, 200.0
        self.vx = float(self.cfg.settings.get("cruise_speed", 2.6))
        self.vy = 0.5
        self.target_vx = self.vx
        self.target_vy = 0.5
        self.tick_count = 0

        self.target_pos: Optional[Tuple[int, int]] = None
        self.next_state: Optional[str] = None
        self.drag_hwnd: Optional[int] = None
        self.drag_win_w = 0
        self.drag_win_h = 0
        self.drag_steps = 0

        self.energy = 85
        self.hunger = 15
        self.is_manual_dragging = False

        self.init_ui()
        self.init_timers()
        self.init_voice()

        self.hud.append_dragon(
            f"Игнис в строю. В базе собрано {len(self.scanner.apps)} абсолютных путей к программам.")

    def init_ui(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.avatar = QLabel(self)
        self.movie = QMovie(self.cfg.settings.get("sprite_file", "dragon.gif"))
        if self.movie.isValid():
            self.avatar.setMovie(self.movie)
            self.movie.start()
        else:
            self.set_icon(self._icon("FLYING"))

        layout.addWidget(self.avatar, alignment=Qt.AlignCenter)
        sz = int(self.cfg.settings.get("dragon_size", 110))
        self.resize(sz, sz)
        self.move(int(self.pos_x), int(self.pos_y))

    def _icon(self, key: str) -> str:
        return self.cfg.settings.get("icons", {}).get(key, "🐲")

    def set_icon(self, icon_str: str, flip: bool = False) -> None:
        sz = int(self.cfg.settings.get("dragon_size", 110)) - 20
        pixmap = QPixmap(max(50, sz), max(50, sz))
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setFont(QFont("Segoe UI Emoji", int(sz * 0.48)))
        p.drawText(pixmap.rect(), Qt.AlignCenter, icon_str)
        p.end()
        if flip:
            pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        self.avatar.setPixmap(pixmap)

    def apply_live_settings(self) -> None:
        """Вызывается при движении ползунков в окне настроек."""
        sz = int(self.cfg.settings.get("dragon_size", 110))
        self.resize(sz, sz)
        if not self.movie.isValid():
            self.set_icon(self._icon(self.state), flip=not self.facing_right)
        self.hud.apply_dynamic_styles()

    def open_settings_dialog(self) -> None:
        if not self.settings_dlg:
            self.settings_dlg = SettingsDialog(
                self.cfg, self.scanner, self.apply_live_settings, self)
        self.settings_dlg.show()
        self.settings_dlg.raise_()

    def init_voice(self) -> None:
        self.listener = VoiceListener(self.brain)
        self.listener.user_spoke_signal.connect(self.hud.append_user)
        self.listener.dragon_reply_signal.connect(self.execute_action)
        self.listener.status_signal.connect(self.hud.status_label.setText)
        self.listener.start_listening()

        self.hud.mic_toggled.connect(self.toggle_mic)
        self.hud.settings_requested.connect(self.open_settings_dialog)
        self.hud.exit_requested.connect(self.clean_exit)
        self.hud.text_command_sent.connect(
            lambda t: threading.Thread(
                target=self.listener.process_input, args=(t,), daemon=True).start()
        )

    def toggle_mic(self) -> None:
        muted = self.listener.toggle_mute()
        self.hud.update_mic_status(muted)

    def clean_exit(self) -> None:
        self.listener.running = False
        os._exit(0)

    def init_timers(self) -> None:
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.physics_loop)
        self.tick_timer.start(25)

        self.behavior_timer = QTimer(self)
        self.behavior_timer.timeout.connect(self.smooth_direction_picker)
        self.behavior_timer.start(6000)

        self.ai_timer = QTimer(self)
        self.ai_timer.timeout.connect(self.autonomous_cycle)
        self.ai_timer.start(8000)

    def smooth_direction_picker(self) -> None:
        if self.state != "FLYING" or self.is_manual_dragging:
            return
        cruise = float(self.cfg.settings.get("cruise_speed", 2.6))
        dir_x = 1.0 if self.target_vx > 0 else -1.0
        if random.random() < 0.35:
            dir_x = -dir_x
        angle = random.uniform(-0.6, 0.6)
        self.target_vx = math.cos(angle) * cruise * dir_x
        self.target_vy = math.sin(angle) * 1.5

    def execute_action(self, action: str, payload: str, reply: str, timestamp: str) -> None:
        if reply:
            self.hud.append_dragon(reply, timestamp)

        if action == "EXIT":
            self.clean_exit()
        elif action == "CUSTOM_APP":
            self.set_icon(self._icon("APP"))
        elif action == "OPEN_URL":
            webbrowser.open(payload)
            self.set_icon(self._icon("APP"))
        elif action == "WEB_SEARCH" and payload:
            url = self.cfg.settings.get(
                "search_engine_url", "https://www.google.com/search?q=") + urllib.parse.quote(payload)
            webbrowser.open(url)
            self.set_icon(self._icon("SEARCH"))
        elif action == "MEDIA_PAUSE":
            send_key_event(VK_MEDIA_PLAY_PAUSE)
            self.set_icon(self._icon("MEDIA"))
        elif action == "VOL_UP":
            for _ in range(4):
                send_key_event(VK_VOLUME_UP)
        elif action == "VOL_DOWN":
            for _ in range(4):
                send_key_event(VK_VOLUME_DOWN)
        elif action == "VOL_MUTE":
            send_key_event(VK_VOLUME_MUTE)
        elif action == "LOCK_PC":
            user32.LockWorkStation()
        elif action == "SCREENSHOT":
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            fname = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            QApplication.primaryScreen().grabWindow(
                0).save(os.path.join(desktop, fname), "png")
            self.set_icon(self._icon("CAMERA"))
        elif action == "MINIMIZE_ALL":
            minimize_all_windows()
        elif action == "MINIMIZE_WINDOW":
            hwnd, _ = get_foreground_window()
            if hwnd:
                user32.ShowWindow(hwnd, 6)
        elif action == "MAXIMIZE_WINDOW":
            hwnd, _ = get_foreground_window()
            if hwnd:
                user32.ShowWindow(hwnd, 3)
        elif action == "CLOSE_WINDOW":
            hwnd, _ = get_foreground_window()
            if hwnd:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
        elif action == "DRAG_WINDOW":
            hwnd, rect = get_foreground_window()
            if hwnd and hwnd != int(self.winId()):
                self.drag_hwnd, self.drag_win_w, self.drag_win_h = hwnd, rect[2], rect[3]
                self.drag_steps = 70
                self.state = "DRAGGING_WIN"
                self.set_icon(self._icon("DRAGGING_WIN"))
        elif action == "FLY_UP":
            self.state = "FLYING"
            self.target_vy = -3.0
            self.set_icon(self._icon("FLYING"))
        elif action == "TO_MOUSE":
            self.state = "TO_MOUSE"
            self.set_icon(self._icon("TO_MOUSE"))
        elif action == "LAND_BOTTOM":
            self.start_landing("BOTTOM", "BOTTOM_WALK")
        elif action == "LAND_WINDOW":
            self.start_landing("WINDOW", "WINDOW_WALK")
        elif action == "SLEEP":
            self.start_landing("AUTO", "SLEEPING")
        elif action == "EAT":
            self.start_landing("AUTO", "EATING")

    def start_landing(self, target: str, next_state: str) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        floor_y = screen.height() - self.height() - 10
        _, win = get_foreground_window()
        if (target == "WINDOW" or target == "AUTO") and win:
            tx = max(win[0], min(int(self.pos_x),
                     win[0] + win[2] - self.width()))
            ty = max(10, win[1] - self.height() + 20)
        else:
            tx, ty = int(self.pos_x), floor_y
        self.target_pos = (tx, ty)
        self.next_state = next_state
        self.state = "LANDING"
        self.set_icon(self._icon("LANDING"))

    def autonomous_cycle(self) -> None:
        if self.is_manual_dragging or self.state in ("LANDING", "DRAGGING_WIN", "TO_MOUSE"):
            return
        self.hunger = min(100, self.hunger + 4)
        self.energy = max(0, self.energy - 3)
        if self.energy < 20 and self.state != "SLEEPING":
            self.start_landing("AUTO", "SLEEPING")
        elif self.state == "SLEEPING":
            self.energy += 35
            if self.energy >= 90:
                self.state = "FLYING"
                self.set_icon(self._icon("FLYING"))
        elif self.hunger > 75 and self.state != "EATING":
            self.start_landing("AUTO", "EATING")
        elif self.state == "EATING":
            self.hunger = 0
            self.energy += 25
            self.state = "FLYING"
            self.set_icon(self._icon("FLYING"))

    def physics_loop(self) -> None:
        if self.is_manual_dragging:
            return
        try:
            self.tick_count += 1
            screen = QApplication.primaryScreen().availableGeometry()
            s = self.cfg.settings
            cruise = float(s.get("cruise_speed", 2.6))
            dash_spd = float(s.get("mouse_dash_speed", 14.0))
            inertia = float(s.get("smooth_inertia", 0.05))
            wave_amp = float(s.get("wave_amplitude", 4.0))

            if self.state == "FLYING":
                margin = 80
                if self.pos_x < margin:
                    self.target_vx = abs(self.target_vx) if abs(
                        self.target_vx) > 0.5 else 1.5
                elif self.pos_x > screen.width() - self.width() - margin:
                    self.target_vx = - \
                        abs(self.target_vx) if abs(
                            self.target_vx) > 0.5 else -1.5

                if self.pos_y < margin:
                    self.target_vy = abs(self.target_vy) if abs(
                        self.target_vy) > 0.3 else 1.0
                elif self.pos_y > screen.height() - self.height() - margin - 30:
                    self.target_vy = - \
                        abs(self.target_vy) if abs(
                            self.target_vy) > 0.3 else -1.0

                self.target_vx = max(-cruise, min(cruise, self.target_vx))
                self.target_vy = max(-cruise, min(cruise, self.target_vy))

                self.vx += (self.target_vx - self.vx) * inertia
                self.vy += (self.target_vy - self.vy) * inertia

                self.pos_x = max(
                    0.0, min(float(screen.width() - self.width()), self.pos_x + self.vx))
                self.pos_y = max(
                    10.0, min(float(screen.height() - self.height() - 40), self.pos_y + self.vy))

                if self.vx > 0.3 and not self.facing_right:
                    self.facing_right = True
                    if not self.movie.isValid():
                        self.set_icon(self._icon("FLYING"), flip=False)
                elif self.vx < -0.3 and self.facing_right:
                    self.facing_right = False
                    if not self.movie.isValid():
                        self.set_icon(self._icon("FLYING"), flip=True)

                visual_y = self.pos_y + \
                    math.sin(self.tick_count * 0.06) * wave_amp
                self.move(int(self.pos_x), int(visual_y))

            elif self.state == "TO_MOUSE":
                c = QCursor.pos()
                dx, dy = (c.x() + 25) - self.pos_x, (c.y() - 35) - self.pos_y
                dist = math.hypot(dx, dy)
                if dist > 20:
                    step = min(dash_spd, max(3.0, dist * 0.16))
                    self.pos_x += (dx / dist) * step
                    self.pos_y += (dy / dist) * step
                    self.move(int(self.pos_x), int(self.pos_y))
                else:
                    self.state = "FLYING"
                    self.target_vx = cruise
                    self.set_icon(self._icon("FLYING"))

            elif self.state == "DRAGGING_WIN":
                if self.drag_steps > 0 and self.drag_hwnd and user32.IsWindow(self.drag_hwnd):
                    self.drag_steps -= 1
                    self.pos_x += 2.0
                    self.pos_y += 1.0
                    self.move(int(self.pos_x), int(self.pos_y))
                    user32.MoveWindow(self.drag_hwnd, int(self.pos_x), int(
                        self.pos_y) + 70, self.drag_win_w, self.drag_win_h, True)
                else:
                    self.state = "FLYING"
                    self.set_icon(self._icon("FLYING"))

            elif self.state == "LANDING" and self.target_pos:
                tx, ty = self.target_pos
                dx, dy = tx - self.pos_x, ty - self.pos_y
                if math.hypot(dx, dy) < 4:
                    self.pos_x, self.pos_y = float(tx), float(ty)
                    self.move(tx, ty)
                    self.state = self.next_state or "FLYING"
                    self.set_icon(self._icon(self.state))
                else:
                    self.pos_x += max(-cruise, min(cruise, dx * 0.08))
                    self.pos_y += max(-cruise, min(cruise, dy * 0.08))
                    self.move(int(self.pos_x), int(self.pos_y))

            elif self.state == "WINDOW_WALK":
                _, win = get_foreground_window()
                if win:
                    left, top, w, _ = win
                    self.pos_x += (1.5 if self.facing_right else -1.5)
                    if self.pos_x < left:
                        self.pos_x, self.facing_right = float(left), True
                    elif self.pos_x + self.width() > left + w:
                        self.pos_x, self.facing_right = float(
                            left + w - self.width()), False
                    self.pos_y = float(max(10, top - self.height() + 20))
                    self.move(int(self.pos_x), int(self.pos_y))
                else:
                    self.state = "FLYING"

            elif self.state == "BOTTOM_WALK":
                self.pos_x += (1.5 if self.facing_right else -1.5)
                if self.pos_x <= 0:
                    self.pos_x, self.facing_right = 0.0, True
                elif self.pos_x + self.width() >= screen.width():
                    self.pos_x, self.facing_right = float(
                        screen.width() - self.width()), False
                self.pos_y = float(screen.height() - self.height() - 10)
                self.move(int(self.pos_x), int(self.pos_y))
        except Exception as e:
            logging.warning(f"Ошибка физики: {e}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.is_manual_dragging = True
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self.is_manual_dragging:
            new_pos = event.globalPos() - self.drag_pos
            self.pos_x, self.pos_y = float(new_pos.x()), float(new_pos.y())
            self.move(new_pos)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.is_manual_dragging = False


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    app = QApplication(sys.argv)

    cfg_mgr = ConfigManager()
    default_user = cfg_mgr.settings.get("user_name", "София")

    name, ok = QInputDialog.getText(
        None, "Игнис", "Как обращаться?", text=default_user)
    user_name = name.strip() if (ok and name.strip()) else default_user
    cfg_mgr.settings["user_name"] = user_name
    cfg_mgr.save_settings()

    app_scanner = AbsoluteAppScanner()
    dragon_brain = DragonBrain(cfg_mgr, app_scanner)

    hud_win = CornerChatHUD(cfg_mgr, user_name)
    hud_win.show()

    pet_win = DragonPet(cfg_mgr, app_scanner, dragon_brain, hud_win)
    pet_win.show()

    sys.exit(app.exec_())
