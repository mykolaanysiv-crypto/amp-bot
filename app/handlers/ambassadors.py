from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from ..ambassadors import AMP_TEAM_ROLES, responsibility_label
from ..db import Database
from ..media import save_telegram_photo
from ..models import AmbassadorReport, TeamTask, User, UserRole, UserStatus
from ..reliability import queue_telegram_delivery
from ..services import get_user_by_tg
from ..states import AmbassadorReportState, TeamTaskReportState
from ..time_utils import clock
from ..ui_labels import label

router = Router(name="ambassadors")


def _parse_date(value: str):
    raw = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _task_status_label(status: str) -> str:
    return {
        "assigned": "Призначено",
        "submitted": "Звіт на перевірці",
        "returned": "На доопрацюванні",
        "approved": "Виконано",
        "cancelled": "Скасовано",
    }.get(status, status)


def _cabinet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Мої завдання", callback_data="teamtask:list")],
        [InlineKeyboardButton(text="📋 Подати періодичний звіт", callback_data="ambassador:report:start")],
        [InlineKeyboardButton(text="🧭 Мій напрям відповідальності", callback_data="ambassador:responsibility")],
    ])


async def _team_user(session, tg_id: int):
    user = await get_user_by_tg(session, tg_id)
    if not user or user.status != UserStatus.ACTIVE.value or user.role not in AMP_TEAM_ROLES:
        return None
    return user


@router.callback_query(F.data == "ambassador:cabinet")
async def ambassador_cabinet(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _team_user(session, call.from_user.id)
        if not user:
            await call.answer("Кабінет доступний лише команді АМП", show_alert=True)
            return
        reports_count = len(list((await session.scalars(select(AmbassadorReport.id).where(AmbassadorReport.user_id == user.id))).all()))
        open_tasks = len(list((await session.scalars(select(TeamTask.id).where(
            TeamTask.assignee_user_id == user.id,
            TeamTask.status.in_(["assigned", "returned", "submitted"]),
        ))).all()))
        responsibility = responsibility_label(user.ambassador_responsibility)
    await call.message.answer(
        "🧭 <b>Кабінет команди АМП</b>\n\n"
        f"👤 {escape(user.full_name)} · <b>{escape(label(user.role))}</b>\n"
        f"📍 Напрям відповідальності: <b>{escape(responsibility)}</b>\n"
        f"✅ Активних завдань: <b>{open_tasks}</b>\n"
        f"📋 Періодичних звітів: <b>{reports_count}</b>\n\n"
        "Тут можна переглядати персональні завдання, звітувати про їх виконання та подавати періодичні звіти.",
        reply_markup=_cabinet_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "ambassador:responsibility")
async def ambassador_responsibility(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _team_user(session, call.from_user.id)
        if not user:
            await call.answer("Недоступно", show_alert=True)
            return
        value = responsibility_label(user.ambassador_responsibility)
    await call.message.answer(f"🧭 <b>Твій напрям відповідальності</b>\n\n{escape(value)}")
    await call.answer()


@router.callback_query(F.data == "teamtask:list")
async def team_task_list(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _team_user(session, call.from_user.id)
        if not user:
            await call.answer("Недоступно", show_alert=True)
            return
        tasks = list((await session.scalars(
            select(TeamTask)
            .where(TeamTask.assignee_user_id == user.id)
            .order_by(TeamTask.created_at.desc())
            .limit(30)
        )).all())
    if not tasks:
        await call.message.answer("✅ <b>Мої завдання</b>\n\nПерсональних завдань поки немає.")
        await call.answer()
        return
    rows = []
    for task in tasks:
        icon = "✅" if task.status == "approved" else ("📤" if task.status == "submitted" else ("↩️" if task.status == "returned" else "📌"))
        rows.append([InlineKeyboardButton(text=f"{icon} {task.title}", callback_data=f"teamtask:{task.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Кабінет команди", callback_data="ambassador:cabinet")])
    await call.message.answer("✅ <b>Мої завдання</b>\n\nОбери завдання, щоб переглянути деталі або подати звіт:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.regexp(r"^teamtask:\d+$"))
async def team_task_detail(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await _team_user(session, call.from_user.id)
        task = await session.get(TeamTask, task_id)
        if not user or not task or task.assignee_user_id != user.id:
            await call.answer("Завдання недоступне", show_alert=True)
            return
    deadline = task.deadline.strftime("%d.%m.%Y %H:%M") if task.deadline else "без дедлайну"
    text = (
        f"✅ <b>{escape(task.title)}</b>\n\n"
        f"📌 Статус: <b>{escape(_task_status_label(task.status))}</b>\n"
        f"⚡ Винагорода: <b>{task.xp_reward} XP</b>\n"
        f"📅 Дедлайн: <b>{deadline}</b>\n\n"
        f"{escape(task.description or 'Без додаткового опису.')}"
    )
    if task.report_text:
        text += f"\n\n📋 <b>Твій звіт</b>\n{escape(task.report_text)}"
    if task.review_note:
        text += f"\n\n💬 <b>Коментар перевірки</b>\n{escape(task.review_note)}"
    rows = []
    if task.status in {"assigned", "returned"}:
        rows.append([InlineKeyboardButton(text="📋 Прозвітувати про виконання", callback_data=f"teamtask:report:{task.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ До моїх завдань", callback_data="teamtask:list")])
    await call.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.regexp(r"^teamtask:report:\d+$"))
async def team_task_report_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    task_id = int(call.data.rsplit(":", 1)[1])
    async with db.session_factory() as session:
        user = await _team_user(session, call.from_user.id)
        task = await session.get(TeamTask, task_id)
        if not user or not task or task.assignee_user_id != user.id or task.status not in {"assigned", "returned"}:
            await call.answer("Звіт для цього завдання зараз недоступний", show_alert=True)
            return
    await state.clear()
    await state.update_data(team_task_id=task_id)
    await state.set_state(TeamTaskReportState.report_text)
    await call.message.answer(
        f"📋 <b>Звіт до завдання «{escape(task.title)}»</b>\n\n"
        "Опиши, що саме виконано та який отримано результат. <b>Текстовий звіт обов’язковий.</b>"
    )
    await call.answer()


@router.message(TeamTaskReportState.report_text)
async def team_task_report_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer("Опиши результат детальніше — щонайменше 10 символів.")
        return
    await state.update_data(team_task_report_text=text[:5000])
    await state.set_state(TeamTaskReportState.photo)
    await message.answer(
        "📷 Можеш додати фото-підтвердження або завершити звіт без фото.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Завершити без фото", callback_data="teamtask:report:skip_photo")]]),
    )


async def _submit_team_task_report(tg_id: int, db: Database, state: FSMContext, photo_path: str | None) -> TeamTask | None:
    data = await state.get_data()
    task_id = int(data.get("team_task_id") or 0)
    report_text = str(data.get("team_task_report_text") or "").strip()
    if not task_id or len(report_text) < 10:
        return None
    async with db.session_factory() as session:
        user = await _team_user(session, tg_id)
        task = await session.get(TeamTask, task_id)
        if not user or not task or task.assignee_user_id != user.id or task.status not in {"assigned", "returned"}:
            return None
        task.report_text = report_text
        if photo_path:
            task.report_photo_path = photo_path
        task.status = "submitted"
        task.submitted_at = clock.storage_utc()
        task.updated_at = clock.storage_utc()
        task.review_note = ""
        admins = list((await session.scalars(select(User).where(
            User.status == UserStatus.ACTIVE.value,
            User.role.in_([UserRole.ADMIN.value, UserRole.SUPERADMIN.value]),
            User.tg_id.is_not(None),
        ))).all())
        for admin in admins:
            await queue_telegram_delivery(
                session,
                admin.tg_id,
                f"📋 <b>Новий звіт до командного завдання</b>\n\n<b>{escape(task.title)}</b>\n👤 {escape(user.full_name)}\n⚡ {task.xp_reward} XP\n\nПеревір звіт у веб-панелі → Команда АМП.",
                source="team_task",
                dedupe_key=f"team_task_submitted:{task.id}:{task.submitted_at.isoformat()}:{admin.id}",
                recipient_user_id=admin.id,
                entity_type="team_task",
                entity_id=task.id,
            )
        await session.commit()
        await session.refresh(task)
        return task


@router.message(TeamTaskReportState.photo, F.photo)
async def team_task_report_photo(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    try:
        path = await save_telegram_photo(bot, message.photo[-1].file_id, "team_task_reports", db, max_mb=20)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    task = await _submit_team_task_report(message.from_user.id, db, state, path)
    await state.clear()
    if not task:
        await message.answer("Не вдалося подати звіт. Перевір статус завдання.")
        return
    await message.answer(f"✅ <b>Звіт до завдання №{task.id} подано.</b>\nXP буде нараховано після перевірки адміністратором.")


@router.callback_query(F.data == "teamtask:report:skip_photo")
async def team_task_report_skip_photo(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if await state.get_state() != TeamTaskReportState.photo.state:
        await call.answer("Форма вже завершена або скасована", show_alert=True)
        return
    task = await _submit_team_task_report(call.from_user.id, db, state, None)
    await state.clear()
    if task:
        await call.message.answer(f"✅ <b>Звіт до завдання №{task.id} подано.</b>\nXP буде нараховано після перевірки адміністратором.")
    await call.answer()


@router.callback_query(F.data == "ambassador:report:start")
async def ambassador_report_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        user = await _team_user(session, call.from_user.id)
    if not user:
        await call.answer("Форма доступна лише команді АМП", show_alert=True)
        return
    await state.clear()
    await state.set_state(AmbassadorReportState.period_start)
    await call.message.answer("📋 <b>Періодичний звіт команди АМП</b>\n\nВкажи початок звітного періоду у форматі <code>ДД.ММ.РРРР</code>.")
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
    await message.answer("✍️ Опиши, <b>що було зроблено за цей період</b>: активності, чергування, допомогу команді, результати та інше.")


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
        user = await _team_user(session, tg_id)
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
        await message.answer(str(exc))
        return
    report = await _save_report(message.from_user.id, db, state, path)
    await state.clear()
    if not report:
        await message.answer("Не вдалося подати звіт: кабінет доступний лише команді АМП.")
        return
    await message.answer(f"✅ <b>Звіт №{report.id} подано.</b>\nКоманда АМП побачить його у веб-панелі.")


@router.callback_query(F.data == "ambassador:report:skip_photo")
async def ambassador_report_skip_photo(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    current = await state.get_state()
    if current != AmbassadorReportState.photo.state:
        await call.answer("Форма вже завершена або скасована", show_alert=True)
        return
    report = await _save_report(call.from_user.id, db, state, None)
    await state.clear()
    if report:
        await call.message.answer(f"✅ <b>Звіт №{report.id} подано.</b>\nКоманда АМП побачить його у веб-панелі.")
    await call.answer()
