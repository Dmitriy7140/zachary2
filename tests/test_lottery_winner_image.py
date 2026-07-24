from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from PIL import Image, ImageChops, ImageFont

from content import lottery as lottery_content
from scripts.lottery_winner_image import (
    BALL_FILL,
    BASE_SLOT_CENTERS,
    DEFAULT_TEMPLATE_PATH,
    FONT_CANDIDATES,
    REPEAT_SLICE_LEFT,
    REPEAT_SLICE_RIGHT,
    REPEAT_SLICE_WIDTH,
    generate_winner_image,
    render_winner_png,
    render_winner_image,
    resolve_font_path,
    _drawable_symbol,
    _load_font,
    _slot_centers,
)


class LotteryWinnerImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.font_path = resolve_font_path()

    def test_short_cyrillic_nickname_keeps_original_size_and_source(self) -> None:
        with Image.open(DEFAULT_TEMPLATE_PATH) as source:
            before = source.convert("RGB").tobytes()
            result = render_winner_image(
                source, "Андрей", font_path=self.font_path
            )
            after = source.convert("RGB").tobytes()

        self.assertEqual((1280, 720), result.size)
        self.assertEqual(before, after)
        for x, y in BASE_SLOT_CENTERS[len("Андрей"):]:
            blank_center = result.crop((x - 12, y - 12, x + 13, y + 13))
            expected = Image.new("RGB", blank_center.size, BALL_FILL)
            self.assertEqual(expected.tobytes(), blank_center.tobytes())

    def test_eight_symbols_do_not_extend_template(self) -> None:
        with Image.open(DEFAULT_TEMPLATE_PATH) as source:
            result = render_winner_image(
                source, "Belaisha", font_path=self.font_path
            )

        self.assertEqual((1280, 720), result.size)

    def test_long_nickname_repeats_42_slice_once_per_extra_symbol(self) -> None:
        nickname = "vladimir_khil"
        extra_slots = len(nickname) - 8
        with Image.open(DEFAULT_TEMPLATE_PATH) as source:
            source = source.convert("RGB")
            result = render_winner_image(
                source, nickname, font_path=self.font_path
            )

            expected_slice = source.crop(
                (REPEAT_SLICE_LEFT, 0, REPEAT_SLICE_RIGHT, 530)
            )
            for index in range(extra_slots):
                left = REPEAT_SLICE_RIGHT + index * REPEAT_SLICE_WIDTH
                actual_slice = result.crop(
                    (left, 0, left + REPEAT_SLICE_WIDTH, 530)
                )
                self.assertIsNone(
                    ImageChops.difference(expected_slice, actual_slice).getbbox()
                )

            shifted_tail_x = REPEAT_SLICE_RIGHT + extra_slots * REPEAT_SLICE_WIDTH
            expected_tail = source.crop((REPEAT_SLICE_RIGHT, 0, source.width, 530))
            actual_tail = result.crop(
                (shifted_tail_x, 0, result.width, 530)
            )
            self.assertIsNone(
                ImageChops.difference(expected_tail, actual_tail).getbbox()
            )

        self.assertEqual(
            (1280 + extra_slots * REPEAT_SLICE_WIDTH, 720), result.size
        )
        self.assertEqual(
            [
                (338, 613),
                (503, 635),
                (580, 635),
                (657, 635),
                (733, 635),
                (810, 635),
                (887, 635),
                (964, 635),
                (1041, 635),
                (1118, 635),
                (1195, 635),
                (1272, 635),
                (1349, 635),
            ],
            list(_slot_centers(len(nickname))),
        )

    def test_empty_nickname_is_rejected(self) -> None:
        with Image.open(DEFAULT_TEMPLATE_PATH) as source:
            with self.assertRaisesRegex(ValueError, "не может быть пустым"):
                render_winner_image(source, "", font_path=self.font_path)

    def test_generate_writes_png(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "winner.png"
            generated = generate_winner_image(
                DEFAULT_TEMPLATE_PATH,
                "nick_name",
                output,
                font_path=self.font_path,
            )

            self.assertEqual(output, generated)
            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual("PNG", image.format)
                self.assertEqual((1280 + REPEAT_SLICE_WIDTH, 720), image.size)

    def test_render_png_returns_telegram_ready_bytes(self) -> None:
        payload = render_winner_png("Андрей", font_path=self.font_path)

        with Image.open(BytesIO(payload)) as image:
            self.assertEqual("PNG", image.format)
            self.assertEqual((1280, 720), image.size)

    def test_ubuntu_dejavu_bold_is_preferred_system_fallback(self) -> None:
        self.assertEqual(
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            FONT_CANDIDATES[0],
        )

    def test_missing_system_fonts_fall_back_to_pillow_font(self) -> None:
        with patch("scripts.lottery_winner_image.FONT_CANDIDATES", ()):
            payload = render_winner_png("Winner")

        with Image.open(BytesIO(payload)) as image:
            self.assertEqual("PNG", image.format)
            self.assertEqual((1280, 720), image.size)

    def test_explicit_missing_font_is_still_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-font.ttf"

            with self.assertRaisesRegex(FileNotFoundError, "Файл шрифта не найден"):
                resolve_font_path(missing)

    def test_pillow_10_default_font_signature_is_supported(self) -> None:
        fallback = ImageFont.load_default()
        with patch(
            "scripts.lottery_winner_image.ImageFont.load_default",
            side_effect=[TypeError("size is unsupported"), fallback],
        ) as load_default:
            selected = _load_font(None, 40)

        self.assertIs(fallback, selected)
        self.assertEqual([call(size=40), call()], load_default.call_args_list)

    def test_unsupported_bitmap_symbol_degrades_to_question_mark(self) -> None:
        class AsciiOnlyFont:
            def getmask(self, symbol: str):
                if not symbol.isascii():
                    raise UnicodeEncodeError("ascii", symbol, 0, 1, "unsupported")
                return object()

        font = AsciiOnlyFont()
        self.assertEqual("W", _drawable_symbol(font, "W"))
        self.assertEqual("?", _drawable_symbol(font, "Ж"))

    def test_winner_announcement_uses_call_for_winning_ticket(self) -> None:
        caption = lottery_content.winner_announcement(
            '<a href="tg://user?id=1">@Winner</a>',
            12_345,
            44,
        )

        self.assertIn("🎱🏆🎟", caption)
        self.assertIn("@Winner", caption)
        self.assertIn("12 345 Z", caption)
        self.assertIn("№44</b> — «стульчики»", caption)
        self.assertLessEqual(len(caption), 1_024)

    def test_winner_announcement_does_not_invent_missing_call(self) -> None:
        caption = lottery_content.winner_announcement("@Winner", 45, 5)

        self.assertIn("№5</b>.", caption)
        self.assertNotIn("— «", caption)


if __name__ == "__main__":
    unittest.main()
