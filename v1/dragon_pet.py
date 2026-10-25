import sys
import time
import json
import re
import math
import random
import threading
import subprocess
import webbrowser
import os
from datetime import datetime
import ctypes
from ctypes import wintypes
import requests
import speech_recognition as sr
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QPushButton,
    QHBoxLayout, QInputDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QMovie, QPixmap, QPainter, QFont, QCursor, QTransform

# --- АВТОМАТИЧЕСКИЙ ЗАПРОС ПРАВ АДМИНИСТРАТОРА (ELEVATION) ---


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


if not is_admin():
    params = " ".join([f'"{arg}"' for arg in sys.argv])
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1)
    sys.exit(0)

# --- НАСТРОЙКИ LM STUDIO ---
PET_NAME = "Игнис"
LM_STUDIO_URL = "http://26.15.91.117:1234/v1/chat/completions"
LOCAL_MODEL = "qwen/qwen3.5-9b"

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
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None, None
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 200 and h > 150:
            return hwnd, (rect.left, rect.top, w, h)
    return None, None


def send_key_event(vk_code):
    user32.keybd_event(vk_code, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk_code, 0, 2, 0)


VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_PLAY_PAUSE = 0xB3

# --- СТАЦИОНАРНЫЙ УГЛОВОЙ HUD ---


class CornerChatHUD(QWidget):
    mic_toggled = pyqtSignal()
    exit_requested = pyqtSignal()

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
            "background-color: rgba(18, 18, 28, 235); "
            "border: 1.5px solid #FF9900; border-radius: 12px;"
        )
        self.c_layout = QVBoxLayout(self.container)
        self.c_layout.setContentsMargins(12, 8, 12, 10)
        self.c_layout.setSpacing(6)

        header_layout = QHBoxLayout()
        self.title_label = QLabel(f"🐲 {PET_NAME}")
        self.title_label.setStyleSheet(
            "color: #FFB300; font-weight: bold; font-size: 13px; border: none;")
        header_layout.addWidget(self.title_label)

        self.status_label = QLabel("Слушает...")
        self.status_label.setStyleSheet(
            "color: #00E5FF; font-size: 11px; border: none; margin-right: 6px;")
        header_layout.addWidget(self.status_label)

        header_layout.addStretch()

        self.mic_btn = QPushButton("🎙️")
        self.mic_btn.setToolTip("Включить/выключить микрофон")
        self.mic_btn.setFixedSize(28, 24)
        self.mic_btn.setStyleSheet(
            "QPushButton { background: rgba(35, 95, 45, 220); color: white; border: none; border-radius: 5px; font-size: 12px; } "
            "QPushButton:hover { background: rgba(45, 125, 60, 240); }"
        )
        self.mic_btn.clicked.connect(self.mic_toggled.emit)
        header_layout.addWidget(self.mic_btn)

        self.toggle_chat_btn = QPushButton("💬")
        self.toggle_chat_btn.setToolTip("Свернуть / развернуть чат")
        self.toggle_chat_btn.setFixedSize(28, 24)
        self.toggle_chat_btn.setStyleSheet(
            "QPushButton { background: rgba(55, 60, 100, 220); color: white; border: none; border-radius: 5px; font-size: 12px; } "
            "QPushButton:hover { background: rgba(75, 80, 130, 240); }"
        )
        self.toggle_chat_btn.clicked.connect(self.toggle_chat_view)
        header_layout.addWidget(self.toggle_chat_btn)

        self.exit_btn = QPushButton("❌")
        self.exit_btn.setToolTip("Закрыть дракончика")
        self.exit_btn.setFixedSize(28, 24)
        self.exit_btn.setStyleSheet(
            "QPushButton { background: rgba(120, 30, 30, 220); color: white; border: none; border-radius: 5px; font-size: 11px; } "
            "QPushButton:hover { background: rgba(160, 40, 40, 240); }"
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

        self.main_layout.addWidget(self.container)
        self.setLayout(self.main_layout)

        self.reposition(expanded=True)

    def reposition(self, expanded):
        screen = QApplication.primaryScreen().availableGeometry()
        hud_w = 360
        hud_h = 220 if expanded else 56
        self.resize(hud_w, hud_h)
        self.move(screen.width() - hud_w - 20, screen.height() - hud_h - 20)

    def toggle_chat_view(self):
        self.chat_visible = not self.chat_visible
        self.log_text.setVisible(self.chat_visible)
        self.reposition(self.chat_visible)

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

    def append_user(self, text):
        self.status_label.setText("Думает...")
        self.log_text.append(
            f"<b style='color: #4CAF50;'>🎤 {self.user_name}:</b> {text}")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum())

    def append_dragon(self, text):
        self.status_label.setText("Готов")
        self.log_text.append(
            f"<b style='color: #FFB300;'>🐲 {PET_NAME}:</b> {text}<br>")
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum())

    def set_status(self, text):
        self.status_label.setText(text)

# --- БЫСТРЫЙ РОУТЕР КОМАНД ---


def fast_intent_router(text, user_name):
    clean = text.lower()
    for alias in ["игнис", "ignis", "игни", "игник", "дракончик", "дракон"]:
        clean = clean.replace(alias, "").strip()

    if any(w in clean for w in ["брось", "отпусти", "фу", "хватит", "отцепись", "не трогай"]):
        return "FLY_UP", "", "Понял, улетаю повыше! 🚀"

    if any(w in clean for w in ["пауза", "продолжи", "останови видео", "плей", "play"]):
        return "MEDIA_PAUSE", "", "Переключаю трек/видео! ⏯️"
    if any(w in clean for w in ["тише", "убавь звук"]):
        return "VOL_DOWN", "", "Сделал потише! 🔉"
    if any(w in clean for w in ["громче", "прибавь звук"]):
        return "VOL_UP", "", "Прибавил громкости! 🔊"
    if any(w in clean for w in ["выключи звук", "без звука", "мут"]):
        return "VOL_MUTE", "", "Заглушил звук! 🔇"

    if any(w in clean for w in ["скриншот", "снимок экрана"]):
        return "SCREENSHOT", "", "Делаю скриншот экрана! 📸"
    if any(w in clean for w in ["заблокируй комп", "заблокируй экран"]):
        return "LOCK_PC", "", "Блокирую компьютер! 🔒"

    if any(w in clean for w in ["где мышка", "поймай мышь", "к мышке"]):
        return "TO_MOUSE", "", "Лечу к мышке! 🐾"
    if any(w in clean for w in ["вверх", "сверх", "взлетай", "лети"]):
        return "FLY_UP", "", "Расправляю крылья! 🚀"
    if any(w in clean for w in ["на землю", "вниз", "на пол"]):
        return "LAND_BOTTOM", "", "Спускаюсь на землю! 🐾"
    if any(w in clean for w in ["на окно", "окно", "рамку", "сядь"]):
        return "LAND_WINDOW", "", "Приземляюсь на окно! 🪟"
    if any(w in clean for w in ["спать", "отдохни", "спи"]):
        return "SLEEP", "", "Зевает... Сворачиваюсь спать 💤"
    if any(w in clean for w in ["кушать", "поешь", "еда", "уголек"]):
        return "EAT", "", "Хрумкаю угольки! 🔥"

    if any(w in clean for w in ["перетащи", "сдвинь", "утащи"]):
        return "DRAG_WINDOW", "", "Хватаю окно и тащу! 💪"
    if any(w in clean for w in ["сверни", "спрячь"]):
        return "MINIMIZE_WINDOW", "", "Окно свернуто! 🕳️"
    if any(w in clean for w in ["разверни", "на весь экран"]):
        return "MAXIMIZE_WINDOW", "", "Развернул окно на максимум! 🖥️"
    if any(w in clean for w in ["закрой", "выключи окно"]):
        return "CLOSE_WINDOW", "", "Закрываю окно! ❌"

    if any(k in clean for k in ["открой", "запусти", "включи"]):
        if "календарь" in clean:
            return "OPEN_APP", "calendar", "Открываю календарь! 📅"
        if "калькулятор" in clean:
            return "OPEN_APP", "calc", "Калькулятор готов! 🔢"
        if "блокнот" in clean:
            return "OPEN_APP", "notepad", "Открываю блокнот! 📝"
        if "ютуб" in clean or "youtube" in clean:
            return "OPEN_APP", "youtube", "Включаю YouTube! 🎬"
        if any(b in clean for b in ["браузер", "интернет"]):
            return "OPEN_APP", "browser", "Открываю браузер! 🌐"
        if any(e in clean for e in ["проводник", "папку"]):
            return "OPEN_APP", "explorer", "Открываю файлы! 📁"
        if any(p in clean for p in ["paint", "рисовалку"]):
            return "OPEN_APP", "mspaint", "Открываю Paint! 🎨"

    return None, None, None

# --- НЕЙРОСЕТЬ ЧЕРЕЗ LM STUDIO ---


def analyze_intent_with_llm(user_text, user_name):
    system_prompt = (
        f"Ты — {PET_NAME}, умный и преданный дракончик на рабочем столе Windows.\n"
        f"Хозяин: {user_name}. Обращайся к нему по имени {user_name} или на 'ты'.\n"
        "ПИШИ ТОЛЬКО НА РУССКОМ! Запрещены любые китайские иероглифы и слова 'господин', 'хозяин'.\n"
        "Отвечай дружелюбно (2-3 предложения).\n\n"
        "ФОРМАТ СТРОГО JSON:\n"
        "{\"action\": \"CHAT\", \"payload\": \"\", \"reply\": \"текст ответа\"}"
    )

    payload = {
        "model": LOCAL_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "temperature": 0.5,
        "max_tokens": 200
    }

    try:
        response = requests.post(LM_STUDIO_URL, json=payload, timeout=8)
        if response.status_code == 200:
            res_data = response.json()
            raw = res_data.get("choices", [{}])[0].get(
                "message", {}).get("content", "{}")
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(match.group(0)) if match else json.loads(raw)
            reply = data.get("reply", "Ррр!")
            reply = re.sub(r'[\u4e00-\u9fff]+', '', reply).strip()
            for bad_word in ["господин", "господина", "хозяин", "хозяина", "повелитель"]:
                reply = reply.replace(bad_word, user_name)
            return (data.get("action", "CHAT"), data.get("payload", ""), reply)
    except Exception as e:
        print(f"⚠️ [LM Studio Error]: {e}")

    return "CHAT", "", f"Я слушаю тебя, {user_name}!"

# --- ГОЛОСОВОЙ МОДУЛЬ ---


class VoiceListener(QObject):
    user_spoke_signal = pyqtSignal(str)
    dragon_reply_signal = pyqtSignal(str, str, str)
    status_signal = pyqtSignal(str)

    def __init__(self, user_name):
        super().__init__()
        self.user_name = user_name
        self.running = True
        self.is_muted = False

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        return self.is_muted

    def start_listening(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 1.0
        recognizer.phrase_threshold = 0.3
        recognizer.non_speaking_duration = 0.5

        while self.running:
            if self.is_muted:
                time.sleep(0.4)
                continue

            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.8)
                    print(f"\n>>> {PET_NAME} слушает...")

                    while not self.is_muted and self.running:
                        try:
                            audio = recognizer.listen(
                                source, timeout=4, phrase_time_limit=15)
                            user_text = recognizer.recognize_google(
                                audio, language="ru-RU").strip()

                            print(f"🎤 [Вы сказали]: {user_text}")
                            self.user_spoke_signal.emit(user_text)

                            action, payload, reply = fast_intent_router(
                                user_text, self.user_name)
                            if not action:
                                self.status_signal.emit("Думаю... 🧠")
                                action, payload, reply = analyze_intent_with_llm(
                                    user_text, self.user_name)

                            print(f"🐲 [{PET_NAME}]: {reply}")
                            self.dragon_reply_signal.emit(
                                action, payload, reply)

                        except sr.WaitTimeoutError:
                            continue
                        except sr.UnknownValueError:
                            pass
                        except Exception as e:
                            time.sleep(0.3)
            except Exception as e:
                print(f"[Mic error]: {e}")
                time.sleep(2)

# --- ПИТОМЕЦ С БЕЗОПАСНОЙ И ПЛАВНОЙ ФИЗИКОЙ ---


class DragonPet(QWidget):
    def __init__(self, user_name, hud):
        super().__init__()
        self.user_name = user_name
        self.hud = hud

        self.state = "FLYING"
        self.facing_right = True

        # Координаты и скорость с жестким лимитом
        self.pos_x = 300.0
        self.pos_y = 200.0
        self.vx = 2.0
        self.vy = 0.5
        self.target_vx = 2.0
        self.target_vy = 0.5

        self.MAX_SPEED = 2.8      # Строгий предел скорости
        self.SMOOTHNESS = 0.05    # Мягкость разгона/торможения

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

        self.hud.append_dragon(
            f"Привет, {self.user_name}! Модель готова, полет стабильный! 🐉")

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.avatar = QLabel(self)
        self.movie = QMovie("dragon.gif")
        if self.movie.isValid():
            self.avatar.setMovie(self.movie)
            self.movie.start()
        else:
            self.set_icon("🐲")

        layout.addWidget(self.avatar, alignment=Qt.AlignCenter)
        self.setLayout(layout)
        self.resize(110, 110)
        self.move(int(self.pos_x), int(self.pos_y))

    def connect_hud_signals(self):
        self.hud.mic_toggled.connect(self.toggle_mic_from_hud)
        self.hud.exit_requested.connect(self.clean_exit)

    def toggle_mic_from_hud(self):
        self.last_interaction = time.time()
        is_muted = self.listener.toggle_mute()
        self.hud.update_mic_status(is_muted)
        if is_muted:
            self.hud.append_dragon("Слух временно выключен 🔇")
        else:
            self.hud.append_dragon("Снова внимательно слушаю! 🎙️")

    def clean_exit(self):
        self.hud.append_dragon("Пока-пока! Отключаюсь 👋")
        self.listener.running = False
        QTimer.singleShot(350, QApplication.instance().quit)

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

    # --- ПЛАВНЫЙ ВЫБОР ЦЕЛЕВОГО КУРСА ---
    def smooth_direction_picker(self):
        if self.state != "FLYING" or self.is_manual_dragging:
            return

        direction_x = 1.0 if self.target_vx > 0 else -1.0
        if random.random() < 0.35:
            direction_x = -direction_x

        angle = random.uniform(-0.6, 0.6)
        self.target_vx = math.cos(angle) * self.MAX_SPEED * direction_x
        self.target_vy = math.sin(angle) * 1.5

    def execute_action(self, action, payload, reply):
        self.last_interaction = time.time()
        if reply:
            self.hud.append_dragon(reply)

        if action == "MEDIA_PAUSE":
            send_key_event(VK_MEDIA_PLAY_PAUSE)
            self.set_icon("⏯️")
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
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            path = os.path.join(desktop, filename)
            screen = QApplication.primaryScreen()
            if screen:
                screen.grabWindow(0).save(path, "png")
                self.hud.append_dragon(
                    f"Снимок сохранен на Рабочий стол: {filename}")
            self.set_icon("📸")

        elif action == "OPEN_APP":
            p = payload.lower()
            if "youtube" in p:
                webbrowser.open("https://www.youtube.com")
            elif "browser" in p:
                webbrowser.open("https://www.google.com")
            elif "calendar" in p:
                os.system("start outlookcal:")
            elif "notepad" in p:
                subprocess.Popen("notepad", shell=True)
            elif "calc" in p:
                subprocess.Popen("calc", shell=True)
            elif "explorer" in p:
                subprocess.Popen("explorer", shell=True)
            elif "mspaint" in p:
                subprocess.Popen("mspaint", shell=True)
            self.set_icon("✨")

        elif action == "DRAG_WINDOW":
            hwnd, rect = get_foreground_window()
            if hwnd and hwnd != int(self.winId()):
                self.drag_hwnd = hwnd
                self.drag_win_w = rect[2]
                self.drag_win_h = rect[3]
                self.drag_steps = 70
                self.state = "DRAGGING_WIN"
                self.set_icon("💪")

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

        elif action == "FLY_UP":
            self.state = "FLYING"
            self.target_vy = -2.5
            self.set_icon("🐲")

        elif action == "TO_MOUSE":
            self.state = "TO_MOUSE"
            self.set_icon("👀")

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
        self.set_icon("🪂")

    def autonomous_cycle(self):
        if self.is_manual_dragging or self.state in ["LANDING", "DRAGGING_WIN"]:
            return

        self.hunger = min(100, self.hunger + 4)
        self.energy = max(0, self.energy - 3)

        if self.energy < 20 and self.state != "SLEEPING":
            self.hud.append_dragon("Устал летать... Сажусь поспать 💤")
            self.start_landing("AUTO", "SLEEPING")
            return

        if self.state == "SLEEPING":
            self.energy += 35
            if self.energy >= 90:
                self.hud.append_dragon(
                    f"Выспался, {self.user_name}! Снова в воздухе! ☀️")
                self.state = "FLYING"
                self.set_icon("🐲")
            return

        if self.hunger > 75 and self.state != "EATING":
            self.hud.append_dragon("Время перекусить угольком! 🔥")
            self.start_landing("AUTO", "EATING")
            return

        if self.state == "EATING":
            self.hunger = 0
            self.energy += 25
            self.hud.append_dragon("Сыт и готов к полетам!")
            self.state = "FLYING"
            self.set_icon("🐲")

    # --- БЕЗОПАСНАЯ И ПЛАВНАЯ ФИЗИКА ---
    def physics_loop(self):
        if self.is_manual_dragging:
            return

        try:
            self.tick_count += 1
            screen = QApplication.primaryScreen().availableGeometry()

            # 1. ПЛАВНЫЙ СВОБОДНЫЙ ПОЛЕТ
            if self.state == "FLYING":
                # Корректный разворот без накопления скорости
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

                # Ограничение целевой скорости
                self.target_vx = max(-self.MAX_SPEED,
                                     min(self.MAX_SPEED, self.target_vx))
                self.target_vy = max(-self.MAX_SPEED,
                                     min(self.MAX_SPEED, self.target_vy))

                # Мягкое сглаживание реальной скорости
                self.vx += (self.target_vx - self.vx) * self.SMOOTHNESS
                self.vy += (self.target_vy - self.vy) * self.SMOOTHNESS

                self.pos_x += self.vx
                self.pos_y += self.vy

                # Жесткий clamp координат (никогда не улетит за монитор)
                self.pos_x = max(
                    0.0, min(float(screen.width() - self.width()), self.pos_x))
                self.pos_y = max(
                    10.0, min(float(screen.height() - self.height() - 40), self.pos_y))

                # Разворот спрайта
                if self.vx > 0.3 and not self.facing_right:
                    self.facing_right = True
                    if not self.movie.isValid():
                        self.set_icon("🐲", flip=False)
                elif self.vx < -0.3 and self.facing_right:
                    self.facing_right = False
                    if not self.movie.isValid():
                        self.set_icon("🐲", flip=True)

                visual_y = self.pos_y + math.sin(self.tick_count * 0.06) * 4.0
                self.move(int(self.pos_x), int(visual_y))

            # 2. ДВИЖЕНИЕ К МЫШКЕ
            elif self.state == "TO_MOUSE":
                c = QCursor.pos()
                dx = (c.x() + 30) - self.pos_x
                dy = (c.y() - 30) - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5

                if dist > 25:
                    self.pos_x += max(-self.MAX_SPEED,
                                      min(self.MAX_SPEED, dx * 0.05))
                    self.pos_y += max(-self.MAX_SPEED,
                                      min(self.MAX_SPEED, dy * 0.05))
                    self.move(int(self.pos_x), int(self.pos_y))
                else:
                    self.state = "FLYING"
                    self.target_vx = 1.5
                    self.target_vy = 0.5
                    self.set_icon("🐲")

            # 3. ПЕРЕТАСКИВАНИЕ ОКНА
            elif self.state == "DRAGGING_WIN":
                if self.drag_steps > 0 and self.drag_hwnd:
                    self.drag_steps -= 1
                    self.pos_x += 2.0
                    self.pos_y += 1.0
                    self.move(int(self.pos_x), int(self.pos_y))
                    user32.MoveWindow(self.drag_hwnd, int(self.pos_x), int(
                        self.pos_y) + 70, self.drag_win_w, self.drag_win_h, True)
                else:
                    self.state = "FLYING"
                    self.set_icon("🐲")

            # 4. ПОСАДКА
            elif self.state == "LANDING":
                if not self.target_pos:
                    self.state = "FLYING"
                    return
                tx, ty = self.target_pos
                dx = tx - self.pos_x
                dy = ty - self.pos_y
                dist = (dx**2 + dy**2) ** 0.5
                if dist < 4:
                    self.pos_x, self.pos_y = float(tx), float(ty)
                    self.move(int(tx), int(ty))
                    self.state = self.next_state
                    icons = {"SLEEPING": "💤", "EATING": "🍖",
                             "WINDOW_WALK": "🦎", "BOTTOM_WALK": "🐾"}
                    self.set_icon(icons.get(self.state, "🐲"))
                else:
                    self.pos_x += max(-self.MAX_SPEED,
                                      min(self.MAX_SPEED, dx * 0.06))
                    self.pos_y += max(-self.MAX_SPEED,
                                      min(self.MAX_SPEED, dy * 0.06))
                    self.move(int(self.pos_x), int(self.pos_y))

            # 5. ХОЖДЕНИЕ ПО ОКНУ
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

            # 6. ХОЖДЕНИЕ ПО ЗЕМЛЕ
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
            print(f"[Physics Warning]: {e}")

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
        None, "Знакомство с Игнисом", "Как мне к тебе обращаться?", text="София")
    user_name = name.strip() if (ok and name.strip()) else "София"

    hud = CornerChatHUD(user_name)
    hud.show()

    pet = DragonPet(user_name, hud)
    pet.show()

    sys.exit(app.exec_())
