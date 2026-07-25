import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import BufferedInputFile, InputMediaPhoto

from utils.photo import show_dynamic_photo


def _message(*, has_photo: bool):
    return SimpleNamespace(
        photo=[object()] if has_photo else [],
        edit_media=AsyncMock(),
        answer_photo=AsyncMock(),
        answer=AsyncMock(),
        delete=AsyncMock(),
    )


class DynamicPhotoTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_photo_is_replaced_in_same_message(self) -> None:
        message = _message(has_photo=True)

        await show_dynamic_photo(
            message, b"png payload", "cube.png", "caption", "keyboard"
        )

        message.edit_media.assert_awaited_once()
        media = message.edit_media.await_args.kwargs["media"]
        self.assertIsInstance(media, InputMediaPhoto)
        self.assertIsInstance(media.media, BufferedInputFile)
        self.assertEqual(b"png payload", media.media.data)
        self.assertEqual("cube.png", media.media.filename)
        self.assertEqual("caption", media.caption)
        self.assertEqual("keyboard", message.edit_media.await_args.kwargs["reply_markup"])
        message.answer_photo.assert_not_awaited()
        message.delete.assert_not_awaited()

    async def test_text_message_is_replaced_only_after_photo_was_sent(self) -> None:
        message = _message(has_photo=False)
        order: list[str] = []
        message.answer_photo.side_effect = lambda *args, **kwargs: order.append("sent")
        message.delete.side_effect = lambda *args, **kwargs: order.append("deleted")

        await show_dynamic_photo(message, b"png", "cube.png", "caption")

        self.assertEqual(["sent", "deleted"], order)
        message.edit_media.assert_not_awaited()
        upload = message.answer_photo.await_args.args[0]
        self.assertIsInstance(upload, BufferedInputFile)
        self.assertEqual(b"png", upload.data)

    async def test_failed_edit_sends_replacement_before_deleting_old_photo(self) -> None:
        message = _message(has_photo=True)
        order: list[str] = []
        message.edit_media.side_effect = RuntimeError("edit failed")
        message.answer_photo.side_effect = lambda *args, **kwargs: order.append("sent")
        message.delete.side_effect = lambda *args, **kwargs: order.append("deleted")

        await show_dynamic_photo(message, b"png", "cube.png", "caption")

        self.assertEqual(["sent", "deleted"], order)
        message.answer.assert_not_awaited()

    async def test_failed_photo_upload_falls_back_to_text_then_deletes_old(self) -> None:
        message = _message(has_photo=False)
        order: list[str] = []
        message.answer_photo.side_effect = RuntimeError("upload failed")
        message.answer.side_effect = lambda *args, **kwargs: order.append("text")
        message.delete.side_effect = lambda *args, **kwargs: order.append("deleted")

        await show_dynamic_photo(
            message, b"png", "cube.png", "caption", "keyboard"
        )

        self.assertEqual(["text", "deleted"], order)
        message.answer.assert_awaited_once_with("caption", reply_markup="keyboard")

    async def test_failed_replacement_keeps_original_message(self) -> None:
        message = _message(has_photo=False)
        message.answer_photo.side_effect = RuntimeError("upload failed")
        message.answer.side_effect = RuntimeError("text failed")

        with self.assertRaisesRegex(RuntimeError, "text failed"):
            await show_dynamic_photo(message, b"png", "cube.png", "caption")

        message.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
