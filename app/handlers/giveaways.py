from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from ..db import Database
from ..giveaways import audience_label, is_open_now, participation_label, user_is_eligible
from ..media import delete_stored_image, save_telegram_photo, telegram_photo_input
from ..model_domains import Giveaway, GiveawayEntry, GiveawayPrize, GiveawayWinner, User, UserRole, UserStatus
from ..reliability import queue_telegram_delivery
from ..domain_services import get_user_by_tg
from ..states import GiveawayEntryState
from ..time_utils import clock

router = Router(name="giveaways")


def _local_dt(value):
    if not value:
        return "—"
    aware = clock.from_storage_utc(value)
    return clock.utc_to_local(aware).strftime("%d.%m.%Y %H:%M") if aware else "—"


def _entry_status(status: str) -> str:
    return {
        "pending": "⏳ На перевірці",
        "approved": "✅ Допущено до розіграшу",
        "returned": "↩️ Потрібно доопрацювати",
        "rejected": "🚫 Не допущено",
    }.get(status, status)


async def _active_visible_giveaways(session, user: User) -> list[Giveaway]:
    now = clock.storage_utc()
    rows = list((await session.scalars(
        select(Giveaway).where(Giveaway.status == "active").order_by(Giveaway.ends_at.asc(), Giveaway.id.desc())
    )).all())
    visible: list[Giveaway] = []
    for row in rows:
        if not is_open_now(row, now=now):
            continue
        if await user_is_eligible(session, row, user):
            visible.append(row)
    return visible


async def list_giveaways(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            await message.answer("Профіль ще не активований. Натисніть /start")
            return
        rows = await _active_visible_giveaways(session, user)
        entries = {row.giveaway_id: row for row in (await session.scalars(
            select(GiveawayEntry).where(GiveawayEntry.user_id == user.id)
        )).all()}
    if not rows:
        await message.answer("🎲 <b>Розіграші</b>\n\nЗараз для тебе немає активних розіграшів.")
        return
    buttons = []
    lines = ["🎲 <b>Активні розіграші</b>", "", "Тут видно розіграші, у яких ти береш участь автоматично, або до яких можна долучитися після виконання умови.", ""]
    for row in rows:
        entry = entries.get(row.id)
        if row.participation_mode == "automatic":
            status = "🎟 береш участь автоматично"
        elif entry:
            status = _entry_status(entry.status)
        else:
            status = "📷 можна виконати умову"
        lines.append(f"• <b>{escape(row.title)}</b> — {status}\n  ⏳ до {_local_dt(row.ends_at)}")
        buttons.append([InlineKeyboardButton(text=f"🎲 {row.title}", callback_data=f"giveaway:{row.id}")])
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(F.text == "🎲 Розіграші")
async def giveaways_message(message: Message, db: Database) -> None:
    await list_giveaways(message, db)


@router.callback_query(F.data == "giveaway:list")
async def giveaways_callback(call: CallbackQuery, db: Database) -> None:
    msg = call.message.model_copy(update={"from_user": call.from_user, "text": "🎲 Розіграші"})
    await list_giveaways(msg, db)
    await call.answer()


@router.callback_query(F.data.regexp(r"^giveaway:\d+$"))
async def giveaway_detail(call: CallbackQuery, db: Database) -> None:
    giveaway_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        giveaway = await session.get(Giveaway, giveaway_id)
        if not user or user.status != UserStatus.ACTIVE.value or not giveaway:
            await call.answer("Розіграш недоступний", show_alert=True)
            return
        eligible = await user_is_eligible(session, giveaway, user)
        winner = await session.scalar(select(GiveawayWinner).where(GiveawayWinner.giveaway_id == giveaway.id, GiveawayWinner.user_id == user.id))
        entry = await session.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway.id, GiveawayEntry.user_id == user.id))
        # Active draws are audience-gated. A past winner may still open the result from the notification.
        if giveaway.status in {"active", "drawn"} and not eligible and not winner:
            await call.answer("Цей розіграш не входить до твоєї аудиторії", show_alert=True)
            return
        if giveaway.status not in {"active", "drawn"} and not winner:
            await call.answer("Розіграш зараз недоступний", show_alert=True)
            return
        prizes = list((await session.scalars(
            select(GiveawayPrize).where(GiveawayPrize.giveaway_id == giveaway.id).order_by(GiveawayPrize.sort_order, GiveawayPrize.id)
        )).all())
        won_prize = await session.get(GiveawayPrize, winner.prize_id) if winner else None
    lines = [
        f"🎲 <b>{escape(giveaway.title)}</b>", "",
        escape(giveaway.description or "Без додаткового опису."), "",
        f"👥 <b>{escape(audience_label(giveaway))}</b>",
        f"🎟 {escape(participation_label(giveaway))}",
        f"⏳ Дедлайн: <b>{_local_dt(giveaway.ends_at)}</b>",
    ]
    if giveaway.participation_mode == "automatic" and giveaway.status == "active":
        lines += ["", "✅ <b>Ти береш участь автоматично.</b> Нічого додатково робити не потрібно."]
    if giveaway.participation_mode == "task":
        lines += ["", "📷 <b>Умова участі</b>", escape(giveaway.task_text or "Виконай умову та надішли підтвердження.")]
        if entry:
            lines += ["", f"Статус підтвердження: <b>{escape(_entry_status(entry.status))}</b>"]
            if entry.review_note:
                lines.append(f"💬 {escape(entry.review_note)}")
    lines += ["", "🎁 <b>Подарунки</b>"]
    for prize in prizes:
        lines.append(f"• {escape(prize.title)} × <b>{prize.quantity}</b>" + (f" — {escape(prize.description)}" if prize.description else ""))
    if giveaway.status == "drawn":
        if winner and won_prize:
            lines += ["", f"🏆 <b>Ти переміг/ла!</b>\nТвій подарунок: <b>{escape(won_prize.title)}</b>\nЗ тобою зв’яжеться адміністратор АМП щодо отримання."]
        else:
            lines += ["", "Розіграш уже проведено. Цього разу подарунок дістався іншому учаснику."]
    buttons = []
    if giveaway.status == "active" and giveaway.participation_mode == "task" and eligible:
        if entry is None or entry.status == "returned":
            buttons.append([InlineKeyboardButton(text="📷 Виконати умову / надіслати підтвердження", callback_data=f"giveaway:submit:{giveaway.id}")])
        elif entry.status == "pending":
            buttons.append([InlineKeyboardButton(text="⏳ Підтвердження на перевірці", callback_data="noop")])
        elif entry.status == "approved":
            buttons.append([InlineKeyboardButton(text="✅ Участь підтверджено", callback_data="noop")])
        elif entry.status == "rejected":
            buttons.append([InlineKeyboardButton(text="🚫 Підтвердження відхилено", callback_data="noop")])
    buttons.append([InlineKeyboardButton(text="⬅️ Активні розіграші", callback_data="giveaway:list")])
    await call.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    # Show prize artwork without exposing secure storage URLs.
    for prize in prizes:
        photo = await telegram_photo_input(db, prize.image_path)
        if photo:
            await call.message.answer_photo(photo, caption=f"🎁 <b>{escape(prize.title)}</b> × {prize.quantity}" + (f"\n{escape(prize.description)}" if prize.description else ""))
    await call.answer()


@router.callback_query(F.data.regexp(r"^giveaway:submit:\d+$"))
async def giveaway_submit_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    giveaway_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        giveaway = await session.get(Giveaway, giveaway_id)
        if not user or not giveaway or giveaway.participation_mode != "task" or not is_open_now(giveaway):
            await call.answer("Подання підтвердження зараз недоступне", show_alert=True)
            return
        if not await user_is_eligible(session, giveaway, user):
            await call.answer("Цей розіграш недоступний для твоєї категорії", show_alert=True)
            return
        entry = await session.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway.id, GiveawayEntry.user_id == user.id))
        if entry and entry.status in {"pending", "approved", "rejected"}:
            await call.answer("Підтвердження вже подано", show_alert=True)
            return
    await state.clear()
    await state.update_data(giveaway_id=giveaway_id)
    await state.set_state(GiveawayEntryState.report_text)
    await call.message.answer(
        f"📷 <b>Участь у розіграші «{escape(giveaway.title)}»</b>\n\n"
        f"Умова: {escape(giveaway.task_text)}\n\n"
        "Коротко опиши, що ти виконав/ла. Після цього потрібно буде <b>обов’язково надіслати фото-підтвердження</b>."
    )
    await call.answer()


@router.message(GiveawayEntryState.report_text)
async def giveaway_report_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer("Опиши виконання трохи детальніше — щонайменше 10 символів.")
        return
    await state.update_data(giveaway_report_text=text[:5000])
    await state.set_state(GiveawayEntryState.photo)
    await message.answer("📸 Тепер надішли <b>одне фото-підтвердження</b>. Без фото заявка не буде подана.")


@router.message(GiveawayEntryState.photo, F.photo)
async def giveaway_report_photo(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    data = await state.get_data()
    giveaway_id = int(data.get("giveaway_id") or 0)
    report_text = str(data.get("giveaway_report_text") or "").strip()
    if not giveaway_id or not report_text:
        await state.clear()
        await message.answer("Сесію подання втрачено. Відкрий розіграш і спробуй ще раз.")
        return
    try:
        photo_path = await save_telegram_photo(bot, message.photo[-1].file_id, "giveaway_proofs", db, max_mb=20)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        giveaway = await session.get(Giveaway, giveaway_id)
        if not user or not giveaway or not is_open_now(giveaway) or not await user_is_eligible(session, giveaway, user):
            await state.clear()
            if photo_path:
                await delete_stored_image(db, photo_path)
            await message.answer("Розіграш уже недоступний для подання підтвердження.")
            return
        entry = await session.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway.id, GiveawayEntry.user_id == user.id))
        now = clock.storage_utc()
        old_photo = None
        if entry is None:
            entry = GiveawayEntry(giveaway_id=giveaway.id, user_id=user.id, source="task", status="pending", created_at=now, updated_at=now)
            session.add(entry)
        else:
            if entry.status not in {"returned"}:
                await state.clear()
                if photo_path:
                    await delete_stored_image(db, photo_path)
                await message.answer("Підтвердження вже подано.")
                return
            old_photo = entry.proof_photo_path
        entry.status = "pending"
        entry.report_text = report_text
        entry.proof_photo_path = photo_path
        entry.submitted_at = now
        entry.reviewed_at = None
        entry.reviewed_by = None
        entry.review_note = ""
        entry.updated_at = now
        await session.flush()
        admins = list((await session.scalars(select(User).where(
            User.status == UserStatus.ACTIVE.value,
            User.role.in_([UserRole.ADMIN.value, UserRole.SUPERADMIN.value]),
        ))).all())
        for admin in admins:
            if admin.tg_id:
                await queue_telegram_delivery(
                    session, admin.tg_id,
                    f"🎲 <b>Нове підтвердження для розіграшу</b>\n\n«{giveaway.title}»\n👤 {escape(user.full_name)} · АМП-{user.id:04d}\n\nПеревірте заявку у Web → Гейміфікація → Розіграші.",
                    source="giveaway", dedupe_key=f"giveaway_submission:{entry.id}:{now.isoformat()}:{admin.id}", recipient_user_id=admin.id,
                    entity_type="giveaway", entity_id=giveaway.id,
                )
        await session.commit()
    if old_photo and old_photo != photo_path:
        await delete_stored_image(db, old_photo)
    await state.clear()
    await message.answer(
        f"✅ <b>Підтвердження подано</b>\n\nРозіграш: «{escape(giveaway.title)}».\nАдміністратор перевірить виконання. Після підтвердження ти будеш допущений/а до автоматичного розіграшу."
    )


@router.message(GiveawayEntryState.photo)
async def giveaway_report_photo_required(message: Message) -> None:
    await message.answer("📸 Для цього розіграшу фото-підтвердження обов’язкове. Надішли фото одним повідомленням.")
