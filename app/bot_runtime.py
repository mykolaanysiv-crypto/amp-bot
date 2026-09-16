from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, F
from aiogram.types import BotCommand, CallbackQuery

from .db import Database
from .handlers import admin, donations, events, feedback, participant, quests, start, surveys, v11
from .observability import log_extra
from .telegram_middleware import (
    DeletedAccountMiddleware, FSMNavigationMiddleware, LastActivityMiddleware, TemporaryBanMiddleware,
)

async def configure_bot_profile(bot: Bot) -> None:
    try:
        await bot.set_my_name(name="АМПасадори")
        await bot.set_my_short_description(short_description="Активності, XP, квести, волонтерство та можливості АМП.")
        await bot.set_my_description(description="Офіційний бот волонтерської групи «АМПасадори» Анисівського молодіжного простору: події, опитування, квести, досвід, винагороди та волонтерські задачі.")
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустити бота / реєстрація"),
            BotCommand(command="menu", description="Головне меню"),
            BotCommand(command="smart", description="Персональні можливості"),
            BotCommand(command="help", description="Довідка та QR"),
            BotCommand(command="myqr", description="Мій персональний QR-бейдж"),
            BotCommand(command="invite", description="Запросити друга"),
            BotCommand(command="cancel", description="Скасувати незавершену дію"),
        ])
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Не вдалося оновити публічний опис бота",
            extra=log_extra("BOT_PUBLIC_PROFILE_UPDATE_FAILED", exception_type=type(exc).__name__),
        )

def build_dispatcher(bot: Bot, db: Database, settings) -> Dispatcher:
    dp = Dispatcher()
    activity_tracker = LastActivityMiddleware()
    ban_guard = TemporaryBanMiddleware()
    deleted_guard = DeletedAccountMiddleware()
    navigation_guard = FSMNavigationMiddleware()
    dp.message.outer_middleware(navigation_guard)
    dp.message.outer_middleware(activity_tracker)
    dp.callback_query.outer_middleware(activity_tracker)
    dp.message.outer_middleware(ban_guard)
    dp.callback_query.outer_middleware(ban_guard)
    dp.message.outer_middleware(deleted_guard)
    dp.callback_query.outer_middleware(deleted_guard)
    # Navigation routers come before admin FSM handlers so menu buttons always
    # work even if an administrator left an unfinished creation wizard.
    dp.include_router(start.router)
    dp.include_router(v11.router)
    dp.include_router(donations.router)
    dp.include_router(feedback.router)
    dp.include_router(surveys.router)
    dp.include_router(participant.router)
    dp.include_router(events.router)
    dp.include_router(quests.router)
    dp.include_router(admin.router)

    async def _open_confirmed_navigation(call: CallbackQuery, target: str, state) -> None:
        # Reuse the normal participant handlers so a confirmed transition opens
        # the destination immediately instead of asking the user to tap twice.
        msg = call.message.model_copy(update={"from_user": call.from_user, "text": target})
        mapping = {
            "🏠 Головна": lambda: participant.overview(msg, db),
            "🏠 Огляд": lambda: participant.overview(msg, db),
            "🚀 Долучитися": lambda: participant.join_hub(msg, db),
            "☰ Ще": lambda: participant.more_hub(msg, db),
            "👤 Мій профіль": lambda: participant.profile(msg, db),
            "📈 Сезон": lambda: v11.season_profile(msg, db),
            "📅 Події": lambda: events.list_events(msg, db),
            "⚡ Активності": lambda: participant.activity_catalog(msg, db),
            "🎯 Квести": lambda: quests.list_quests(msg, db),
            "✅ Волонтерство": lambda: participant.tasks(msg, db),
            "✅ Волонтерські задачі": lambda: participant.tasks(msg, db),
            "🏅 Бейджі": lambda: participant.badges(msg, db),
            "🎁 Винагороди": lambda: participant.rewards(msg, db),
            "🎫 QR-бейдж": lambda: v11.my_qr(msg, db, state),
            "🎫 Мій QR-бейдж": lambda: v11.my_qr(msg, db, state),
            "🎫 Мій QR-код": lambda: v11.my_qr(msg, db, state),
            "🤝 Запросити друга": lambda: v11.invite_friend(msg, db, bot),
            "📊 Рейтинг": lambda: participant.leaderboard(msg, db),
            "🔥 Серії участі": lambda: participant.streaks_menu(msg, db, state),
            "🏁 Цілі & місії": lambda: participant.participant_goals(msg, db),
            "💡 Нова ідея": lambda: participant.idea_start(msg, state),
            "💡 Запропонувати ідею": lambda: participant.idea_start(msg, state),
            "🌍 Можливості": lambda: participant.opportunities(msg, db),
            "📰 Можливості": lambda: participant.opportunities(msg, db),
            "🆘 Звернення": lambda: participant.request_menu(msg, state),
            "📋 Опитування": lambda: surveys.surveys_menu(msg, db, state),
            "📜 Правила": lambda: participant.rules(msg),
            "🛠 Адмін-панель": lambda: admin.admin_panel(msg, db),
        }
        action = mapping.get(target)
        if action:
            await action()
        else:
            await call.message.answer(f"✅ Перехід до «{target}» підтверджено.")

    @dp.callback_query(F.data.in_({"fsmnav:yes", "fsmnav:no"}))
    async def confirm_fsm_navigation(call: CallbackQuery, state) -> None:
        data = await state.get_data()
        target = str(data.get("_pending_navigation") or "")
        if call.data == "fsmnav:no":
            data.pop("_pending_navigation", None)
            await state.set_data(data)
            await call.answer("Продовжуємо заповнення")
            try:
                await call.message.edit_text("↩️ Добре, продовжуємо заповнення поточної форми.")
            except Exception as exc:
                logging.getLogger("amp.navigation").debug(
                    "Не вдалося відредагувати повідомлення FSM navigation",
                    extra=log_extra("TG_FSM_NAV_EDIT_FAILED", tg_id=call.from_user.id, action="stay", exception_type=type(exc).__name__),
                )
            return
        await state.clear()
        await call.answer("Перехід підтверджено")
        try:
            await call.message.edit_text(f"✅ Перехід до «{target}» підтверджено.")
        except Exception as exc:
            logging.getLogger("amp.navigation").debug(
                "Не вдалося відредагувати повідомлення FSM navigation",
                extra=log_extra("TG_FSM_NAV_EDIT_FAILED", tg_id=call.from_user.id, action="confirm", target=target, exception_type=type(exc).__name__),
            )
        if target:
            await _open_confirmed_navigation(call, target, state)

    @dp.callback_query(F.data.startswith("ux:"))
    async def participant_ux_navigation(call: CallbackQuery, state) -> None:
        """Second-level participant navigation for the compact v1.10.0 menu."""
        action = str(call.data or "")
        msg = call.message.model_copy(update={"from_user": call.from_user, "text": ""})
        await state.clear()
        mapping = {
            "ux:join:events": lambda: events.list_events(msg, db),
            "ux:join:quests": lambda: quests.list_quests(msg, db),
            "ux:join:volunteer": lambda: participant.tasks(msg, db),
            "ux:join:activities": lambda: participant.activity_catalog(msg, db),
            "ux:join:ideas": lambda: participant.idea_start(msg, state),
            "ux:join:surveys": lambda: surveys.surveys_menu(msg, db, state),
            "ux:mine:profile": lambda: participant.profile(msg, db),
            "ux:mine:xp": lambda: participant.xp_history(msg, db),
            "ux:mine:league": lambda: v11.season_profile(msg, db),
            "ux:mine:streaks": lambda: participant.streaks_menu(msg, db, state),
            "ux:mine:goals": lambda: participant.participant_goals(msg, db),
            "ux:mine:badges": lambda: participant.badges(msg, db),
            "ux:mine:rewards": lambda: participant.rewards(msg, db),
            "ux:mine:invite": lambda: v11.invite_friend(msg, db, bot),
            "ux:more:requests": lambda: participant.request_menu(msg, state),
            "ux:more:rules": lambda: participant.rules(msg),
            "ux:more:help": lambda: start.help_command(msg),
        }
        if action == "ux:mine:seasons":
            await v11.season_history(call, db)
            return
        fn = mapping.get(action)
        if not fn:
            await call.answer("Розділ недоступний", show_alert=True)
            return
        await call.answer()
        await fn()


    @dp.callback_query(F.data == "noop")
    async def noop(call: CallbackQuery) -> None:
        await call.answer()
    return dp
