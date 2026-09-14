from __future__ import annotations

from urllib.parse import quote
from io import BytesIO
import qrcode
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..db import Database
from ..media import delete_stored_image, load_image_bytes, save_telegram_photo
from ..keyboards import main_menu
from ..states import QRBadgeState
from ..models import User, UserStatus, XPTransaction
from ..season_history import user_season_history
from ..services import (
    build_profile_qr_png,
    current_season,
    ensure_user_tokens,
    get_user_by_tg,
    season_xp,
    xp_total,
    referral_quarter_summary,
)
from ..runtime_config import get_runtime_int

router = Router(name="v11")


async def _active(session, tg_id: int) -> User | None:
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value:
        return None
    await ensure_user_tokens(session, user)
    return user


@router.message(F.text == "📈 Сезон")
async def season_profile(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _active(session, message.from_user.id)
        if not user:
            await message.answer("Профіль ще не активований.")
            return
        season = await current_season(session)
        if not season:
            await message.answer("📈 Активний сезон ще не налаштований.")
            return
        sxp = await season_xp(session, user.id, season.id)
        total = await xp_total(session, user.id)
        ranking = (
            await session.execute(
                select(XPTransaction.user_id, func.coalesce(func.sum(XPTransaction.amount), 0).label("xp"))
                .where(XPTransaction.season_id == season.id)
                .group_by(XPTransaction.user_id)
                .order_by(func.sum(XPTransaction.amount).desc())
            )
        ).all()
        rank = next((i for i, (uid, _) in enumerate(ranking, start=1) if uid == user.id), None)
        await session.commit()
        b = InlineKeyboardBuilder()
        b.button(text="🕰 Історія сезонів", callback_data="season:history")
        await message.answer(
            f"📈 <b>{season.name}</b>\n"
            f"📅 {season.starts_at.strftime('%d.%m.%Y')} — {season.ends_at.strftime('%d.%m.%Y')}\n\n"
            f"⚡ XP сезону: <b>{sxp}</b>\n"
            f"🏆 Місце в сезоні: <b>{rank or '—'}</b>\n"
            f"🚀 Загальний XP за весь час: <b>{total}</b>\n\n"
            "Сезонний рейтинг починається заново кожного сезону, але загальний XP і отримані бейджі залишаються.",
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data == "season:history")
async def season_history(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        if not user:
            await call.answer("Профіль неактивний", show_alert=True); return
        history = await user_season_history(session, user.id)
    if not history:
        await call.message.answer("🕰 Історії сезонів поки немає.")
        await call.answer(); return
    lines = ["🕰 <b>Історія сезонів</b>", ""]
    for row in history[:12]:
        status = "🟢 активний" if row["active"] else "📦 завершений"
        lines.append(
            f"<b>{row['name']}</b> · {status}\n"
            f"{row['league'].icon} {row['league'].title} · ⚡ {row['xp']} XP · 🏆 місце {row['rank'] or '—'}"
        )
    await call.message.answer("\n\n".join(lines))
    await call.answer()


@router.message(F.text == "🤝 Запросити друга")
@router.message(Command("invite"))
async def invite_friend(message: Message, db: Database, bot: Bot) -> None:
    async with db.session_factory() as session:
        user = await _active(session, message.from_user.id)
        if not user:
            await message.answer("Профіль ще не активований.")
            return
        count, next_reward, quarter_start, quarter_end = await referral_quarter_summary(session, user.id)
        referral_max = await get_runtime_int(session, "xp.referral_max")
        await session.commit()
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.referral_code}"
        b = InlineKeyboardBuilder()
        b.button(text="🚀 Перейти за запрошенням", url=link)
        share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote('Приєднуйся до АМПасадорів 🚀')}"
        b.button(text="📤 Надіслати другові", url=share)
        b.button(text="🔳 Згенерувати QR-запрошення", callback_data="invite:qr")
        b.adjust(1)
        await message.answer(
            "🤝 <b>Запроси друга в АМП</b>\n\n"
            f'<a href="{link}">Персональне посилання-запрошення</a>\n\n'
            "Бонус XP нараховується після того, як новий учасник зареєструється та його профіль буде активовано адміністратором.\n\n"
            f"📊 У цьому кварталі успішних запрошень: <b>{count}</b>.\n"
            f"Наступне успішне запрошення: <b>+{next_reward} XP</b>.\n"
            f"Схема кварталу: {referral_max} → {max(1, referral_max-1)} → … → 1 XP; усі наступні — по 1 XP. На початку нового кварталу лічильник оновлюється.",
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data == "invite:qr")
async def invite_qr(call: CallbackQuery, db: Database, bot: Bot) -> None:
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        if not user:
            await call.answer("Профіль не активований", show_alert=True)
            return
        await session.commit()
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user.referral_code}"
    qr = qrcode.QRCode(version=None, box_size=12, border=3)
    qr.add_data(link); qr.make(fit=True)
    img = qr.make_image(fill_color="#0B5B6C", back_color="white").convert("RGB")
    bio = BytesIO(); img.save(bio, format="PNG"); png = bio.getvalue()
    await call.message.answer_document(
        BufferedInputFile(png, filename=f"AMP-{user.id:04d}_invite_QR.png"),
        caption=(
            "🔳 <b>QR-запрошення в АМПасадори</b>\n\n"
            "Друг може відсканувати цей QR — Telegram відкриє бота з твоїм персональним кодом запрошення. "
            "Бонус XP нарахується після реєстрації та активації нового учасника."
        ),
    )
    await call.answer()


@router.message(F.text.in_({"🎫 QR-бейдж", "🎫 Мій QR-бейдж", "🎫 Мій QR-код", "🎫 Мій QR"}))
@router.message(Command("myqr"))
async def my_qr(message: Message, db: Database, state: FSMContext) -> None:
    """Open the QR-badge center instead of generating immediately.

    Old QR menu captions remain accepted only for compatibility with reply
    keyboards cached by Telegram clients; the visible name is QR-бейдж.
    """
    await state.clear()
    legacy_caption = (message.text or "") in {"🎫 Мій QR-код", "🎫 Мій QR"}
    async with db.session_factory() as session:
        user = await _active(session, message.from_user.id)
        if not user:
            await message.answer("Профіль ще не активований.")
            return
        has_photo = bool(user.badge_photo_path)
        user_role = user.role
    if legacy_caption:
        await message.answer(
            "🔄 Назву оновлено: тепер цей розділ називається <b>«🎫 Мій QR-бейдж»</b>.",
            reply_markup=main_menu(user_role),
        )
    b = InlineKeyboardBuilder()
    b.button(text="🎫 Згенерувати бейдж", callback_data="qr_badge:generate")
    b.button(text="📷 Додати фото", callback_data="qr_badge:photo")
    b.button(text="⬇️ Завантажити PNG", callback_data="qr_badge:download")
    b.button(text="📤 Поділитися", callback_data="qr_badge:share")
    if has_photo:
        b.button(text="🗑 Прибрати фото", callback_data="qr_badge:remove_photo")
    b.button(text="⬅️ Назад до меню", callback_data="qr_badge:back")
    b.adjust(2, 2, 1, 1)
    await message.answer(
        "🎫 <b>Мій QR-бейдж</b>\n\n"
        "Персональний бейдж АМП у єдиному форматі <b>55 × 85 мм</b>, підготовлений для друку. "
        "Можеш додати власне фото — воно автоматично з’являтиметься на наступних версіях бейджа.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data == "qr_badge:back")
async def qr_badge_back(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        if not user:
            await call.answer("Профіль не активований", show_alert=True); return
        role = user.role
    await call.message.answer("🏠 Головне меню", reply_markup=main_menu(role))
    await call.answer()


async def _make_qr_badge(db: Database, bot: Bot, tg_id: int) -> tuple[User | None, bytes | None, str | None]:
    async with db.session_factory() as session:
        user = await _active(session, tg_id)
        if not user:
            return None, None, None
        total = await xp_total(session, user.id)
        from ..gamification import get_level
        level = get_level(total)[0]
        await session.commit()
    me = await bot.get_me()
    photo_bytes = await load_image_bytes(db, user.badge_photo_path)
    png = build_profile_qr_png(user, me.username, total_xp=total, level=level, profile_photo=photo_bytes)
    public_link = f"https://t.me/{me.username}?start=profile_{user.public_token}"
    return user, png, public_link


@router.callback_query(F.data == "qr_badge:generate")
async def qr_badge_generate(call: CallbackQuery, db: Database, bot: Bot) -> None:
    user, png, _ = await _make_qr_badge(db, bot, call.from_user.id)
    if not user or not png:
        await call.answer("Профіль не активований", show_alert=True)
        return
    await call.message.answer_photo(
        BufferedInputFile(png, filename=f"AMP-{user.id:04d}_QR-badge.png"),
        caption=(
            f"🎫 <b>QR-бейдж АМП-{user.id:04d}</b>\n"
            f"{user.full_name}\n\n"
            "Формат для друку: <b>55 × 85 мм, 300 DPI</b>. "
            "QR відкриває лише публічну картку без контактних і чутливих даних."
        ),
    )
    await call.answer()


@router.callback_query(F.data == "qr_badge:download")
async def qr_badge_download(call: CallbackQuery, db: Database, bot: Bot) -> None:
    user, png, _ = await _make_qr_badge(db, bot, call.from_user.id)
    if not user or not png:
        await call.answer("Профіль не активований", show_alert=True)
        return
    await call.message.answer_document(
        BufferedInputFile(png, filename=f"AMP-{user.id:04d}_QR-badge_55x85mm.png"),
        caption="⬇️ PNG-файл QR-бейджа для збереження або друку: 55 × 85 мм, 300 DPI.",
    )
    await call.answer()


@router.callback_query(F.data == "qr_badge:photo")
async def qr_badge_photo_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(QRBadgeState.photo)
    await call.message.answer(
        "📷 Надішли <b>одне фото</b> для QR-бейджа.\n"
        "Підійде JPG, PNG або WebP до <b>20 МБ</b>. Найкраще — портрет, де добре видно обличчя.\n\n"
        "Після завантаження просто згенеруй бейдж ще раз."
    )
    await call.answer()


@router.message(QRBadgeState.photo, F.photo)
async def qr_badge_photo_receive(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    async with db.session_factory() as session:
        user = await _active(session, message.from_user.id)
        if not user:
            await state.clear()
            await message.answer("Профіль ще не активований.")
            return
        old_path = user.badge_photo_path
    try:
        new_path = await save_telegram_photo(bot, message.photo[-1].file_id, "qr_badges", db, max_mb=20)
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    async with db.session_factory() as session:
        user = await _active(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        user.badge_photo_path = new_path
        await session.commit()
    if old_path and old_path != new_path:
        await delete_stored_image(db, old_path)
    await state.clear()
    await message.answer("✅ Фото збережено. Відкрий «🎫 Мій QR-бейдж» і натисни «Згенерувати бейдж».")


@router.message(QRBadgeState.photo)
async def qr_badge_photo_wrong(message: Message) -> None:
    await message.answer("Надішли фото як зображення. Максимальний розмір — 20 МБ.")


@router.callback_query(F.data == "qr_badge:remove_photo")
async def qr_badge_photo_remove(call: CallbackQuery, db: Database) -> None:
    old_path = None
    async with db.session_factory() as session:
        user = await _active(session, call.from_user.id)
        if not user:
            await call.answer("Профіль не активований", show_alert=True)
            return
        old_path = user.badge_photo_path
        user.badge_photo_path = None
        await session.commit()
    if old_path:
        await delete_stored_image(db, old_path)
    await call.message.answer("✅ Фото з QR-бейджа прибрано.")
    await call.answer()


@router.callback_query(F.data == "qr_badge:share")
async def qr_badge_share(call: CallbackQuery, db: Database, bot: Bot) -> None:
    user, png, public_link = await _make_qr_badge(db, bot, call.from_user.id)
    if not user or not png or not public_link:
        await call.answer("Профіль не активований", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    share_url = f"https://t.me/share/url?url={quote(public_link, safe='')}&text={quote('Мій QR-бейдж АМПасадора', safe='')}"
    b.button(text="📤 Поділитися бейджем", url=share_url)
    await call.message.answer_photo(
        BufferedInputFile(png, filename=f"AMP-{user.id:04d}_QR-badge.png"),
        caption="📤 Це твій QR-бейдж. Зображення можна переслати в інший чат, а кнопка нижче ділиться публічним посиланням профілю.",
        reply_markup=b.as_markup(),
    )
    await call.answer()
