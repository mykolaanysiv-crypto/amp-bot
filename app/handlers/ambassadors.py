from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from ..ambassadors import responsibility_label
from ..db import Database
from ..media import save_telegram_photo
from ..models import AmbassadorReport, UserRole, UserStatus
from ..services import get_user_by_tg
from ..states import AmbassadorReportState

router = Router(name="ambassadors")


def _parse_date(value: str):
    raw = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _cabinet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Подати звіт", callback_data="ambassador:report:start")],
        [InlineKeyboardButton(text="🧭 Мій напрям відповідальності", callback_data="ambassador:responsibility")],
    ])


async def _ambassador_user(session, tg_id: int):
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role != UserRole.AMBASSADOR.value:
        return None
    return user


@router.callback_query(F.data == "ambassador:cabinet")
async def ambassador_cabinet(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _ambassador_user(session, call.from_user.id)
        if not user:
            await call.answer("Кабінет доступний лише АМПасадорам", show_alert=True)
            return
        reports_count = len(list((await session.scalars(select(AmbassadorReport.id).where(AmbassadorReport.user_id == user.id))).all()))
        responsibility = responsibility_label(user.ambassador_responsibility)
    await call.message.answer(
        "🧭 <b>Кабінет АМПасадора</b>\n\n"
        f"👤 {escape(user.full_name)}\n"
        f"📍 Напрям відповідальності: <b>{escape(responsibility)}</b>\n"
        f"📋 Подано звітів: <b>{reports_count}</b>\n\n"
        "Тут можна подати звіт про роботу за період. Напрям відповідальності призначає команда АМП через панель керування.",
        reply_markup=_cabinet_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "ambassador:responsibility")
async def ambassador_responsibility(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _ambassador_user(session, call.from_user.id)
        if not user:
            await call.answer("Недоступно", show_alert=True); return
        value = responsibility_label(user.ambassador_responsibility)
    await call.message.answer(f"🧭 <b>Твій напрям відповідальності</b>\n\n{escape(value)}")
    await call.answer()


@router.callback_query(F.data == "ambassador:report:start")
async def ambassador_report_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _ambassador_user(session, call.from_user.id)
    if not user:
        await call.answer("Форма доступна лише АМПасадорам", show_alert=True); return
    await state.clear()
    await state.set_state(AmbassadorReportState.period_start)
    await call.message.answer("📋 <b>Звіт АМПасадора</b>\n\nВкажи початок звітного періоду у форматі <code>ДД.ММ.РРРР</code>.")
    await call.answer()


@router.message(AmbassadorReportState.period_start)
async def ambassador_report_period_start(message: Message, state: FSMContext) -> None:
    value = _parse_date(message.text or "")
    if not value:
        await message.answer("❗ Некоректна дата. Приклад: <code>01.09.2026</code>")
        return
    await state.update_data(period_start=value.isoformat())
    await state.set_state(AmbassadorReportState.period_end)
    await message.answer("Вкажи кінець звітного періоду у форматі <code>ДД.ММ.РРРР</code>.")


@router.message(AmbassadorReportState.period_end)
async def ambassador_report_period_end(message: Message, state: FSMContext) -> None:
    value = _parse_date(message.text or "")
    data = await state.get_data()
    start = datetime.fromisoformat(str(data.get("period_start"))).date() if data.get("period_start") else None
    if not value or not start or value < start:
        await message.answer("❗ Дата завершення має бути не раніше початку періоду.")
        return
    await state.update_data(period_end=value.isoformat())
    await state.set_state(AmbassadorReportState.description)
    await message.answer("✍️ Опиши, <b>що було зроблено за цей період</b>. Можна вказати проведені активності, чергування, допомогу команді, результати та інше.")


@router.message(AmbassadorReportState.description)
async def ambassador_report_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer("Опиши роботу трохи детальніше — щонайменше 10 символів.")
        return
    await state.update_data(description=text[:5000])
    await state.set_state(AmbassadorReportState.photo)
    await message.answer(
        "📷 Додай <b>фото-підтвердження</b> роботи або пропусти цей крок.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Без фото", callback_data="ambassador:report:skip_photo")]]),
    )


async def _save_report(tg_id: int, db: Database, state: FSMContext, photo_path: str | None) -> AmbassadorReport | None:
    data = await state.get_data()
    async with db.session_factory() as session:
        user = await _ambassador_user(session, tg_id)
        if not user:
            return None
        report = AmbassadorReport(
            user_id=user.id,
            period_start=datetime.fromisoformat(str(data["period_start"])).date(),
            period_end=datetime.fromisoformat(str(data["period_end"])).date(),
            description=str(data["description"]),
            photo_path=photo_path,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report


@router.message(AmbassadorReportState.photo, F.photo)
async def ambassador_report_photo(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    try:
        path = await save_telegram_photo(bot, message.photo[-1].file_id, "ambassador_reports", db, max_mb=20)
    except ValueError as exc:
        await message.answer(str(exc)); return
    report = await _save_report(message.from_user.id, db, state, path)
    await state.clear()
    if not report:
        await message.answer("Не вдалося подати звіт: кабінет доступний лише АМПасадорам."); return
    await message.answer(f"✅ <b>Звіт №{report.id} подано.</b>\nКоманда АМП побачить його у веб-панелі.")


@router.callback_query(F.data == "ambassador:report:skip_photo")
async def ambassador_report_skip_photo(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    current = await state.get_state()
    if current != AmbassadorReportState.photo.state:
        await call.answer("Форма вже завершена або скасована", show_alert=True); return
    report = await _save_report(call.from_user.id, db, state, None)
    await state.clear()
    if report:
        await call.message.answer(f"✅ <b>Звіт №{report.id} подано.</b>\nКоманда АМП побачить його у веб-панелі.")
    await call.answer()
