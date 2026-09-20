from __future__ import annotations

from html import escape
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from app.config import Settings
from app.db import Database
from app.media import load_file_bytes
from app.model_domains import DonationJarState, DonationReport, SupportPageView, User
from app.domain_services import get_user_by_tg
from app.observability import log_extra

router = Router()


def _money(kop: int | None) -> str:
    return f"{(int(kop or 0) / 100):,.2f}".replace(",", " ").replace(".00", "") + " грн"


def _support_keyboard(settings: Settings):
    b = InlineKeyboardBuilder()
    b.button(text="💙 Відкрити банку Monobank", url=settings.donation_jar_url)
    b.button(text="📄 Звітність", callback_data="donations:reports")
    b.adjust(1)
    return b.as_markup()


@router.message(F.text == "💙 Підтримати")
async def support_page(message: Message, db: Database, settings: Settings) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        session.add(SupportPageView(user_id=user.id if user else None, tg_id=message.from_user.id))
        state = await session.get(DonationJarState, 1)
        await session.commit()

    progress = ""
    if state and int(state.goal_kop or 0) > 0:
        pct = min(100.0, max(0.0, int(state.balance_kop or 0) / int(state.goal_kop or 1) * 100))
        progress = f"\n\n📊 Зібрано: <b>{_money(state.balance_kop)}</b> із <b>{_money(state.goal_kop)}</b> · {pct:.1f}%"
    elif state and int(state.balance_kop or 0) > 0:
        progress = f"\n\n📊 На банці: <b>{_money(state.balance_kop)}</b>"

    amp_hint = ""
    if user:
        amp_hint = (
            f"\n\n⚡ <b>Бонус XP за донат:</b> 1 XP = 5 грн. "
            f"Щоб XP і донатні бейджі нарахувалися автоматично, додайте в коментар до переказу свій АМП-код: "
            f"<code>АМП-{user.id:04d}</code>.\n"
            "Якщо ви донатили раніше з АМП-кодом, система автоматично донарахує пропущений XP під час синхронізації."
        )

    await message.answer(
        "💙 <b>Підтримати АМП</b>\n\n"
        "Донати допомагають розвивати молодіжний простір, проводити активності та купувати необхідні матеріали. "
        "Переказати кошти можна через офіційну банку Monobank."
        f"{progress}{amp_hint}\n\n"
        "📄 У розділі «Звітність» публікуємо документи та інформацію про використання коштів.",
        reply_markup=_support_keyboard(settings),
    )


@router.callback_query(F.data == "donations:reports")
async def public_reports(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        rows = list((await session.scalars(
            select(DonationReport)
            .where(DonationReport.published == True)  # noqa: E712
            .order_by(DonationReport.spent_at.desc().nullslast(), DonationReport.created_at.desc())
            .limit(20)
        )).all())

    if not rows:
        await call.message.answer("📄 <b>Звітність про використання донатів</b>\n\nОпублікованих звітів поки немає.")
        await call.answer()
        return

    lines = ["📄 <b>Звітність про використання донатів</b>", ""]
    for row in rows:
        date_text = (row.spent_at or row.created_at).strftime("%d.%m.%Y")
        amount = f" · {_money(row.amount_spent_kop)}" if int(row.amount_spent_kop or 0) > 0 else ""
        lines.append(f"• <b>{escape(row.title)}</b> · {date_text}{amount}")
        if row.description:
            lines.append(f"  {escape(row.description[:300])}")
    await call.message.answer("\n".join(lines))

    for row in rows:
        if not row.document_path:
            continue
        raw = await load_file_bytes(db, row.document_path)
        if not raw:
            continue
        filename = row.document_name or f"zvit_{row.id}.pdf"
        try:
            await call.message.answer_document(
                BufferedInputFile(raw, filename=filename),
                caption=f"📄 <b>{escape(row.title)}</b>",
            )
        except Exception as exc:
            # The textual report remains available even if Telegram rejects a legacy file.
            logging.getLogger("amp.donations").warning(
                "Telegram rejected donation report document; text fallback remains available",
                extra=log_extra("TG_DONATION_REPORT_DOCUMENT_FAILED", report_id=row.id, tg_id=call.from_user.id, exception_type=type(exc).__name__),
            )
    await call.answer()
