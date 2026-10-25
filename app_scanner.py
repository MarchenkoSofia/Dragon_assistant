import os
import json
import winreg
import difflib
import subprocess
import logging
from typing import Dict, Tuple, Optional

try:
    import win32com.client
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False

CACHE_FILE = "apps_cache.json"
IGNORED_EXES = ("unins", "setup", "update", "crash",
                "helper", "installer", " redist")


class AbsoluteAppScanner:
    """Собирает абсолютные пути ко всем .exe приложениям ПК и запускает их."""

    def __init__(self) -> None:
        self.apps: Dict[str, str] = {}
        self.load_or_scan()

    def load_or_scan(self) -> int:
        """Загружает кэш абсолютных путей или запускает полное сканирование."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and data:
                        self.apps = data
                        return len(self.apps)
            except Exception as e:
                logging.warning(f"Ошибка чтения кэша приложений: {e}")
        return self.rescan_all()

    def _add_exe(self, alias: str, exe_path: str) -> None:
        if not exe_path:
            return
        exe_path = exe_path.strip('"').strip()
        if not exe_path.lower().endswith(".exe"):
            return
        abs_path = os.path.abspath(os.path.expandvars(exe_path))
        if not os.path.isfile(abs_path):
            return
        base_lower = os.path.basename(abs_path).lower()
        if any(bad in base_lower for bad in IGNORED_EXES):
            return

        clean_alias = alias.lower().strip()
        if clean_alias:
            self.apps[clean_alias] = abs_path
        exe_name = os.path.splitext(base_lower)[0]
        self.apps[exe_name] = abs_path

    def rescan_all(self) -> int:
        """Полное сканирование ПК со сбором абсолютных путей к .exe."""
        self.apps.clear()

        # 1. Стандартные системные утилиты Windows
        win_dir = os.environ.get("WINDIR", r"C:\Windows")
        sys32 = os.path.join(win_dir, "System32")
        for tool in ("notepad.exe", "calc.exe", "mspaint.exe", "taskmgr.exe", "cmd.exe", "snippingtool.exe"):
            self._add_exe(os.path.splitext(tool)[0], os.path.join(sys32, tool))
        self._add_exe("explorer", os.path.join(win_dir, "explorer.exe"))

        # 2. Реестр Windows: App Paths
        for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hkey, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths") as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name) as subkey:
                                val = winreg.QueryValue(subkey, None)
                                if val:
                                    self._add_exe(
                                        os.path.splitext(sub_name)[0], val)
                        except OSError:
                            continue
            except OSError:
                pass

        # 3. Реестр Windows: Установленные программы (Uninstall)
        uninstall_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        ]
        for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for u_path in uninstall_paths:
                try:
                    with winreg.OpenKey(hkey, u_path) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                sub_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, sub_name) as subkey:
                                    disp_name, _ = winreg.QueryValueEx(
                                        subkey, "DisplayName")
                                    icon_path, _ = winreg.QueryValueEx(
                                        subkey, "DisplayIcon")
                                    exe_candidate = icon_path.split(",")[
                                        0].strip('"')
                                    self._add_exe(disp_name, exe_candidate)
                            except OSError:
                                continue
                except OSError:
                    pass

        # 4. Разрешение ярлыков (.lnk) из меню Пуск и Рабочего стола в абсолютные пути .exe
        shell = win32com.client.Dispatch(
            "WScript.Shell") if HAS_WIN32COM else None
        shortcut_dirs = [
            os.path.join(os.environ.get("APPDATA", ""),
                         r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                         r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.path.expanduser("~"), "Desktop")
        ]
        for s_dir in shortcut_dirs:
            if not os.path.exists(s_dir):
                continue
            for root, _, files in os.walk(s_dir):
                for file in files:
                    if file.lower().endswith(".lnk") and shell:
                        lnk_full = os.path.join(root, file)
                        try:
                            shortcut = shell.CreateShortCut(lnk_full)
                            target_exe = shortcut.Targetpath
                            self._add_exe(os.path.splitext(
                                file)[0], target_exe)
                        except Exception:
                            continue

        # 5. Прямой обход популярных директорий программ (глубина до 2 уровней)
        scan_roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
            os.environ.get("APPDATA", "")
        ]
        for root_dir in scan_roots:
            if not root_dir or not os.path.exists(root_dir):
                continue
            try:
                for entry in os.scandir(root_dir):
                    if entry.is_dir():
                        try:
                            for sub in os.scandir(entry.path):
                                if sub.is_file() and sub.name.lower().endswith(".exe"):
                                    self._add_exe(entry.name, sub.path)
                                elif sub.is_dir() and sub.name.lower().startswith("app-"):
                                    # Для Discord / Slack / Electron-приложений
                                    for sub2 in os.scandir(sub.path):
                                        if sub2.is_file() and sub2.name.lower().endswith(".exe"):
                                            self._add_exe(
                                                entry.name, sub2.path)
                        except PermissionError:
                            continue
            except PermissionError:
                continue

        # Сохранение собранной базы абсолютных путей
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.apps, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Не удалось сохранить кэш путей: {e}")

        logging.info(
            f"Сканирование завершено. Собрано абсолютных путей: {len(self.apps)}")
        return len(self.apps)

    def find_absolute_path(self, query: str, aliases: Dict[str, str]) -> Optional[str]:
        """Ищет абсолютный путь к .exe по названию или синониму."""
        target = query.lower().strip()
        mapped = aliases.get(target, target)

        if mapped in self.apps:
            return self.apps[mapped]
        if target in self.apps:
            return self.apps[target]

        for name, path in self.apps.items():
            if mapped in name or target in name:
                return path

        matches = difflib.get_close_matches(
            mapped, self.apps.keys(), n=1, cutoff=0.55)
        if matches:
            return self.apps[matches[0]]

        return None

    def launch_by_absolute_path(self, query: str, aliases: Dict[str, str]) -> Tuple[bool, str]:
        """Запускает программу строго по найденному абсолютному пути."""
        abs_path = self.find_absolute_path(query, aliases)
        if not abs_path or not os.path.isfile(abs_path):
            return False, f"Не нашел исполняемый файл для «{query}» в базе путей."

        try:
            work_dir = os.path.dirname(abs_path)
            subprocess.Popen([abs_path], cwd=work_dir, shell=False)
            exe_title = os.path.basename(abs_path)
            logging.info(f"Запущен по абсолютному пути: {abs_path}")
            return True, f"Запустил {exe_title} ({abs_path})"
        except OSError:
            try:
                os.startfile(abs_path)
                return True, f"Открыл {os.path.basename(abs_path)}."
            except Exception as e:
                logging.error(f"Ошибка запуска {abs_path}: {e}")
                return False, f"Ошибка при запуске: {e}"
