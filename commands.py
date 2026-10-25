import os
import re
import json
import urllib.parse
import difflib
import subprocess
import webbrowser
import winreg
from datetime import datetime
import requests
import config

# --- МЕНЕДЖЕР ПАМЯТИ ДИАЛОГА С МЕТКАМИ ВРЕМЕНИ ---


class ChatMemory:
    def __init__(self, filename=config.HISTORY_FILE, max_len=config.MAX_HISTORY_LEN):
        self.filename = filename
        self.max_len = max_len
        self.history = self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        # Очищаем старые ошибки и заглушки "Я на связи."
                        clean_data = [
                            item for item in data
                            if "Я на связи." not in item.get("content", "")
                        ]
                        return clean_data[-self.max_len:]
            except Exception:
                pass
        return []

    def save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(self.history[-self.max_len:],
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_message(self, role, text):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history.append({
            "time": now_str,
            "role": role,
            "content": text
        })
        if len(self.history) > self.max_len:
            self.history = self.history[-self.max_len:]
        self.save()

    def get_messages_payload(self, system_prompt, current_user_text):
        msgs = [{"role": "system", "content": system_prompt}]
        for item in self.history:
            t = item.get("time", "")
            time_short = t.split(" ")[-1][:5] if " " in t else ""
            prefix = f"[{time_short}] " if time_short else ""
            msgs.append({
                "role": item["role"],
                "content": f"{prefix}{item['content']}"
            })

        now_time = datetime.now().strftime("%H:%M")
        msgs.append({
            "role": "user",
            "content": f"[{now_time}] {current_user_text}"
        })
        return msgs


chat_memory = ChatMemory()

# --- СКАНИРОВАНИЕ И ЗАПУСК ПРИЛОЖЕНИЙ WINDOWS ---


class WindowsAppLauncher:
    def __init__(self):
        self.apps = {}
        self.rescan()

    def rescan(self):
        self.apps.clear()
        start_dirs = [
            os.path.join(os.environ.get("APPDATA", ""),
                         r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                         r"Microsoft\Windows\Start Menu\Programs")
        ]

        for base_dir in start_dirs:
            if not os.path.exists(base_dir):
                continue
            for root, _, files in os.walk(base_dir):
                for f in files:
                    if f.lower().endswith((".lnk", ".url")):
                        self.apps[os.path.splitext(
                            f)[0].lower()] = os.path.join(root, f)

        for hkey in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            try:
                with winreg.OpenKey(hkey, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                exe_path = winreg.QueryValue(subkey, None)
                                if exe_path and os.path.exists(exe_path):
                                    self.apps[os.path.splitext(subkey_name)[
                                        0].lower()] = exe_path
                        except Exception:
                            continue
            except Exception:
                pass

    def launch(self, query):
        target = query.lower().strip()

        protocols = {
            "калькулятор": "calculator:", "calc": "calculator:",
            "календарь": "outlookcal:", "calendar": "outlookcal:",
            "блокнот": "notepad.exe", "notepad": "notepad.exe",
            "проводник": "explorer.exe", "explorer": "explorer.exe",
            "paint": "mspaint.exe", "рисовалка": "mspaint.exe",
            "диспетчер задач": "taskmgr.exe", "taskmgr": "taskmgr.exe",
            "настройки": "ms-settings:", "параметры": "ms-settings:"
        }
        for k, proto in protocols.items():
            if k in target:
                try:
                    os.startfile(proto)
                    return True, f"Запустил {k}."
                except Exception:
                    pass

        if target in self.apps:
            try:
                os.startfile(self.apps[target])
                return True, f"Открыл {target}."
            except Exception as e:
                return False, f"Не смог открыть {target}: {e}"

        for name, path in self.apps.items():
            if target in name or name in target:
                try:
                    os.startfile(path)
                    return True, f"Запустил {name}."
                except Exception:
                    pass

        matches = difflib.get_close_matches(
            target, self.apps.keys(), n=1, cutoff=0.55)
        if matches:
            try:
                os.startfile(self.apps[matches[0]])
                return True, f"Запустил {matches[0]}."
            except Exception:
                pass

        try:
            subprocess.Popen(target, shell=True)
            return True, f"Запустил {target}."
        except Exception:
            pass

        return False, f"Не нашел '{query}' на твоем компьютере."


app_launcher = WindowsAppLauncher()

# --- КОНТУР 1: ВЫЗОВ ИНСТРУМЕНТОВ (КОМАНДЫ) ---


def fast_tool_router(text, user_name):
    """
    Проверяет, содержит ли фраза четкую системную команду или обращение к инструментам.
    Если это действие — возвращает (action, payload, reply).
    Если это обычный разговор — возвращает (None, None, None).
    """
    clean = text.lower().strip()

    # Убираем префиксы обращения
    for w in config.CONTROL_WORDS:
        clean = re.sub(rf'^\b{w}\b[:,]?\s*', '', clean).strip()

    # 1. Выключение приложения
    if re.search(r'\b(выключись|закройся|выйди|отключись|выход|спать в гнездо)\b', clean):
        return "EXIT", "", "Понял, сворачиваю крылья и выхожу."

    # 2. Мышка и стоп
    if re.search(r'\b(где мышка|к мышке|поймай мышь|лови мышь|курсор)\b', clean):
        return "TO_MOUSE", "", "Мчу к мышке!"
    if re.search(r'\b(брось|отпусти|хватит|отцепись|не трогай|фу)\b', clean):
        return "FLY_UP", "", "Ладно-ладно, отпустил."

    # 3. Сворачивание / разворачивание / закрытие окон
    if re.search(r'\b(сверни все|сверни всё|все окна|рабочий стол)\b', clean):
        return "MINIMIZE_ALL", "", "Свернул всё. Чистый рабочий стол."
    if re.search(r'\b(сверни окно|сверни)\b', clean):
        return "MINIMIZE_WINDOW", "", "Свернул окно."
    if re.search(r'\b(разверни окно|разверни|на весь экран)\b', clean):
        return "MAXIMIZE_WINDOW", "", "Развернул во весь экран."
    if re.search(r'\b(закрой окно|закрой это|прикрой окно)\b', clean):
        return "CLOSE_WINDOW", "", "Закрыл окно."
    if re.search(r'\b(перетащи|сдвинь|подвинь|утащи окно)\b', clean):
        return "DRAG_WINDOW", "", "Хватаю окно и тащу."

    # 4. Посадка дракона
    if re.search(r'\b(сядь на окно|присядь на окно|на рамку)\b', clean):
        return "LAND_WINDOW", "", "Приземлился на рамку окна."
    if re.search(r'\b(на землю|на пол|в самый низ|вниз)\b', clean):
        return "LAND_BOTTOM", "", "Спустился на пол."
    if re.search(r'\b(взлетай|вверх|в небо|взлети)\b', clean):
        return "FLY_UP", "", "Взмываю вверх."

    # 5. Скриншот, блокировка, медиа
    if re.search(r'\b(скриншот|снимок экрана|заскринь)\b', clean):
        return "SCREENSHOT", "", "Скриншот готов."
    if re.search(r'\b(заблокируй комп|заблокируй экран|залочь)\b', clean):
        return "LOCK_PC", "", "Блокирую компьютер."
    if re.search(r'\b(пауза|продолжи|останови видео|плей)\b', clean):
        return "MEDIA_PAUSE", "", "Переключил медиа."
    if re.search(r'\b(тише|убавь звук|потише)\b', clean):
        return "VOL_DOWN", "", "Сделал тише."
    if re.search(r'\b(громче|прибавь звук|погромче)\b', clean):
        return "VOL_UP", "", "Прибавил громкость."
    if re.search(r'\b(выключи звук|без звука|мут)\b', clean):
        return "VOL_MUTE", "", "Заглушил звук."

    # 6. Запуск программ
    app_match = re.search(
        r'\b(?:открой|запусти|вруби|включи|зайди в)\s+(.+)', clean)
    if app_match:
        app_name = app_match.group(1).strip()
        for junk in ["пожалуйста", "быстро", "мне", "программу", "приложение"]:
            app_name = app_name.replace(junk, "").strip()

        if app_name in ["ютуб", "youtube"]:
            return "OPEN_URL", "https://www.youtube.com", "Открываю YouTube."
        if app_name in ["браузер", "интернет"]:
            return "OPEN_URL", "https://www.google.com", "Открываю браузер."

        _, launch_reply = app_launcher.launch(app_name)
        return "CUSTOM_APP", app_name, launch_reply

    # 7. Поиск в интернете
    search_match = re.search(
        r'\b(?:найди в интернете|найди в сети|поищи в интернете|загугли|погугли|поищи информацию про|поищи информацию о|посмотри погоду)\s+(.+)',
        clean
    )
    if search_match:
        query = search_match.group(1).strip()
        if "погоду" in clean and "погода" not in query:
            query = f"погода {query}"
        return "WEB_SEARCH", query, f"Ищу в сети: «{query}»."

    # Это не команда, отдаем в обычный чат
    return None, None, None

# --- КОНТУР 2: ОБЫЧНОЕ ОБЩЕНИЕ (ЧАТ БЕЗ JSON-ШАБЛОНОВ) ---


def chat_with_llm(user_text, user_name):
    """
    Чистый диалоговый режим: никакого JSON!
    Модель отвечает естественным текстом, с характером, памятью и метками времени.
    """
    messages = chat_memory.get_messages_payload(
        config.DRAGON_PERSONALITY, user_text)

    payload = {
        "model": config.LOCAL_MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 500
    }

    try:
        response = requests.post(config.LM_STUDIO_URL,
                                 json=payload, timeout=config.REQUEST_TIMEOUT)
        if response.status_code == 200:
            res_data = response.json()
            choice = res_data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            raw = msg.get("content", "") or msg.get(
                "reasoning_content", "") or ""

            # Убираем теги рассуждений, если они попали в текст
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)
            # Убираем китайские иероглифы
            raw = re.sub(r'[\u4e00-\u9fff]+', '', raw).strip()

            # Если собеседник не здоровался явно первым словом — срезаем шаблонные "Привет!"
            if not re.search(r'^\s*(привет|здравствуй|хай|салют|добрый)\b', user_text.lower()):
                raw = re.sub(
                    r'^(Привет[!,.]?|Здравствуй[!,.]?|Хай[!,.]?)\s*', '', raw, flags=re.IGNORECASE).strip()

            if not raw:
                raw = "Слушаю тебя."

            # Запоминаем в историю реплики с временем
            chat_memory.add_message("user", user_text)
            chat_memory.add_message("assistant", raw)

            return "CHAT", "", raw
    except Exception as e:
        print(f"⚠️ [LM Studio Chat Error]: {e}")
        return "CHAT", "", "Огонь притих: не могу достучаться до LM Studio. Проверь сервер."

    return "CHAT", "", "Слушаю тебя."

# --- ЕДИНАЯ ТОЧКА ОБРАБОТКИ ВВОДА ---


def process_user_input(text, user_name):
    """
    1. Проверяет команду в роутере инструментов.
    2. Если совпало — исполняет инструмент.
    3. Если нет — ведет нормальную человеческую беседу через LLM.
    """
    action, payload, reply = fast_tool_router(text, user_name)
    if action:
        # Инструменты тоже фиксируются в истории с временем
        chat_memory.add_message("user", text)
        chat_memory.add_message("assistant", reply)
        return action, payload, reply

    # Обычный диалог
    return chat_with_llm(text, user_name)
