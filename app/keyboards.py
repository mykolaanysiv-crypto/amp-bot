from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .models import UserRole
from .permissions import effective_permissions

ADMIN_ROLES = {UserRole.ADMIN.value, UserRole.SUPERADMIN.value, UserRole.COORDINATOR.value}


def compact_button_text(text: str, max_chars: int = 28) -> str:
    """Shorten utility/admin button labels without trailing dots/ellipsis."""
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0].rstrip()
    return cut.rstrip(" .…") or text[:max_chars].rstrip(" .…")


def entity_button_text(text: str) -> str:
    """Keep participant-facing entity names complete; only normalize whitespace.

    Telegram controls the visual width of inline buttons, so we intentionally do
    not cut titles in code. This prevents names of events, quests, activities,
    volunteer tasks and opportunities from being silently shortened.
    """
    return " ".join((text or "").split()).strip()

MAIN_MENU_TEXTS = {
    # v1.10.0 compact participant navigation
    "🏠 Головна", "🚀 Долучитися", "🌍 Можливості", "💙 Підтримати", "👤 Мій профіль", "🎫 QR-бейдж", "☰ Ще",
    # Legacy labels remain recognized so unfinished FSM flows and old Telegram keyboards are safe.
    "🏠 Огляд", "📈 Сезон", "📅 Події", "⚡ Активності", "🎯 Квести",
    "✅ Волонтерство", "✅ Волонтерські задачі", "🏅 Бейджі", "🎁 Винагороди", "🎫 Мій QR-бейдж", "🎫 Мій QR-код",
    "🤝 Запросити друга", "📊 Рейтинг", "💡 Нова ідея", "💡 Запропонувати ідею", "📰 Можливості",
    "🏁 Цілі & місії", "🆘 Звернення", "📋 Опитування", "🔥 Серії участі", "📜 Правила", "🛠 Адмін-панель",
}


def main_menu(role: str, permissions_raw: str | None = None) -> ReplyKeyboardMarkup:
    """v1.11.0 participant-first layout in the requested left-to-right order.

    The admin entry is shown not only for legacy staff roles, but also for a
    profile that has an explicit granular staff permission set.
    """
    rows = [
        [KeyboardButton(text="🏠 Головна"), KeyboardButton(text="👤 Мій профіль")],
        [KeyboardButton(text="🚀 Долучитися"), KeyboardButton(text="🌍 Можливості")],
        [KeyboardButton(text="🎫 QR-бейдж"), KeyboardButton(text="🤝 Запросити друга")],
        [KeyboardButton(text="💙 Підтримати"), KeyboardButton(text="🆘 Звернення")],
        [KeyboardButton(text="☰ Ще")],
    ]
    if role in ADMIN_ROLES or bool(effective_permissions(role, permissions_raw)):
        rows.append([KeyboardButton(text="🛠 Адмін-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def join_hub_keyboard() -> InlineKeyboardMarkup:
    return _admin_inline_menu([
        ("📅 Події", "ux:join:events"),
        ("🎯 Квести", "ux:join:quests"),
        ("✅ Волонтерство", "ux:join:volunteer"),
        ("⚡ Активності", "ux:join:activities"),
        ("💡 Ідеї", "ux:join:ideas"),
        ("📋 Опитування", "ux:join:surveys"),
    ], columns=2)


def profile_hub_keyboard() -> InlineKeyboardMarkup:
    return _admin_inline_menu([
        ("👤 Профіль", "ux:mine:profile"),
        ("⚡ XP", "ux:mine:xp"),
        ("🏆 Ліга", "ux:mine:league"),
        ("🔥 Серії", "ux:mine:streaks"),
        ("🏁 Цілі", "ux:mine:goals"),
        ("🏅 Бейджі", "ux:mine:badges"),
        ("🎁 Винагороди", "ux:mine:rewards"),
        ("🕰 Історія сезонів", "ux:mine:seasons"),
        ("⚙️ Інтереси", "opp_prefs"),
    ], columns=2)


def more_hub_keyboard() -> InlineKeyboardMarkup:
    return _admin_inline_menu([
        ("📜 Правила", "ux:more:rules"),
        ("❓ Допомога", "ux:more:help"),
    ], columns=1)



def registration_phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def events_keyboard(events) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for event in events:
        b.button(text=entity_button_text(f"📅 {event.title}"), callback_data=f"event:{event.id}")
    b.adjust(1)
    return b.as_markup()


def event_detail_keyboard(event_id: int, registered: bool, share_url: str | None = None, registration_status: str | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    status = registration_status or ("registered" if registered else None)
    if status == "waitlisted":
        b.button(text="⏳ Ви у черзі", callback_data="noop")
        b.button(text="❌ Вийти з черги", callback_data=f"event_cancel:{event_id}")
    elif status == "reserved":
        b.button(text="🎟 Місце зарезервовано", callback_data="noop")
        b.button(text="✅ Підтвердити місце", callback_data=f"event_reserve_accept:{event_id}")
        b.button(text="❌ Відмовитися", callback_data=f"event_cancel:{event_id}")
    elif status in {"registered", "checked_in"}:
        b.button(text="✅ Ви зареєстровані", callback_data="noop")
        b.button(text="❌ Скасувати реєстрацію", callback_data=f"event_cancel:{event_id}")
    elif status == "attended":
        b.button(text="✅ Участь підтверджено", callback_data="noop")
    elif status == "no_show":
        b.button(text="🚫 Позначено «Не прийшов»", callback_data="noop")
    else:
        b.button(text="🙋 Долучитися", callback_data=f"event_join:{event_id}")
    if share_url:
        b.button(text="📤 Переслати другу", url=share_url)
    b.button(text="⬅️ Назад", callback_data="nav:events")
    b.adjust(1)
    return b.as_markup()


def event_waitlist_offer_keyboard(event_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏳ Стати в чергу", callback_data=f"event_waitlist:{event_id}")
    b.button(text="⬅️ Назад до події", callback_data=f"event:{event_id}")
    b.adjust(1)
    return b.as_markup()


def quests_keyboard(quests) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for quest in quests:
        prefix = "👥" if getattr(quest, "quest_type", "individual") == "team" else "🎯"
        b.button(text=entity_button_text(f"{prefix} {quest.title}"), callback_data=f"quest:{quest.id}")
    b.adjust(1)
    return b.as_markup()


def quest_detail_keyboard(quest_id: int, status: str | None, quest_type: str = "individual") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if status is None:
        b.button(text="🚀 Долучитися", callback_data=f"quest_join:{quest_id}")
    elif quest_type == "team" and status == "joined":
        b.button(text="👥 Ви в команді", callback_data="noop")
        b.button(text="❌ Скасувати участь", callback_data=f"quest_cancel_join:{quest_id}")
    elif status in {"joined", "returned"}:
        b.button(text="✅ Виконано", callback_data=f"quest_done:{quest_id}")
        b.button(text="❌ Скасувати участь", callback_data=f"quest_cancel_join:{quest_id}")
    elif status == "completed":
        b.button(text="⏳ Очікує перевірки", callback_data="noop")
        b.button(text="❌ Скасувати участь", callback_data=f"quest_cancel_join:{quest_id}")
    elif status == "approved":
        b.button(text="🏆 Виконано", callback_data="noop")
    b.button(text="⬅️ Назад", callback_data="nav:quests")
    b.adjust(1)
    return b.as_markup()


def rewards_keyboard(rewards) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for reward in rewards:
        b.button(text=entity_button_text(f"🎁 {reward.title} · {reward.min_xp} XP"), callback_data=f"reward:{reward.id}")
    b.adjust(1)
    return b.as_markup()


def tasks_keyboard(tasks) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for task in tasks:
        b.button(text=entity_button_text(f"✅ {task.title}"), callback_data=f"task:{task.id}")
    b.adjust(1)
    return b.as_markup()


def _admin_inline_menu(buttons: list[tuple[str, str]], *, columns: int = 1) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, cb in buttons:
        b.button(text=compact_button_text(text, max_chars=34), callback_data=cb)
    b.adjust(columns)
    return b.as_markup()


def admin_menu(role: str, permissions: set[str] | frozenset[str] | None = None) -> InlineKeyboardMarkup:
    """Granular top-level Telegram admin navigation (v1.10.2)."""
    perms = frozenset(permissions) if permissions is not None else effective_permissions(role, None)
    buttons: list[tuple[str, str]] = []
    if perms & {"events.create", "events.edit", "events.delete"}:
        buttons.append(("📅 Події", "admin:section:events"))
    if perms & {"quests.manage", "volunteer.manage", "activities.manage", "opportunities.manage"}:
        buttons.append(("🎯 Активності", "admin:section:activities"))
    if perms & {"xp.award", "gamification.manage"}:
        buttons.append(("🏆 XP та винагороди", "admin:section:gamification"))
    if perms & {"participants.approve", "moderation.manage"}:
        buttons.append(("👥 Учасники", "admin:section:people"))
    if perms & {"analytics.view", "reports.basic_export", "broadcast.send"}:
        buttons.append(("📊 Аналітика й комунікація", "admin:section:data"))
    buttons.append(("🌐 Вебпанель", "admin:web"))
    return _admin_inline_menu(buttons)


def admin_section_menu(role: str, section: str, permissions: set[str] | frozenset[str] | None = None) -> InlineKeyboardMarkup:
    perms = frozenset(permissions) if permissions is not None else effective_permissions(role, None)
    buttons: list[tuple[str, str]] = []
    if section == "events":
        if "events.create" in perms: buttons.append(("📅 Створити подію", "admin:create_event"))
        if "events.edit" in perms:
            buttons.extend([
                ("✅ Відвідування", "admin:attendance"),
                ("📷 QR-сканер", "admin:event_scanner"),
                ("🔳 QR відмітки", "admin:event_qr"),
                ("🔗 Посилання на подію", "admin:event_share_link"),
            ])
    elif section == "activities":
        if "quests.manage" in perms: buttons.extend([("🎯 Створити квест", "admin:create_quest"), ("🏆 Перевірка квестів", "admin:quest_approvals")])
        if "activities.manage" in perms: buttons.append(("⚡ Заявки активностей", "admin:activity_apps"))
        if "volunteer.manage" in perms: buttons.extend([("🧰 Додати задачу", "admin:create_task"), ("✅ Перевірка задач", "admin:task_approvals")])
        if "opportunities.manage" in perms: buttons.append(("📰 Додати можливість", "admin:create_opportunity"))
    elif section == "gamification":
        if "xp.award" in perms: buttons.append(("⚡ Нарахувати XP", "admin:add_xp"))
        if "gamification.manage" in perms:
            buttons.extend([("🏅 Видати бейдж", "admin:award_badge"), ("🎁 Додати винагороду", "admin:create_reward"), ("🎁 Заявки винагород", "admin:reward_claims")])
    elif section == "people":
        if "participants.approve" in perms: buttons.append(("👥 Нові учасники", "admin:pending"))
        if "moderation.manage" in perms: buttons.append(("🛡 Модерація", "admin:moderation"))
    elif section == "data":
        if "analytics.view" in perms: buttons.append(("📊 Аналітика", "admin:analytics"))
        if "reports.basic_export" in perms: buttons.append(("📈 Експорт Excel", "admin:export"))
        if "broadcast.send" in perms: buttons.append(("📣 Розсилки", "admin:broadcast"))
    buttons.append(("⬅️ Головне меню", "admin:menu"))
    return _admin_inline_menu(buttons)


def pending_user_keyboard(user_id: int, needs_consent: bool, permissions: set[str] | frozenset[str] | None = None) -> InlineKeyboardMarkup:
    perms = frozenset(permissions or [])
    b = InlineKeyboardBuilder()
    if "participants.approve" in perms:
        if needs_consent:
            b.button(text="👪 Згода батьків", callback_data=f"admin:consent:{user_id}")
        b.button(text="✅ Активувати", callback_data=f"admin:approve:{user_id}")
    if "moderation.manage" in perms:
        b.button(text="⛔ Заблокувати", callback_data=f"admin:block:{user_id}")
    b.adjust(1)
    return b.as_markup()
