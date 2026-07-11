"""Меню с фотографией: file_id кэшируется в meta, файл заливается один раз.

Правила переходов (без мигания и пересылки, где это возможно):
  фото → то же фото   = edit_caption (меняется только подпись);
  фото → другое фото  = edit_media  (фото и подпись меняются в ТОМ ЖЕ сообщении);
  текст → фото        = пересоздание (Telegram не умеет добавить фото текстовому);
  фото → текст        = пересоздание (show_text_menu).
Сравнение «то же ли фото» — по file_unique_id (хранится в meta рядом с file_id).
Нет файла/сети — тихо деградируем до текста. Подпись к фото ≤ 1024 символов.
"""
from aiogram.types import FSInputFile, InputMediaPhoto, Message

from db import storage


def _uniq_key(meta_key: str) -> str:
    return meta_key + ":uniq"


async def _remember(meta_key: str, photo_sizes) -> None:
    if photo_sizes:
        await storage.set_meta(meta_key, photo_sizes[-1].file_id)
        await storage.set_meta(_uniq_key(meta_key), photo_sizes[-1].file_unique_id)


async def show_photo_menu(message: Message, path: str, meta_key: str,
                          caption: str, kb=None) -> None:
    fid = await storage.get_meta(meta_key)
    uniq = await storage.get_meta(_uniq_key(meta_key))

    if message.photo:
        # то же самое фото — правим только подпись
        if uniq and message.photo[-1].file_unique_id == uniq:
            try:
                await message.edit_caption(caption=caption, reply_markup=kb)
                return
            except Exception as e:
                if "not modified" in str(e):
                    return
        # другое фото — меняем медиа в том же сообщении
        for media in ([fid] if fid else []) + [FSInputFile(path)]:
            try:
                edited = await message.edit_media(
                    media=InputMediaPhoto(media=media, caption=caption),
                    reply_markup=kb)
                if not isinstance(media, str):
                    await _remember(meta_key, getattr(edited, "photo", None))
                elif not uniq and getattr(edited, "photo", None):
                    await _remember(meta_key, edited.photo)
                return
            except Exception as e:
                if "not modified" in str(e):
                    return
                continue  # fid протух или файл не ушёл — следующая попытка

    # текстовое сообщение (или все правки провалились) — пересоздаём
    try:
        await message.delete()
    except Exception:
        pass
    if fid:
        try:
            sent = await message.answer_photo(fid, caption=caption, reply_markup=kb)
            if not uniq:
                await _remember(meta_key, sent.photo)
            return
        except Exception:
            pass
    try:
        sent = await message.answer_photo(FSInputFile(path), caption=caption,
                                          reply_markup=kb)
        await _remember(meta_key, sent.photo)
    except Exception:
        await message.answer(caption, reply_markup=kb)


async def show_text_menu(message: Message, text: str, kb=None) -> None:
    """Текстовое меню, умеющее приходить С фото-экрана (пересоздаёт сообщение)."""
    try:
        await message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=kb)
