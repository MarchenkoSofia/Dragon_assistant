from typing import Callable
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QColorDialog, QGroupBox, QFormLayout, QMessageBox
)
from PyQt5.QtCore import Qt

from PyQt5.QtGui import QColor

from brain import ConfigManager
from app_scanner import AbsoluteAppScanner
try:
    import create_dragon_gifs
except ImportError:          # без Pillow нет ни анимаций, ни смены расцветки
    create_dragon_gifs = None


class SettingsDialog(QDialog):
    """Интерактивное окно настроек с ползунками и живым применением."""

    def __init__(
        self,
        config_mgr: ConfigManager,
        scanner: AbsoluteAppScanner,
        on_update_callback: Callable[[], None],
        parent=None
    ) -> None:
        super().__init__(parent)
        self.cfg = config_mgr
        self.scanner = scanner
        self.on_update = on_update_callback
        self.setWindowTitle("⚙️ Настройки Игниса")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setFixedWidth(420)
        self.setStyleSheet("""
            QDialog { background-color: #161622; color: #EAEAEA; font-family: 'Segoe UI'; font-size: 12px; }
            QGroupBox { border: 1px solid #FF9900; border-radius: 8px; margin-top: 10px; padding-top: 12px; color: #FFB300; font-weight: bold; }
            QLabel { color: #DDDDDD; }
            QPushButton { background-color: #2A2A40; color: white; border: 1px solid #555; border-radius: 6px; padding: 5px 10px; }
            QPushButton:hover { background-color: #3A3A58; border-color: #FF9900; }
        """)
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        s = self.cfg.settings

        # --- ГРУППА 1: ФИЗИКА И ВИД (ПОЛЗУНКИ) ---
        phys_group = QGroupBox("Физика полета и габариты")
        phys_form = QFormLayout(phys_group)

        # 1. Скорость полета (1.0 - 10.0)
        self.speed_lbl = QLabel(f"{s.get('cruise_speed', 2.6):.1f}")
        self.speed_slider = self._make_slider(10, 100, int(
            s.get("cruise_speed", 2.6) * 10), self._on_slider_change)
        phys_form.addRow("Скорость парения:", self._wrap_slider(
            self.speed_slider, self.speed_lbl))

        # 2. Рывок к мышке (5.0 - 30.0)
        self.dash_lbl = QLabel(f"{s.get('mouse_dash_speed', 14.0):.0f}")
        self.dash_slider = self._make_slider(5, 30, int(
            s.get("mouse_dash_speed", 14.0)), self._on_slider_change)
        phys_form.addRow("Скорость рывка к мыши:", self._wrap_slider(
            self.dash_slider, self.dash_lbl))

        # 3. Плавность / Инерция (0.01 - 0.20)
        self.inertia_lbl = QLabel(f"{s.get('smooth_inertia', 0.05):.2f}")
        self.inertia_slider = self._make_slider(1, 20, int(
            s.get("smooth_inertia", 0.05) * 100), self._on_slider_change)
        phys_form.addRow("Маневренность (инерция):", self._wrap_slider(
            self.inertia_slider, self.inertia_lbl))

        # 4. Размер дракона (70 - 220 px)
        self.size_lbl = QLabel(f"{s.get('dragon_size', 110)} px")
        self.size_slider = self._make_slider(70, 220, int(
            s.get("dragon_size", 110)), self._on_slider_change)
        phys_form.addRow("Размер дракона:", self._wrap_slider(
            self.size_slider, self.size_lbl))

        # 5. Амплитуда взмахов (0 - 15 px)
        self.wave_lbl = QLabel(f"{s.get('wave_amplitude', 4.0):.0f} px")
        self.wave_slider = self._make_slider(0, 15, int(
            s.get("wave_amplitude", 4.0)), self._on_slider_change)
        phys_form.addRow("Амплитуда волн:", self._wrap_slider(
            self.wave_slider, self.wave_lbl))

        layout.addWidget(phys_group)

        # --- ГРУППА 2: НЕЙРОСЕТЬ И ИНТЕРФЕЙС ---
        ai_group = QGroupBox("Нейросеть и Окно чата (HUD)")
        ai_form = QFormLayout(ai_group)

        # 6. Прозрачность HUD (100 - 255)
        self.opacity_lbl = QLabel(f"{s.get('hud_opacity', 240)}")
        self.opacity_slider = self._make_slider(100, 255, int(
            s.get("hud_opacity", 240)), self._on_slider_change)
        ai_form.addRow("Непрозрачность HUD:", self._wrap_slider(
            self.opacity_slider, self.opacity_lbl))

        # 7. Глубина памяти (2 - 40 реплик)
        self.mem_lbl = QLabel(f"{s.get('max_history_len', 16)}")
        self.mem_slider = self._make_slider(2, 40, int(
            s.get("max_history_len", 16)), self._on_slider_change)
        ai_form.addRow("Память диалога (реплик):",
                       self._wrap_slider(self.mem_slider, self.mem_lbl))

        # 8. Температура ИИ (0.1 - 1.2)
        self.temp_lbl = QLabel(f"{s.get('temperature', 0.7):.1f}")
        self.temp_slider = self._make_slider(1, 12, int(
            s.get("temperature", 0.7) * 10), self._on_slider_change)
        ai_form.addRow("Креативность (Temp):", self._wrap_slider(
            self.temp_slider, self.temp_lbl))

        layout.addWidget(ai_group)

        # --- ГРУППА 3: ЦВЕТА И БАЗА ПУТЕЙ ---
        color_layout = QHBoxLayout()
        btn_border = QPushButton("🎨 Цвет рамки")
        btn_border.clicked.connect(lambda: self._pick_color("hud_border"))
        color_layout.addWidget(btn_border)

        btn_dragon_col = QPushButton("🎨 Цвет текста Игниса")
        btn_dragon_col.clicked.connect(lambda: self._pick_color("hud_dragon"))
        color_layout.addWidget(btn_dragon_col)
        layout.addLayout(color_layout)

        # --- РАСЦВЕТКА ДРАКОНА (анимации перерисовываются на лету) ---
        if create_dragon_gifs:
            dragon_group = QGroupBox("Расцветка дракона")
            dragon_form = QFormLayout(dragon_group)
            self.dragon_btns = {}
            keys = list(create_dragon_gifs.PALETTE_KEYS)
            for i in range(0, len(keys), 3):
                row = QHBoxLayout()
                for key in keys[i:i + 3]:
                    btn = QPushButton()
                    btn.setMinimumHeight(42)
                    self.dragon_btns[key] = btn
                    btn.clicked.connect(
                        lambda _, k=key, b=btn: self._pick_dragon_color(k, b))
                    self._paint_color_button(btn, key)
                    row.addWidget(btn)
                dragon_form.addRow(row)
            reset_btn = QPushButton("↺ Вернуть родную расцветку")
            reset_btn.clicked.connect(self._reset_dragon_colors)
            dragon_form.addRow(reset_btn)
            layout.addWidget(dragon_group)

        # Кнопка пересборки абсолютных путей
        self.rescan_btn = QPushButton(
            f"🔄 Пересобрать пути к .exe (В базе: {len(self.scanner.apps)})")
        self.rescan_btn.clicked.connect(self._rescan_apps)
        layout.addWidget(self.rescan_btn)

    @staticmethod
    def _make_slider(min_v: int, max_v: int, val: int, callback: Callable) -> QSlider:
        sl = QSlider(Qt.Horizontal)
        sl.setRange(min_v, max_v)
        sl.setValue(val)
        sl.valueChanged.connect(callback)
        return sl

    @staticmethod
    def _wrap_slider(slider: QSlider, label: QLabel) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addWidget(slider)
        label.setFixedWidth(48)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(label)
        return h

    def _on_slider_change(self) -> None:
        s = self.cfg.settings
        s["cruise_speed"] = self.speed_slider.value() / 10.0
        s["mouse_dash_speed"] = float(self.dash_slider.value())
        s["smooth_inertia"] = self.inertia_slider.value() / 100.0
        s["dragon_size"] = self.size_slider.value()
        s["wave_amplitude"] = float(self.wave_slider.value())
        s["hud_opacity"] = self.opacity_slider.value()
        s["max_history_len"] = self.mem_slider.value()
        s["temperature"] = self.temp_slider.value() / 10.0

        self.speed_lbl.setText(f"{s['cruise_speed']:.1f}")
        self.dash_lbl.setText(f"{s['mouse_dash_speed']:.0f}")
        self.inertia_lbl.setText(f"{s['smooth_inertia']:.2f}")
        self.size_lbl.setText(f"{s['dragon_size']} px")
        self.wave_lbl.setText(f"{s['wave_amplitude']:.0f} px")
        self.opacity_lbl.setText(f"{s['hud_opacity']}")
        self.mem_lbl.setText(f"{s['max_history_len']}")
        self.temp_lbl.setText(f"{s['temperature']:.1f}")

        self.cfg.save_settings()
        self.on_update()

    def _pick_color(self, key: str) -> None:
        col = QColorDialog.getColor()
        if col.isValid():
            self.cfg.settings.setdefault("colors", {})[key] = col.name()
            self.cfg.save_settings()
            self.on_update()

    # --- РАСЦВЕТКА ДРАКОНА ---
    def _dragon_palette(self) -> dict:
        return create_dragon_gifs.normalize_palette(
            self.cfg.settings.get("dragon_colors", {}))

    def _paint_color_button(self, btn: QPushButton, key: str) -> None:
        hexc = self._dragon_palette().get(
            key) or create_dragon_gifs.DEFAULT_PALETTE[key]
        r, g, b = create_dragon_gifs.hex_to_rgb(hexc)
        # на светлом образце текст должен быть темным, иначе его не прочитать
        text_col = "#101018" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"
        btn.setText(f"{create_dragon_gifs.PALETTE_NAMES[key]}\n{hexc}")
        btn.setStyleSheet(
            f"background-color: {hexc}; color: {text_col}; border: 1px solid #FF9900;"
            " border-radius: 6px; padding: 3px 4px; font-weight: bold;")

    def _pick_dragon_color(self, key: str, btn: QPushButton) -> None:
        current = self._dragon_palette().get(
            key) or create_dragon_gifs.DEFAULT_PALETTE[key]
        col = QColorDialog.getColor(
            QColor(current), self, create_dragon_gifs.PALETTE_NAMES[key])
        if not col.isValid():
            return
        self.cfg.settings.setdefault("dragon_colors", {})[key] = col.name()
        self.cfg.save_settings()
        self._paint_color_button(btn, key)
        self.on_update()

    def _reset_dragon_colors(self) -> None:
        self.cfg.settings["dragon_colors"] = dict(
            create_dragon_gifs.DEFAULT_PALETTE)
        self.cfg.save_settings()
        for key, btn in self.dragon_btns.items():
            self._paint_color_button(btn, key)
        self.on_update()

    def _rescan_apps(self) -> None:
        count = self.scanner.rescan_all()
        self.rescan_btn.setText(f"🔄 Пересобрать пути к .exe (В базе: {count})")
        QMessageBox.information(
            self, "Готово", f"Собрано абсолютных путей к программам: {count}\nСохранено в apps_cache.json")
