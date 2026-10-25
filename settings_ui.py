from typing import Callable
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider,
    QPushButton, QColorDialog, QGroupBox, QFormLayout, QMessageBox
)
from PyQt5.QtCore import Qt

from brain import ConfigManager
from app_scanner import AbsoluteAppScanner


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

    def _rescan_apps(self) -> None:
        count = self.scanner.rescan_all()
        self.rescan_btn.setText(f"🔄 Пересобрать пути к .exe (В базе: {count})")
        QMessageBox.information(
            self, "Готово", f"Собрано абсолютных путей к программам: {count}\nСохранено в apps_cache.json")
