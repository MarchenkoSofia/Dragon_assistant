import sys
import time
import math
import random
import threading
import webbrowser
import os
import urllib.parse
import logging
from datetime import datetime
import ctypes
from ctypes import wintypes
import speech_recognition as sr
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QHBoxLayout, QInputDialog, QTextEdit, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QMovie, QPixmap, QPainter, QFont, QCursor, QTransform

import config
import commands

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    filename=config.LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)


def log_msg(msg, level="info"):
    print(msg)
    if level == "error":
        logging.error(msg)
    elif level == "warning":
        logging.warning(msg)
    else:
        logging.info(msg)


def exception_hook(exctype, value, tb):
    logging.critical("КРИТИЧЕСКИЙ СБОЙ!", exc_info=(exctype, value, tb))
    sys.__excepthook__(exctype, value, tb)


sys.excepthook = exception_hook

# --- АВТОМАТИЧЕСКИЙ ЗАПРОС ПРАВ АДМИНИСТРАТОРА (ELEVATION) ---


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


if not is_admin():
    log_msg("Запрос прав Администратора...")
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


def get_foreground_window():
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindow(hwnd):
            return None, None
        rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 200 and h > 150:
                return hwnd, (rect.left, rect.top, w, h)
    except Exception as e:
        log_msg(f"Ошибка получения окна: {e}", "warning")
    return None, None


def send_key_event(vk_code):
    try:
        user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(vk_code, 0, 2, 0)
    except Exception as e:
        log_msg(f"Ошибка нажатия клавиши {vk_code}: {e}", "error")


def minimize_all_windows():
    VK_LWIN = 0x5B
    VK_D = 0x44
    user32.keybd_event(VK_LWIN, 0, 0, 0)
    user32.keybd_event(VK_D, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_D, 0, 2, 0)
    user32.keybd_event(VK_LWIN, 0, 2, 0)


VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_PLAY_PAUSE = 0xB3

# --- СТАЦИОНАРНЫЙ УГЛОВОЙ HUD С МЕТКАМИ ВРЕМЕНИ ---


class CornerChatHUD(QWidget):
    mic_toggled = pyqtSignal()
    exit_requested = pyqtSignal()
    text_command_sent = pyqtSignal(str)

    def __init__(self, user_name):
        super().__init__()
        self.user_name = user_name
        self.chat_visible = True
        self.init_ui()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(10, 10, 10, 10)

        self.container = QWidget()
        self.container.setStyleSheet(
            f"background-color: {config.HUD_BG_COLOR}; "
            f"border: 1.5px solid {config.HUD_BORDER_COLOR}; border-radius: 12px;"
        )
        self.c_layout = QVBoxLayout(self.container)
        self.c_layout.setContentsMargins(12, 8, 12, 10)
        self.c_layout.setSpacing(6)

        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"🐲 {config.PET_NAME}")
        self.title_label.setStyleSheet(
            f"color: {config.HUD_TITLE_COLOR}; font-weight: bold; font-size: 13px; border: none;"
        )
        header_layout.addWidget(self.title_label)

        self.status_label = QLabel("Слушает...")
        self.status_label.setStyleSheet(
            f"color: {config.HUD_STATUS_COLOR}; font-size: 11px; border: none; margin-right: 6px;"
        )
        header_layout.addWidget(self.status_label)

        header_layout.addStretch()

        self.mic_btn = QPushButton("🎙️")
        self.mic_btn.setFixedSize(28, 24)
        self.mic_btn.setStyleSheet(
            "QPushButton { background: rgba(35, 95, 45, 220); color: white; border: none; border-radius: 5px; font-size: 12px; } "
            "QPushButton:hover { background: rgba(45, 125, 60, 240); }"
        )
        self.mic_btn.clicked.connect(self.mic_toggled.emit)
        header_layout.addWidget(self.mic_btn)

        self.toggle_chat_btn = QPushButton("💬")
        self.toggle_chat_btn.setFixedSize(28, 24)
        self.toggle_chat_btn.setStyleSheet(
            "QPushButton { background: rgba(55, 60, 100, 220); color: white; border: none; border-radius: 5px; font-size: 12px; } "
            "QPushButton:hover { background: rgba(75, 80, 130, 240); }"
        )
        self.toggle_chat_btn.clicked.connect(self.toggle_chat_view)
        header_layout.addWidget(self.toggle_chat_btn)

        self.exit_btn = QPushButton("❌")
        self.exit_btn.setFixedSize(28, 24)
        self.exit_btn.setStyleSheet(
            "QPushButton { background: rgba(130, 30, 30, 220); color: white; border: none; border-radius: 5px; font-size: 11px; } "
            "QPushButton:hover { background: rgba(180, 40, 40, 240); }"
        )
        self.exit_btn.clicked.connect(self.exit_requested.emit)
        header_layout.addWidget(self.exit_btn)

        self.c_layout.addLayout(header_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "background: transparent; color: #ECEFF1; border: none; "
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; line-height: 1.4;"
        )
        self.c_layout.addWidget(self.log_text)

        self.input_widget = QWidget()
        self.input_widget.setStyleSheet(
            "border: none; background: transparent;")
        input_layout = QHBoxLayout(self.input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Команда, вопрос или приложение...")
        self.text_input.setStyleSheet(
            "QLineEdit { background: rgba(30, 30, 45, 230); color: #FFF; "
            "border: 1px solid #555; border-radius: 6px; padding: 4px 8px; font-size: 11px; } "
            "QLineEdit:focus { border: 1px solid #FF9900; }"
        )
        self.text_input.returnPressed.connect(self.send_text_message)
        input_layout.addWidget(self.text_input)

        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(30, 26)
        self.send_btn.setStyleSheet(
            "QPushButton { background: rgba(220, 120, 20, 220); color: white; border: none; border-radius: 6px; font-size: 13px; font-weight: bold; } "
            "QPushButton:hover { background: rgba(255, 140, 30, 240); }"
        )
        self.send_btn.clicked.connect(self.send_text_message)
        input_layout.addWidget(self.send_btn)

        self.c_layout.addWidget(self.input_widget)
        self.main_layout.addWidget(self.container)
        self.setLayout(self.main_layout)

        self.reposition(expanded=True)

    def reposition(self, expanded):
        screen = QApplication.primaryScreen().availableGeometry()
        hud_w = 380
        hud_h = 245 if expanded else 56
        self.resize(hud_w, hud_h)
        self.move(screen.width() - hud_w - 20, screen.height() - hud_h - 20)

    def toggle_chat_view(self):
        self.chat_visible = not self.chat_visible
        self.log_text.setVisible(self.chat_visible)
        self.input_widget.setVisible(self.chat_visible)
        self.reposition(self.chat_visible)

    def send_text_message(self):
        text = self.text_input.text().strip()
        if text:
            self.text_input.clear()
            self.text_command_sent.emit(text)

    def update_mic_status(self, is_muted):
        if is_muted:
            self.mic_btn.setText("🔇")
            self.mic_btn.setStyleSheet(
                "QPushButton { background: rgba(110, 35, 35, 220); border-radius: 5px; }")
            self.set_status("Микрофон ВЫКЛ")
        else:
            self.mic_btn.setText("🎙️")
            self.mic_btn.setStyleSheet(
                "QPushButton { background: rgba(35, 95, 45, 220); border-radius: 5px; }")
            self.set_status("Слушает...")

    def append_user(self, text, timestamp=None):
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M")
        self.status_label.setText("Думает...")
        self.log_text.append(
            f"<span style='color: #888; font-size: 10px;'>[{timestamp}]</span> "
            f"<b style='color: {config.HUD_USER_COLOR};'>👤 {self.user_name}:</b> {text}"
        )
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum())

    def append_dragon(self, text, timestamp=None):
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M")
        self.status_label.setText("Готов")
        self.log_text.append(
            f"<span style='color: #888; font-size: 10px;'>[{timestamp}]</span> "
            f"<b style='color: {config.HUD_DRAGON_COLOR};'>🐲 {config.PET_NAME}:</b> {text}<br>"
        )
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum())

    def set_status(self, text):
        self.status_label.setText(text)

# --- ГОЛОСОВОЙ МОДУЛЬ ---


class VoiceListener(QObject):
    user_spoke_signal = pyqtSignal(str, str)
    dragon_reply_signal = pyqtSignal(str, str, str, str)
    status_signal = pyqtSignal(str)

    def __init__(self, user_name):
        super().__init__()
        self.user_name = user_name
        self.running = True
        self.is_muted = False

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        log_msg(f"Микрофон: is_muted={self.is_muted}")
        return self.is_muted

    def start_listening(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def process_command_sync(self, text):
        now_time = datetime.now().strftime("%H:%M")
        log_msg(f"Ввод пользователя: '{text}'")
        self.user_spoke_signal.emit(text, now_time)

        self.status_signal.emit("Думаю... 🧠")
        # Раздельная обработка: инструмент или диалог
        action, payload, reply = commands.process_user_input(
            text, self.user_name)

        log_msg(f"Результат: action={action}, reply={reply}")
        reply_time = datetime.now().strftime("%H:%M")
        self.dragon_reply_signal.emit(action, payload, reply, reply_time)

    def _loop(self):
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 1.0
        recognizer.phrase_threshold = 0.3
        recognizer.non_speaking_duration = 0.5

        log_msg("Поток микрофона активен")
        while self.running:
            if self.is_muted:
                time.sleep(0.4)
                continue

            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.8)

                    while not self.is_muted and self.running:
                        try:
                            audio = recognizer.listen(
                                source, timeout=4, phrase_time_limit=15)
                            user_text = recognizer.recognize_google(
                                audio, language="ru-RU").strip()
                            log_msg(f"Услышано: '{user_text}'")
                            self.process_command_sync(user_text)

                        except sr.WaitTimeoutError:
                            continue
                        except sr.UnknownValueError:
                            pass
                        except Exception as e:
                            log_msg(f"Ошибка распознавания: {e}", "warning")
                            time.sleep(0.3)
            except Exception as e:
                log_msg(f"Ошибка микрофона: {e}", "error")
                time.sleep(2)

# --- ПИТОМЕЦ ---


class DragonPet(QWidget):
    def __init__(self, user_name, hud):
        super().__init__()
        self.user_name = user_name
        self.hud = hud

        self.state = "FLYING"
        self.facing_right = True

        self.pos_x = 300.0
        self.pos_y = 200.0
        self.vx = config.CRUISE_SPEED
        self.vy = 0.5
        self.target_vx = config.CRUISE_SPEED
        self.target_vy = 0.5

        self.tick_count = 0
        self.target_pos = None
        self.next_state = None

        self.drag_hwnd = None
        self.drag_win_w = 0
        self.drag_win_h = 0
        self.drag_steps = 0

        self.energy = 85
        self.hunger = 15
        self.is_manual_dragging = False
        self.last_interaction = time.time()

        self.init_ui()
        self.init_timers()
        self.init_voice()
        self.connect_hud_signals()

        self.hud.append_dragon("Игнис в строю. Что на уме?")

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.avatar = QLabel(self)
        self.movie = QMovie(config.SPRITE_FILE)
        if self.movie.isValid():
            self.avatar.setMovie(self.movie)
            self.movie.start()
        else:
            self.set_icon(config.ICONS.get("FLYING", "🐲"))

        layout.addWidget(self.avatar, alignment=Qt.AlignCenter)
        self.setLayout(layout)
        self.resize(config.DRAGON_SIZE[0], config.DRAGON_SIZE[1])
        self.move(int(self.pos_x), int(self.pos_y))

    def connect_hud_signals(self):
        self.hud.mic_toggled.connect(self.toggle_mic_from_hud)
        self.hud.exit_requested.connect(self.clean_exit)
        self.hud.text_command_sent.connect(self.handle_typed_command)

    def handle_typed_command(self, text):
        threading.Thread(target=self.listener.process_command_sync,
                         args=(text,), daemon=True).start()

    def toggle_mic_from_hud(self):
        self.last_interaction = time.time()
        is_muted = self.listener.toggle_mute()
        self.hud.update_mic_status(is_muted)
        if is_muted:
            self.hud.append_dragon("Уши прикрыл, не подслушиваю.")
        else:
            self.hud.append_dragon("Слушаю.")

    def clean_exit(self):
        log_msg("Выключение приложения")
        self.listener.running = False
        self.hud.close()
        self.close()
        os._exit(0)

    def set_icon(self, icon, flip=False):
        pixmap = QPixmap(90, 90)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setFont(QFont("Segoe UI Emoji", 44))
        p.drawText(pixmap.rect(), Qt.AlignCenter, icon)
        p.end()

        if flip:
            pixmap = pixmap.transformed(QTransform().scale(-1, 1))

        self.avatar.setPixmap(pixmap)

    def init_voice(self):
        self.listener = VoiceListener(self.user_name)
        self.listener.user_spoke_signal.connect(self.hud.append_user)
        self.listener.dragon_reply_signal.connect(self.execute_action)
        self.listener.status_signal.connect(self.hud.set_status)
        self.listener.start_listening()

    def init_timers(self):
        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.physics_loop)
        self.tick_timer.start(25)

        self.behavior_timer = QTimer(self)
        self.behavior_timer.timeout.connect(self.smooth_direction_picker)
        self.behavior_timer.start(6000)

        self.ai_timer = QTimer(self)
        self.ai_timer.timeout.connect(self.autonomous_cycle)
        self.ai_timer.start(8000)

    def smooth_direction_picker(self):
        if self.state != "FLYING" or self.is_manual_dragging:
            return

        direction_x = 1.0 if self.target_vx > 0 else -1.0
        if random.random() < 0.35:
            direction_x = -direction_x

        angle = random.uniform(-0.6, 0.6)
        self.target_vx = math.cos(angle) * config.CRUISE_SPEED * direction_x
        self.target_vy = math.sin(angle) * 1.5

    def execute_action(self, action, payload, reply, timestamp):
        self.last_interaction = time.time()
        if reply:
            self.hud.append_dragon(reply, timestamp)

        # Выключение
        if action == "EXIT":
            self.clean_exit()

        elif action == "CUSTOM_APP":
            self.set_icon(config.ICONS.get("APP", "✨"))

        elif action == "OPEN_URL":
            webbrowser.open(payload)
            self.set_icon(config.ICONS.get("APP", "✨"))

        elif action == "WEB_SEARCH":
            if payload:
                url = config.SEARCH_ENGINE_URL + urllib.parse.quote(payload)
                webbrowser.open(url)
                self.set_icon(config.ICONS.get("SEARCH", "🔍"))

        elif action == "MEDIA_PAUSE":
            send_key_event(VK_MEDIA_PLAY_PAUSE)
            self.set_icon(config.ICONS.get("MEDIA", "⏯️"))
        elif action == "VOL_UP":
            for _ in range(4):
                send_key_event(VK_VOLUME_UP)
            self.set_icon("🔊")
        elif action == "VOL_DOWN":
            for _ in range(4):
                send_key_event(VK_VOLUME_DOWN)
            self.set_icon("🔉")
        elif action == "VOL_MUTE":
            send_key_event(VK_VOLUME_MUTE)
            self.set_icon("🔇")
        elif action == "LOCK_PC":
            user32.LockWorkStation()
        elif action == "SCREENSHOT":
            try:
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                path = os.path.join(desktop, filename)
                screen = QApplication.primaryScreen()
                if screen:
                    screen.grabWindow(0).save(path, "png")
                    self.hud.append_dragon(
                        f"Скриншот готов: {filename}", timestamp)
                self.set_icon(config.ICONS.get("CAMERA", "📸"))
            except Exception as e:
                log_msg(f"Ошибка скриншота: {e}", "error")

        elif action == "MINIMIZE_ALL":
            minimize_all_windows()
            self.set_icon(config.ICONS.get("FLYING", "🐲"))

        elif action == "MINIMIZE_WINDOW":
            hwnd, _ = get_foreground_window()
            if hwnd and user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, 6)

        elif action == "MAXIMIZE_WINDOW":
            hwnd, _ = get_foreground_window()
            if hwnd and user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, 3)

        elif action == "CLOSE_WINDOW":
            hwnd, _ = get_foreground_window()
            if hwnd and user32.IsWindow(hwnd):
                user32.PostMessageW(hwnd, 0x0010, 0, 0)

        elif action == "DRAG_WINDOW":
            hwnd, rect = get_foreground_window()
            if hwnd and hwnd != int(self.winId()):
                self.drag_hwnd = hwnd
                self.drag_win_w = rect[2]
                self.drag_win_h = rect[3]
                self.drag_steps = 70
                self.state = "DRAGGING_WIN"
                self.set_icon(config.ICONS.get("DRAGGING_WIN", "💪"))
            else:
                self.hud.append_dragon("Окно не выбрано.", timestamp)

        elif action == "FLY_UP":
            self.state = "FLYING"
            self.target_vy = -3.0
            self.set_icon(config.ICONS.get("FLYING", "🐲"))

        elif action == "TO_MOUSE":
            self.state = "TO_MOUSE"
            self.set_icon(config.ICONS.get("TO_MOUSE", "👀"))

        elif action == "LAND_BOTTOM":
            self.start_landing("BOTTOM", "BOTTOM_WALK")
        elif action == "LAND_WINDOW":
            self.start_landing("WINDOW", "WINDOW_WALK")
        elif action == "SLEEP":
            self.start_landing("AUTO", "SLEEPING")
        elif action == "EAT":
            self.start_landing("AUTO", "EATING")

    def start_landing(self, target="AUTO", next_state="SLEEPING"):
        screen = QApplication.primaryScreen().availableGeometry()
        floor_y = screen.height() - self.height() - 10
        _, win = get_foreground_window()

        if target == "WINDOW" and win:
            target_x = max(win[0], min(int(self.pos_x),
                           win[0] + win[2] - self.width()))
            target_y = max(10, win[1] - self.height() + 20)
        elif target == "BOTTOM":
            target_x = int(self.pos_x)
            target_y = floor_y
        else:
            if win:
                target_x = max(win[0], min(int(self.pos_x),
                               win[0] + win[2] - self.width()))
                target_y = max(10, win[1] - self.height() + 20)
            else:
                target_x = int(self.pos_x)
                target_y = floor_y

        self.target_pos = (target_x, target_y)
        self.next_state = next_state
        self.state = "LANDING"
        self.set_icon(config.ICONS.get("LANDING", "🪂"))

    def autonomous_cycle(self):
        if self.is_manual_dragging or self.state in ["LANDING", "DRAGGING_WIN", "TO_MOUSE"]:
            return

        self.hunger = min(100, self.hunger + 4)
        self.energy = max(0, self.energy - 3)

        if self.energy < 20 and self.state != "SLEEPING":
            self.hud.append_dragon("Устал. Ушел спать 💤")
            self.start_landing("AUTO", "SLEEPING")
            return

        if self.state == "SLEEPING":
            self.energy += 35
            if self.energy >= 90:
                self.hud.append_dragon("Проснулся. Взлетаю.")
                self.state = "FLYING"
                self.set_icon(config.ICONS.get("FLYING", "🐲"))
            return

        if self.hunger > 75 and self.state != "EATING":
            self.hud.append_dragon("Голод не тетка. Ищу уголь 🔥")
            self.start_landing("AUTO", "EATING")
            return

        if self.state == "EATING":
            self.hunger = 0
            self.energy += 25
            self.hud.append_dragon("Подкрепился.")
            self.state = "FLYING"
            self.set_icon(config.ICONS.get("FLYING", "🐲"))

    def physics_loop(self):
        if self.is_manual_dragging:
            return

        try:
            self.tick_count += 1
            screen = QApplication.primaryScreen().availableGeometry()

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

                self.target_vx = max(-config.CRUISE_SPEED,
                                     min(config.CRUISE_SPEED, self.target_vx))
                self.target_vy = max(-config.CRUISE_SPEED,
                                     min(config.CRUISE_SPEED, self.target_vy))

                self.vx += (self.target_vx - self.vx) * config.SMOOTH_INERTIA
                self.vy += (self.target_vy - self.vy) * config.SMOOTH_INERTIA

                self.pos_x += self.vx
                self.pos_y += self.vy

                self.pos_x = max(
                    0.0, min(float(screen.width() - self.width()), self.pos_x))
                self.pos_y = max(
                    10.0, min(float(screen.height() - self.height() - 40), self.pos_y))

                if self.vx > 0.3 and not self.facing_right:
                    self.facing_right = True
                    if not self.movie.isValid():
                        self.set_icon(config.ICONS.get(
                            "FLYING", "🐲"), flip=False)
                elif self.vx < -0.3 and self.facing_right:
                    self.facing_right = False
                    if not self.movie.isValid():
                        self.set_icon(config.ICONS.get(
                            "FLYING", "🐲"), flip=True)

                visual_y = self.pos_y + math.sin(self.tick_count * 0.06) * 4.0
                self.move(int(self.pos_x), int(visual_y))

            elif self.state == "TO_MOUSE":
                c = QCursor.pos()
                target_x = c.x() + 25
                target_y = c.y() - 35
                dx = target_x - self.pos_x
                dy = target_y - self.pos_y
                dist = math.hypot(dx, dy)

                if dist > 20:
                    step_mag = min(config.MOUSE_DASH_SPEED,
                                   max(3.0, dist * 0.16))
                    self.pos_x += (dx / dist) * step_mag
                    self.pos_y += (dy / dist) * step_mag

                    if dx > 5 and not self.facing_right:
                        self.facing_right = True
                        if not self.movie.isValid():
                            self.set_icon(config.ICONS.get(
                                "TO_MOUSE", "👀"), flip=False)
                    elif dx < -5 and self.facing_right:
                        self.facing_right = False
                        if not self.movie.isValid():
                            self.set_icon(config.ICONS.get(
                                "TO_MOUSE", "👀"), flip=True)

                    self.move(int(self.pos_x), int(self.pos_y))
                else:
                    self.state = "FLYING"
                    self.target_vx = config.CRUISE_SPEED
                    self.target_vy = 0.5
                    self.set_icon(config.ICONS.get("FLYING", "🐲"))

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
                    self.set_icon(config.ICONS.get("FLYING", "🐲"))

            elif self.state == "LANDING":
                if not self.target_pos:
                    self.state = "FLYING"
                    return
                tx, ty = self.target_pos
                dx = tx - self.pos_x
                dy = ty - self.pos_y
                dist = math.hypot(dx, dy)
                if dist < 4:
                    self.pos_x, self.pos_y = float(tx), float(ty)
                    self.move(int(tx), int(ty))
                    self.state = self.next_state
                    self.set_icon(config.ICONS.get(self.state, "🐲"))
                else:
                    self.pos_x += max(-config.CRUISE_SPEED,
                                      min(config.CRUISE_SPEED, dx * 0.08))
                    self.pos_y += max(-config.CRUISE_SPEED,
                                      min(config.CRUISE_SPEED, dy * 0.08))
                    self.move(int(self.pos_x), int(self.pos_y))

            elif self.state == "WINDOW_WALK":
                _, win = get_foreground_window()
                if win:
                    left, top, w, _ = win
                    target_y = max(10, top - self.height() + 20)
                    self.pos_x += (1.5 if self.facing_right else -1.5)
                    if self.pos_x < left:
                        self.pos_x = left
                        self.facing_right = True
                    elif self.pos_x + self.width() > left + w:
                        self.pos_x = left + w - self.width()
                        self.facing_right = False
                    self.pos_y = float(target_y)
                    self.move(int(self.pos_x), int(self.pos_y))
                else:
                    self.state = "FLYING"

            elif self.state == "BOTTOM_WALK":
                floor_y = screen.height() - self.height() - 10
                self.pos_x += (1.5 if self.facing_right else -1.5)
                if self.pos_x <= 0:
                    self.pos_x = 0.0
                    self.facing_right = True
                elif self.pos_x + self.width() >= screen.width():
                    self.pos_x = float(screen.width() - self.width())
                    self.facing_right = False
                self.pos_y = float(floor_y)
                self.move(int(self.pos_x), int(self.pos_y))

        except Exception as e:
            log_msg(f"Сбой физики: {e}", "warning")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_interaction = time.time()
            self.is_manual_dragging = True
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.is_manual_dragging:
            new_pos = event.globalPos() - self.drag_pos
            self.pos_x = float(new_pos.x())
            self.pos_y = float(new_pos.y())
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_manual_dragging = False


if __name__ == "__main__":
    app = QApplication(sys.argv)

    name, ok = QInputDialog.getText(
        None, "Игнис", "Как обращаться?",
        text=config.USER_NAME_DEFAULT
    )
    user_name = name.strip() if (ok and name.strip()) else config.USER_NAME_DEFAULT

    log_msg(f"Пользователь: {user_name}")

    hud = CornerChatHUD(user_name)
    hud.show()

    pet = DragonPet(user_name, hud)
    pet.show()

    sys.exit(app.exec_())
