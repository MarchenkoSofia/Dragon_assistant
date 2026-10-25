import os
import re
import json
import logging
from datetime import datetime
from typing import Tuple, List, Dict, Any
import requests

from app_scanner import AbsoluteAppScanner

HISTORY_FILE = "chat_history.json"
COMMANDS_CONFIG_FILE = "commands_config.json"


class ConfigManager:
    """Управляет загрузкой и сохранением settings.json и commands_config.json."""

    def __init__(self, settings_path: str = "settings.json", commands_path: str = COMMANDS_CONFIG_FILE) -> None:
        self.settings_path = settings_path
        self.commands_path = commands_path
        self.settings: Dict[str, Any] = self._load_json(self.settings_path, {})
        self.commands_cfg: Dict[str, Any] = self._load_json(
            self.commands_path, {})

    @staticmethod
    def _load_json(path: str, default: Any) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Ошибка чтения {path}: {e}")
        return default

    def save_settings(self) -> None:
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка сохранения настроек: {e}")


class ChatMemory:
    """Хранит историю диалога с временными метками."""

    def __init__(self, config_mgr: ConfigManager) -> None:
        self.cfg = config_mgr
        self.history: List[Dict[str, str]] = self.load()

    @property
    def max_len(self) -> int:
        return int(self.cfg.settings.get("max_history_len", 16))

    def load(self) -> List[Dict[str, str]]:
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        clean = [
                            x for x in data if "Я на связи." not in x.get("content", "")]
                        return clean[-self.max_len:]
            except Exception:
                pass
        return []

    def save(self) -> None:
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.history[-self.max_len:],
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_message(self, role: str, text: str) -> None:
        self.history.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "role": role,
            "content": text
        })
        if len(self.history) > self.max_len:
            self.history = self.history[-self.max_len:]
        self.save()

    def build_messages(self, current_text: str) -> List[Dict[str, str]]:
        personality = self.cfg.settings.get("dragon_personality", "")
        msgs = [{"role": "system", "content": personality}]
        for item in self.history[-self.max_len:]:
            t = item.get("time", "")
            short_t = t.split(" ")[-1][:5] if " " in t else ""
            prefix = f"[{short_t}] " if short_t else ""
            msgs.append(
                {"role": item["role"], "content": f"{prefix}{item['content']}"})

        now_t = datetime.now().strftime("%H:%M")
        msgs.append({"role": "user", "content": f"[{now_t}] {current_text}"})
        return msgs


class DragonBrain:
    """Координатор инструментов и общения с локальной LLM."""

    def __init__(self, config_mgr: ConfigManager, scanner: AbsoluteAppScanner) -> None:
        self.cfg = config_mgr
        self.scanner = scanner
        self.memory = ChatMemory(config_mgr)

    def route_tool(self, text: str) -> Tuple[str, str, str]:
        """Проверяет текст по правилам из commands_config.json."""
        clean = text.lower().strip()
        cmd_cfg = self.cfg.commands_cfg

        for cw in cmd_cfg.get("control_words", []):
            clean = re.sub(rf"^\b{cw}\b[:,]?\s*", "", clean).strip()

        # 1. Проверка регулярных правил из файла конфигурации
        for rule in cmd_cfg.get("rules", []):
            pattern = rule.get("pattern", "")
            if pattern and re.search(pattern, clean):
                return rule["action"], "", rule.get("reply", "Выполнено.")

        # 2. Проверка триггеров запуска программ по абсолютным путям
        triggers = cmd_cfg.get("launch_triggers", [])
        if triggers:
            trig_regex = r"\b(?:" + \
                "|".join(map(re.escape, triggers)) + r")\s+(.+)"
            match = re.search(trig_regex, clean)
            if match:
                app_query = match.group(1).strip()
                for junk in cmd_cfg.get("junk_words", []):
                    app_query = app_query.replace(junk, "").strip()

                web_map = cmd_cfg.get("web_shortcuts", {})
                if app_query in web_map:
                    return "OPEN_URL", web_map[app_query], f"Открываю {app_query}."

                aliases = cmd_cfg.get("app_aliases", {})
                _, reply = self.scanner.launch_by_absolute_path(
                    app_query, aliases)
                return "CUSTOM_APP", app_query, reply

        # 3. Проверка поиска в интернете
        s_triggers = cmd_cfg.get("search_triggers", [])
        if s_triggers:
            s_regex = r"\b(?:" + "|".join(map(re.escape,
                                              s_triggers)) + r")\s+(.+)"
            s_match = re.search(s_regex, clean)
            if s_match:
                query = s_match.group(1).strip()
                if "погоду" in clean and "погода" not in query:
                    query = f"погода {query}"
                return "WEB_SEARCH", query, f"Ищу в сети: «{query}»."

        return "", "", ""

    def ask_llm(self, user_text: str) -> str:
        """Отправляет диалоговый запрос в LM Studio."""
        s = self.cfg.settings
        messages = self.memory.build_messages(user_text)

        payload = {
            "model": s.get("local_model", "qwen/qwen3.5-9b"),
            "messages": messages,
            "temperature": float(s.get("temperature", 0.7)),
            "max_tokens": 500
        }

        try:
            resp = requests.post(
                s.get("lm_studio_url", "http://127.0.0.1:1234/v1/chat/completions"),
                json=payload,
                timeout=int(s.get("request_timeout", 25))
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("choices", [{}])[0].get("message", {})
                raw = msg.get("content", "") or msg.get(
                    "reasoning_content", "") or ""
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
                raw = re.sub(r"[\u4e00-\u9fff]+", "", raw).strip()

                if not re.search(r"^\s*(привет|здравствуй|хай|салют|добрый)\b", user_text.lower()):
                    raw = re.sub(
                        r"^(Привет[!,.]?|Здравствуй[!,.]?|Хай[!,.]?)\s*", "", raw, flags=re.IGNORECASE).strip()

                return raw if raw else "Слушаю."
        except Exception as e:
            logging.error(f"Ошибка LM Studio: {e}")
            return "Не могу достучаться до сервера LM Studio."

        return "Слушаю."

    def process(self, text: str) -> Tuple[str, str, str]:
        """Главная точка входа: разделяет вызов инструментов и обычный диалог."""
        action, payload, reply = self.route_tool(text)
        if action:
            self.memory.add_message("user", text)
            self.memory.add_message("assistant", reply)
            return action, payload, reply

        chat_reply = self.ask_llm(text)
        self.memory.add_message("user", text)
        self.memory.add_message("assistant", chat_reply)
        return "CHAT", "", chat_reply
