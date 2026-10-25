import os
import sys
import math
import json
from PIL import Image, ImageDraw, ImageFont


def _say(msg: str) -> None:
    """Печатает в консоль и не падает при cp1251 (обычная консоль Windows) и при запуске без консоли."""
    try:
        if sys.stdout is not None:
            sys.stdout.reconfigure(encoding="utf-8")
            print(msg)
    except Exception:
        try:
            if sys.stdout is not None:
                print(msg.encode("ascii", "ignore").decode("ascii"))
        except Exception:
            pass

# Рисуем в повышенном разрешении (240x240) и уменьшаем до 120x120 для гладких краев
RAW_SIZE = 240
FINAL_SIZE = 120
GIF_DIR = "gifs"

# Палитра дракончика Игниса
C_BODY = (225, 48, 62)        # Рубиново-красная чешуя
C_DARK = (155, 22, 35)        # Темно-бордовые тени и спинные гребни
C_BELLY = (255, 205, 85)      # Золотистое брюшко
C_WING_MEM = (250, 130, 30)   # Оранжевые перепонки крыльев
C_EYE = (0, 245, 212)         # Бирюзовые светящиеся глаза
C_HORN = (45, 42, 58)         # Темные рожки и когти
C_FIRE = (255, 230, 40)       # Яркое пламя
C_EMBER = (255, 100, 0)       # Жар / уголь
C_CYAN = (0, 210, 255)        # Эффекты воздуха / пота / технологий
C_PURPLE = (180, 110, 255)    # Магия и сон

# --- Палитра, доступная из интерфейса -------------------------------------
# Тот же набор цветов, что константы выше, но в hex-виде: его показывает окно
# настроек и хранит settings.json (ключ "dragon_colors"). Ключ -> константа модуля.
PALETTE_KEYS = {
    "body": "C_BODY",
    "dark": "C_DARK",
    "belly": "C_BELLY",
    "wing": "C_WING_MEM",
    "eye": "C_EYE",
    "fire": "C_FIRE",
}
PALETTE_NAMES = {
    "body": "Чешуя",
    "dark": "Тени и гребни",
    "belly": "Брюшко",
    "wing": "Перепонки",
    "eye": "Глаза",
    "fire": "Пламя",
}
DEFAULT_PALETTE = {
    "body": "#e1303e",
    "dark": "#9b1623",
    "belly": "#ffcd55",
    "wing": "#fa821e",
    "eye": "#00f5d4",
    "fire": "#ffe628",
}

# Анимация для каждого состояния; main.py берет эту же карту
GIF_FILES = {
    "FLYING": f"{GIF_DIR}/flying.gif",
    "TO_MOUSE": f"{GIF_DIR}/to_mouse.gif",
    "SLEEPING": f"{GIF_DIR}/sleeping.gif",
    "EATING": f"{GIF_DIR}/eating.gif",
    "WINDOW_WALK": f"{GIF_DIR}/window_walk.gif",
    "BOTTOM_WALK": f"{GIF_DIR}/bottom_walk.gif",
    "DRAGGING_WIN": f"{GIF_DIR}/dragging_win.gif",
    "LANDING": f"{GIF_DIR}/landing.gif",
    "MEDIA": f"{GIF_DIR}/media.gif",
    "APP": f"{GIF_DIR}/app.gif",
    "CAMERA": f"{GIF_DIR}/camera.gif",
    "SEARCH": f"{GIF_DIR}/search.gif",
}
# Какая палитра последний раз вшита в gifs/
PALETTE_FILE = f"{GIF_DIR}/palette.json"


def hex_to_rgb(value: str):
    v = str(value).strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v):
        raise ValueError(f"не цвет в формате #RRGGBB: {value!r}")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*tuple(rgb)[:3])


def normalize_palette(colors) -> dict:
    """Оставляет только известные ключи и только в hex-виде; битое значение пропускаем."""
    out = {}
    for key in PALETTE_KEYS:
        value = (colors or {}).get(key)
        if not value:
            continue
        try:
            out[key] = rgb_to_hex(hex_to_rgb(value))
        except ValueError as e:
            _say(f"Пропускаю цвет {key}: {e}")
    return out


def apply_palette(colors=None) -> dict:
    """Меняет константы модуля; рисующие функции читают их в момент вызова."""
    full = dict(DEFAULT_PALETTE)
    full.update(normalize_palette(colors))
    for key, const in PALETTE_KEYS.items():
        globals()[const] = hex_to_rgb(full[key])
    return full


def saved_palette() -> dict:
    """Палитра, с которой последний раз рисовали gifs (пустой словарь = метки нет)."""
    try:
        with open(PALETTE_FILE, "r", encoding="utf-8") as f:
            return normalize_palette(json.load(f))
    except Exception:
        return {}


def needs_repaint(colors=None) -> bool:
    """Рисовать заново? Да, если гифок нет или вшита другая палитра. Нарисованные
    вручную гифки без метки палитры не трогаем."""
    if not os.path.isfile(GIF_FILES["FLYING"]):
        return True
    have = saved_palette()
    if not have:
        return False
    want = dict(DEFAULT_PALETTE)
    want.update(normalize_palette(colors))
    return {k: have.get(k) for k in want} != want


def save_clean_gif(frames, filepath, duration=95):
    """Сохраняет список RGBA-кадров в чистый прозрачный GIF без темных ореолов."""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(
        filepath) else ".", exist_ok=True)
    out_frames = []
    for raw_frame in frames:
        # Уменьшаем с антиалиасингом
        frame = raw_frame.resize(
            (FINAL_SIZE, FINAL_SIZE), Image.Resampling.LANCZOS)
        alpha = frame.split()[3]
        mask = Image.eval(alpha, lambda a: 255 if a < 110 else 0)
        p_img = frame.convert("RGB").quantize(
            colors=254, method=Image.Quantize.MEDIANCUT)
        p_img.paste(255, mask)
        out_frames.append(p_img)

    out_frames[0].save(
        filepath,
        save_all=True,
        append_images=out_frames[1:],
        duration=duration,
        loop=0,
        transparency=255,
        disposal=2
    )
    _say(f"✨ Сохранен GIF: {filepath}")


def draw_dragon_head(d, hx, hy, eye_mode="normal", mouth_open=False):
    """Рисует голову дракончика с рожками, мордочкой и выбранной эмоцией глаз."""
    # Рожки
    d.polygon([(hx - 6, hy - 18), (hx - 22, hy - 46),
              (hx + 8, hy - 22)], fill=C_HORN)
    d.polygon([(hx + 4, hy - 20), (hx - 6, hy - 42),
              (hx + 16, hy - 18)], fill=C_DARK)

    # Основа головы и мордочка
    d.ellipse([hx - 24, hy - 26, hx + 28, hy + 22],
              fill=C_BODY, outline=C_DARK, width=3)
    d.ellipse([hx + 6, hy - 12, hx + 44, hy + 18],
              fill=C_BODY, outline=C_DARK, width=3)

    # Ноздря
    d.ellipse([hx + 32, hy - 6, hx + 37, hy - 1], fill=C_DARK)

    # Рот
    if mouth_open:
        d.pieslice([hx + 12, hy + 2, hx + 40, hy + 20],
                   start=0, end=180, fill=C_DARK)
        d.polygon([(hx + 22, hy + 4), (hx + 25, hy + 10),
                  (hx + 28, hy + 4)], fill=(255, 255, 255))
    else:
        d.arc([hx + 14, hy + 2, hx + 36, hy + 14],
              start=10, end=160, fill=C_DARK, width=3)

    # Глаза
    ex, ey = hx + 10, hy - 8
    if eye_mode == "normal":
        d.ellipse([ex - 8, ey - 9, ex + 8, ey + 9],
                  fill=C_EYE, outline=C_DARK, width=2)
        d.ellipse([ex - 2, ey - 5, ex + 4, ey + 5], fill=(15, 15, 25))
        d.ellipse([ex - 4, ey - 6, ex, ey - 2], fill=(255, 255, 255))
    elif eye_mode == "happy":
        d.arc([ex - 8, ey - 6, ex + 8, ey + 8],
              start=190, end=350, fill=C_DARK, width=4)
    elif eye_mode == "sleep":
        d.arc([ex - 8, ey - 4, ex + 8, ey + 6],
              start=10, end=170, fill=C_DARK, width=4)
    elif eye_mode == "strain":
        d.line([(ex - 7, ey - 6), (ex + 5, ey),
               (ex - 7, ey + 6)], fill=C_FIRE, width=4)
    elif eye_mode == "fire":
        d.ellipse([ex - 9, ey - 9, ex + 9, ey + 9],
                  fill=C_FIRE, outline=C_EMBER, width=2)
        d.ellipse([ex - 2, ey - 4, ex + 4, ey + 4], fill=C_DARK)


def draw_wing(d, wx, wy, flap_angle):
    """Рисует перепончатое крыло дракона."""
    tip_y = wy - 45 + int(math.sin(flap_angle) * 38)
    mid_y = wy - 25 + int(math.sin(flap_angle) * 20)
    pts = [
        (wx, wy),
        (wx - 18, mid_y - 15),
        (wx + 16, tip_y),
        (wx - 48, tip_y + 18),
        (wx - 30, wy + 10)
    ]
    d.polygon(pts, fill=C_WING_MEM, outline=C_DARK)
    d.line([pts[0], pts[1], pts[2]], fill=C_DARK, width=5)


# 1. FLYING
def make_flying():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        phase = (i / 8.0) * math.pi * 2
        bob = int(math.sin(phase) * 10)
        bx, by = 110, 125 + bob

        # Хвост с огоньком
        tw = int(math.cos(phase) * 12)
        d.line([(bx - 35, by + 10), (bx - 75, by + 5 + tw),
               (bx - 95, by - 10 + tw)], fill=C_BODY, width=12)
        d.ellipse([bx - 108, by - 24 + tw, bx - 84, by + tw], fill=C_EMBER)
        d.ellipse([bx - 102, by - 18 + tw, bx - 90, by - 6 + tw], fill=C_FIRE)

        # Крыло заднее и тело
        draw_wing(d, bx - 8, by - 14, phase)
        d.ellipse([bx - 48, by - 28, bx + 36, by + 34],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 24, by - 10, bx + 26, by + 30], fill=C_BELLY)

        # Лапки
        d.ellipse([bx - 22, by + 24, bx - 4, by + 42], fill=C_DARK)
        d.ellipse([bx + 6, by + 24, bx + 24, by + 42], fill=C_DARK)

        draw_dragon_head(d, bx + 34, by - 24, eye_mode="normal")
        frames.append(img)
    return frames


# 2. TO_MOUSE (Сверхзвуковой рывок)
def make_to_mouse():
    frames = []
    for i in range(6):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        jet = (i % 2) * 14
        bx, by = 125, 120

        # Реактивная струя пламени позади
        d.polygon([(bx - 50, by - 14), (bx - 115 - jet, by + 4),
                  (bx - 50, by + 20)], fill=C_EMBER)
        d.polygon([(bx - 50, by - 6), (bx - 90 - jet, by + 4),
                  (bx - 50, by + 12)], fill=C_FIRE)

        # Линии скорости
        y_line = 50 + (i * 27) % 140
        d.line([(20, y_line), (75, y_line)], fill=C_CYAN, width=4)

        # Обтекаемое тело
        d.ellipse([bx - 55, by - 20, bx + 42, by + 24],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 25, by - 2, bx + 30, by + 20], fill=C_BELLY)
        draw_wing(d, bx - 10, by - 10, i * 1.1)
        draw_dragon_head(d, bx + 48, by - 10, eye_mode="fire", mouth_open=True)
        frames.append(img)
    return frames


# 3. SLEEPING (Сон калачиком)
def make_sleeping():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        phase = (i / 8.0) * math.pi * 2
        breath = int(math.sin(phase) * 5)
        bx, by = 115, 150

        d.ellipse([bx - 65 - breath, by - 30 - breath, bx + 55 +
                  breath, by + 40], fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 35, by - 8, bx + 30, by + 34], fill=C_BELLY)
        draw_dragon_head(d, bx + 28, by - 10 + breath // 2, eye_mode="sleep")

        # Сонные пузырьки и Zzz
        z_rise = (i * 8) % 60
        r = 6 + (i % 3) * 3
        d.ellipse([bx + 55 + z_rise // 2, by - 45 - z_rise, bx + 55 + z_rise //
                  2 + r * 2, by - 45 - z_rise + r * 2], outline=C_PURPLE, width=3)
        d.line([(bx + 40, by - 60 - z_rise), (bx + 56, by - 60 - z_rise), (bx + 40,
               by - 44 - z_rise), (bx + 56, by - 44 - z_rise)], fill=C_PURPLE, width=4)
        frames.append(img)
    return frames


# 4. EATING (Хрустит огненным углем)
def make_eating():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        chew = (i % 2 == 0)
        bx, by = 105, 140

        d.ellipse([bx - 45, by - 35, bx + 38, by + 42],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 20, by - 15, bx + 28, by + 38], fill=C_BELLY)
        draw_wing(d, bx - 15, by - 15, 0.3)

        # Светящийся уголек в лапках
        d.ellipse([bx + 30, by + 2, bx + 62, by + 32],
                  fill=C_EMBER, outline=C_DARK, width=3)
        d.ellipse([bx + 38, by + 10, bx + 54, by + 24], fill=C_FIRE)

        # Искры во все стороны
        for s in range(3):
            ang = i * 0.9 + s * 2.1
            sx = bx + 46 + int(math.cos(ang) * 28)
            sy = by + 15 + int(math.sin(ang) * 28)
            d.ellipse([sx - 4, sy - 4, sx + 4, sy + 4], fill=C_FIRE)

        draw_dragon_head(d, bx + 22, by - 34 + (4 if chew else 0),
                         eye_mode="happy", mouth_open=chew)
        frames.append(img)
    return frames


# 5 & 6. WALK (Прогулка по окну и полу)
def make_walk(is_window=False):
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        phase = (i / 8.0) * math.pi * 2
        step = int(math.sin(phase) * 18)
        bob = abs(int(math.cos(phase) * 6))
        bx, by = 110, 135 - bob

        # Опора под лапками для окна
        if is_window:
            d.line([(20, 190), (220, 190)], fill=(255, 165, 0, 180), width=4)

        # Хвост
        d.line([(bx - 35, by + 8), (bx - 80, by - 4 + step // 2)],
               fill=C_BODY, width=12)

        # Шагающие лапки
        d.line([(bx - 20, by + 22), (bx - 20 - step, by + 50)],
               fill=C_DARK, width=10)
        d.line([(bx + 15, by + 22), (bx + 15 + step, by + 50)],
               fill=C_DARK, width=10)

        d.ellipse([bx - 46, by - 26, bx + 36, by + 30],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 18, by - 8, bx + 26, by + 26], fill=C_BELLY)
        draw_wing(d, bx - 10, by - 12, 0.2 + math.sin(phase) * 0.2)
        draw_dragon_head(d, bx + 34, by - 22, eye_mode="normal")
        frames.append(img)
    return frames


# 7. DRAGGING_WIN (Тянет тяжелое окно)
def make_dragging():
    frames = []
    for i in range(6):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        shake = (i % 2) * 5
        bx, by = 105 + shake, 130

        # Упирающиеся лапы и тело под наклоном
        d.line([(bx - 30, by + 20), (bx - 52, by + 52)], fill=C_DARK, width=11)
        d.line([(bx + 5, by + 20), (bx - 12, by + 52)], fill=C_DARK, width=11)
        d.ellipse([bx - 50, by - 25, bx + 26, by + 32],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 25, by - 8, bx + 16, by + 28], fill=C_BELLY)

        # Вытянутые вперед лапы хватают рамку
        d.line([(bx + 18, by + 4), (bx + 72, by + 10)], fill=C_BODY, width=10)
        d.ellipse([bx + 66, by + 2, bx + 82, by + 18], fill=C_HORN)

        draw_wing(d, bx - 20, by - 18, 0.8 + (i % 2) * 0.4)
        draw_dragon_head(d, bx + 18, by - 26,
                         eye_mode="strain", mouth_open=True)

        # Капельки пота
        sy = (i * 12) % 35
        d.ellipse([bx - 8, by - 58 + sy, bx, by - 44 + sy], fill=C_CYAN)
        frames.append(img)
    return frames


# 8. LANDING (Парашютирование / плавная посадка)
def make_landing():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        sway = int(math.sin((i / 8.0) * math.pi * 2) * 8)
        bx, by = 115 + sway, 130

        # Потоки воздуха снизу вверх
        wy = 190 - (i * 18) % 120
        d.line([(45, wy), (45, wy + 28)], fill=C_CYAN, width=3)
        d.line([(195, wy + 20), (195, wy + 48)], fill=C_CYAN, width=3)

        # Большие раскрытые крылья куполом сверху
        d.polygon([(bx - 10, by - 15), (bx - 75, by - 75), (bx, by - 55),
                  (bx + 65, by - 75), (bx + 15, by - 15)], fill=C_WING_MEM, outline=C_DARK)

        d.ellipse([bx - 38, by - 24, bx + 32, by + 30],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 18, by - 6, bx + 22, by + 26], fill=C_BELLY)
        d.line([(bx - 15, by + 26), (bx - 22, by + 56)], fill=C_DARK, width=9)
        d.line([(bx + 12, by + 26), (bx + 18, by + 56)], fill=C_DARK, width=9)
        draw_dragon_head(d, bx + 24, by - 20, eye_mode="normal")
        frames.append(img)
    return frames


# 9. MEDIA (В наушниках с музыкальными нотами)
def make_media():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bop = abs(int(math.sin((i / 4.0) * math.pi) * 10))
        bx, by = 110, 130 + bop // 2

        d.ellipse([bx - 42, by - 25, bx + 34, by + 34],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 18, by - 8, bx + 24, by + 30], fill=C_BELLY)
        draw_wing(d, bx - 10, by - 12, math.sin(i * 0.8))

        hx, hy = bx + 28, by - 24 + bop
        draw_dragon_head(d, hx, hy, eye_mode="happy")

        # Наушники на голове
        d.arc([hx - 18, hy - 34, hx + 22, hy + 10],
              start=180, end=360, fill=C_CYAN, width=6)
        d.ellipse([hx - 10, hy - 14, hx + 8, hy + 8],
                  fill=C_HORN, outline=C_CYAN, width=3)

        # Всплывающие ноты
        ny = (i * 10) % 55
        d.ellipse([bx + 65, by - 35 - ny, bx + 79,
                  by - 23 - ny], fill=C_PURPLE)
        d.line([(bx + 77, by - 29 - ny), (bx + 77, by - 52 - ny),
               (bx + 90, by - 47 - ny)], fill=C_PURPLE, width=4)
        frames.append(img)
    return frames


# 10. APP (Кастует магию запуска приложений)
def make_app():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        phase = (i / 8.0) * math.pi * 2
        bx, by = 105, 130

        d.ellipse([bx - 42, by - 25, bx + 34, by + 34],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 18, by - 8, bx + 24, by + 30], fill=C_BELLY)
        draw_wing(d, bx - 12, by - 14, math.sin(phase) * 0.8)
        draw_dragon_head(d, bx + 28, by - 24, eye_mode="fire")

        # Магическая сфера и звезды
        ox, oy = bx + 72, by - 5
        r = 16 + int(math.sin(phase * 2) * 5)
        d.ellipse([ox - r, oy - r, ox + r, oy + r],
                  fill=C_PURPLE, outline=C_CYAN, width=3)
        d.ellipse([ox - r // 2, oy - r // 2, ox +
                  r // 2, oy + r // 2], fill=C_FIRE)
        frames.append(img)
    return frames


# 11. CAMERA (Скриншот со вспышкой)
def make_camera():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bx, by = 105, 132

        d.ellipse([bx - 42, by - 25, bx + 34, by + 34],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 18, by - 8, bx + 24, by + 30], fill=C_BELLY)
        draw_dragon_head(d, bx + 26, by - 24, eye_mode="normal")

        # Камера в лапках
        cx, cy = bx + 52, by - 6
        d.rectangle([cx - 16, cy - 12, cx + 18, cy + 14],
                    fill=C_HORN, outline=C_CYAN, width=2)
        d.ellipse([cx - 6, cy - 8, cx + 12, cy + 10], fill=C_CYAN)

        # Яркая вспышка на 3 и 4 кадрах
        if i in (3, 4):
            rad = 45 if i == 3 else 65
            d.polygon([
                (cx + 10, cy - rad), (cx + 22, cy - 15), (cx + 10 + rad, cy),
                (cx + 22, cy + 15), (cx + 10, cy + rad), (cx - 2, cy + 15),
                (cx + 10 - rad, cy), (cx - 2, cy - 15)
            ], fill=C_FIRE, outline=(255, 255, 255))
        frames.append(img)
    return frames


# 12. SEARCH (Смотрит через большую лупу)
def make_search():
    frames = []
    for i in range(8):
        img = Image.new("RGBA", (RAW_SIZE, RAW_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        scan = int(math.sin((i / 8.0) * math.pi * 2) * 12)
        bx, by = 105, 132

        d.ellipse([bx - 42, by - 25, bx + 34, by + 34],
                  fill=C_BODY, outline=C_DARK, width=3)
        d.ellipse([bx - 18, by - 8, bx + 24, by + 30], fill=C_BELLY)
        draw_wing(d, bx - 10, by - 12, 0.2)
        draw_dragon_head(d, bx + 26, by - 24, eye_mode="normal")

        # Большая лупа перед мордочкой
        lx, ly = bx + 62 + scan, by - 18
        d.line([(lx - 10, ly + 18), (lx - 24, ly + 42)], fill=C_EMBER, width=8)
        d.ellipse([lx - 24, ly - 24, lx + 24, ly + 24],
                  fill=(180, 245, 255, 130), outline=C_CYAN, width=6)
        frames.append(img)
    return frames


def generate_all_gifs(colors=None) -> None:
    """Генерирует полный комплект из 12 GIF-файлов; colors - палитра из настроек
    (None = палитра по умолчанию). Заодно помечает в gifs/palette.json, какая
    палитра вшита, чтобы при следующем запуске не перерисовывать зря."""
    applied = apply_palette(colors)
    os.makedirs(GIF_DIR, exist_ok=True)
    flying = make_flying()
    save_clean_gif(flying, "dragon.gif")
    save_clean_gif(flying, GIF_FILES["FLYING"])
    save_clean_gif(make_to_mouse(), GIF_FILES["TO_MOUSE"], duration=65)
    save_clean_gif(make_sleeping(), GIF_FILES["SLEEPING"], duration=130)
    save_clean_gif(make_eating(), GIF_FILES["EATING"], duration=95)
    save_clean_gif(make_walk(True), GIF_FILES["WINDOW_WALK"], duration=90)
    save_clean_gif(make_walk(False), GIF_FILES["BOTTOM_WALK"], duration=90)
    save_clean_gif(make_dragging(), GIF_FILES["DRAGGING_WIN"], duration=85)
    save_clean_gif(make_landing(), GIF_FILES["LANDING"], duration=95)
    save_clean_gif(make_media(), GIF_FILES["MEDIA"], duration=95)
    save_clean_gif(make_app(), GIF_FILES["APP"], duration=85)
    save_clean_gif(make_camera(), GIF_FILES["CAMERA"], duration=90)
    save_clean_gif(make_search(), GIF_FILES["SEARCH"], duration=100)
    with open(PALETTE_FILE, "w", encoding="utf-8") as f:
        json.dump(applied, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # Из консоли рисуем с той же расцветкой, что показывает интерфейс
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            start_palette = json.load(f).get("dragon_colors", {})
    except Exception:
        start_palette = {}
    generate_all_gifs(start_palette)
