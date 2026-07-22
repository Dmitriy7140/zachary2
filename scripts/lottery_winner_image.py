#!/usr/bin/env python3
"""Создать картинку с ником победителя на шарах лотереи.

Скрипт не использует генеративные модели: он копирует вертикальный фрагмент
исходного PNG для недостающих шаров и рисует символы через Pillow.
"""

import argparse
import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "static" / "lottery_winner_template.png"

TEMPLATE_SIZE = (1280, 720)
BASE_SLOT_COUNT = 8
MAX_NICKNAME_LENGTH = 64

# Полноразмерный вертикальный фрагмент с маленьким шаром «42».
REPEAT_SLICE_LEFT = 695
REPEAT_SLICE_RIGHT = 772
REPEAT_SLICE_WIDTH = REPEAT_SLICE_RIGHT - REPEAT_SLICE_LEFT

# Большой шар «44» и семь маленьких шаров нижнего табло.
BASE_SLOT_CENTERS = (
    (338, 613),
    (503, 635),
    (580, 635),
    (657, 635),
    (733, 635),
    (810, 635),
    (887, 635),
    (964, 635),
)

BALL_FILL = (255, 254, 255)
LETTER_FILL = (35, 22, 73)
LETTER_STROKE = (255, 254, 255)

FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
    Path("/Library/Fonts/YS Display-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
)


def _validate_nickname(nickname: str) -> None:
    if not nickname:
        raise ValueError("Ник победителя не может быть пустым")
    if len(nickname) > MAX_NICKNAME_LENGTH:
        raise ValueError(
            f"Ник длиннее допустимых {MAX_NICKNAME_LENGTH} символов"
        )
    if any(ord(symbol) < 32 or symbol == "\x7f" for symbol in nickname):
        raise ValueError("Ник не должен содержать управляющие символы")


def resolve_font_path(font_path: Optional[Path] = None) -> Path:
    """Найти жирный шрифт с поддержкой латиницы и кириллицы."""
    if font_path is not None:
        candidate = Path(font_path).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"Файл шрифта не найден: {candidate}")
        return candidate

    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate

    variants = "\n".join(f"  - {candidate}" for candidate in FONT_CANDIDATES)
    raise FileNotFoundError(
        "Не найден жирный шрифт с кириллицей. Передай путь через --font. "
        f"Проверенные варианты:\n{variants}"
    )


def _expand_template(template: Image.Image, extra_slots: int) -> Image.Image:
    if extra_slots <= 0:
        return template.copy()

    new_width = template.width + extra_slots * REPEAT_SLICE_WIDTH
    expanded = Image.new(template.mode, (new_width, template.height))
    expanded.paste(
        template.crop((0, 0, REPEAT_SLICE_RIGHT, template.height)),
        (0, 0),
    )

    repeated = template.crop(
        (REPEAT_SLICE_LEFT, 0, REPEAT_SLICE_RIGHT, template.height)
    )
    for index in range(extra_slots):
        x = REPEAT_SLICE_RIGHT + index * REPEAT_SLICE_WIDTH
        expanded.paste(repeated, (x, 0))

    right_x = REPEAT_SLICE_RIGHT + extra_slots * REPEAT_SLICE_WIDTH
    expanded.paste(
        template.crop((REPEAT_SLICE_RIGHT, 0, template.width, template.height)),
        (right_x, 0),
    )
    return expanded


def _slot_centers(symbol_count: int) -> Sequence[Tuple[int, int]]:
    if symbol_count <= BASE_SLOT_COUNT:
        return BASE_SLOT_CENTERS[:symbol_count]

    extra_slots = symbol_count - BASE_SLOT_COUNT
    centers = list(BASE_SLOT_CENTERS[:5])
    centers.extend(
        (BASE_SLOT_CENTERS[4][0] + index * REPEAT_SLICE_WIDTH, 635)
        for index in range(1, extra_slots + 1)
    )
    centers.extend(
        (x + extra_slots * REPEAT_SLICE_WIDTH, y)
        for x, y in BASE_SLOT_CENTERS[5:]
    )
    return centers


def _fit_font(
    font_path: Path,
    symbols: Sequence[str],
    *,
    preferred_size: int,
    max_width: int,
    max_height: int,
    stroke_width: int,
) -> ImageFont.FreeTypeFont:
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))

    def fits(symbol: str, font: ImageFont.FreeTypeFont) -> bool:
        box = probe.textbbox(
            (0, 0),
            symbol,
            font=font,
            anchor="mm",
            stroke_width=stroke_width,
        )
        return box[2] - box[0] <= max_width and box[3] - box[1] <= max_height

    for size in range(preferred_size, 11, -1):
        font = ImageFont.truetype(str(font_path), size=size)
        if all(fits(symbol, font) for symbol in symbols):
            return font
    raise ValueError("Символы ника не помещаются внутрь шаров")


def render_winner_image(
    template: Image.Image,
    nickname: str,
    *,
    font_path: Optional[Path] = None,
) -> Image.Image:
    """Вернуть новую картинку; переданный шаблон остаётся неизменным."""
    _validate_nickname(nickname)
    if template.size != TEMPLATE_SIZE:
        raise ValueError(
            f"Ожидался шаблон {TEMPLATE_SIZE[0]}x{TEMPLATE_SIZE[1]}, "
            f"получен {template.width}x{template.height}"
        )

    source = template.convert("RGB")
    extra_slots = max(0, len(nickname) - BASE_SLOT_COUNT)
    result = _expand_template(source, extra_slots)
    centers = _slot_centers(max(BASE_SLOT_COUNT, len(nickname)))
    selected_font_path = resolve_font_path(font_path)

    large_font = _fit_font(
        selected_font_path,
        nickname[:1],
        preferred_size=68,
        max_width=88,
        max_height=88,
        stroke_width=3,
    )
    small_font = None
    if len(nickname) > 1:
        small_font = _fit_font(
            selected_font_path,
            nickname[1:],
            preferred_size=40,
            max_width=50,
            max_height=48,
            stroke_width=2,
        )

    draw = ImageDraw.Draw(result)
    for index, center in enumerate(centers):
        radius = 49 if index == 0 else 26
        x, y = center
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=BALL_FILL,
        )

    for index, (symbol, center) in enumerate(zip(nickname, centers)):
        draw.text(
            center,
            symbol,
            font=large_font if index == 0 else small_font,
            anchor="mm",
            fill=LETTER_FILL,
            stroke_width=3 if index == 0 else 2,
            stroke_fill=LETTER_STROKE,
        )
    return result


def render_winner_png(
    nickname: str,
    *,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    font_path: Optional[Path] = None,
) -> bytes:
    """Отрисовать картинку в памяти для отправки через Telegram."""
    with Image.open(template_path) as template:
        result = render_winner_image(template, nickname, font_path=font_path)

    buffer = BytesIO()
    result.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def generate_winner_image(
    template_path: Path,
    nickname: str,
    output_path: Path,
    *,
    font_path: Optional[Path] = None,
) -> Path:
    """Открыть шаблон, отрисовать ник и атомарно сохранить готовый PNG."""
    template_path = Path(template_path)
    output_path = Path(output_path)
    if template_path.resolve() == output_path.resolve():
        raise ValueError("Путь результата не должен совпадать с путём шаблона")
    with Image.open(template_path) as template:
        result = render_winner_image(template, nickname, font_path=font_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        result.save(temporary_path, format="PNG", optimize=True)
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return output_path


def _default_output_path(nickname: str) -> Path:
    safe_nickname = re.sub(r"[^\w.-]+", "_", nickname, flags=re.UNICODE)
    safe_nickname = safe_nickname.strip("._") or "winner"
    return Path.cwd() / f"lottery_winner_{safe_nickname}.png"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Нарисовать ник победителя на шарах лотереи"
    )
    parser.add_argument("nickname", help="ник победителя, регистр сохраняется")
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE_PATH,
        help=f"исходный PNG (по умолчанию: {DEFAULT_TEMPLATE_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="готовый PNG (по умолчанию: lottery_winner_<ник>.png)",
    )
    parser.add_argument(
        "--font",
        type=Path,
        help="TTF/OTF-шрифт с поддержкой символов ника",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    output_path = args.output or _default_output_path(args.nickname)
    try:
        generated = generate_winner_image(
            args.template,
            args.nickname,
            output_path,
            font_path=args.font,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    with Image.open(generated) as image:
        size = f"{image.width}x{image.height}"
    print(f"Готово: {generated.resolve()} ({size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
