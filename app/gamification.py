from __future__ import annotations

from dataclasses import dataclass

LEVELS = [
    (0, "🚀 Новачок"),
    (50, "🌱 Учасник"),
    (150, "⚡ Активіст"),
    (300, "🔥 АМПасадор"),
    (500, "⭐ ПроАМПасадор"),
    (800, "🛰️ Лідер АМП"),
    (1200, "🏆 Легенда АМП"),
]

# Збалансований каталог рекомендованих нарахувань.
# Це орієнтири для адміністратора; автоматичні події/квести/задачі додатково
# мають технічні межі, щоб одна активність не ламала сезонний рейтинг.
DEFAULT_XP_CATALOG = {
    "event_visit": (10, "Відвідування звичайної події АМП"),
    "training": (15, "Тренінг / майстер-клас / навчальна активність"),
    "cleanup": (20, "Толока / благоустрій"),
    "event_volunteer": (20, "Волонтерство під час події"),
    "event_preparation": (15, "Підготовка події"),
    "content": (10, "Корисний контент для АМП"),
    "design": (15, "Дизайн / афіша / візуальний матеріал"),
    "idea_approved": (10, "Ідея схвалена до реалізації"),
    "idea_implemented": (25, "Ідею реально реалізовано"),
    "own_event": (35, "Самостійно організована активність"),
    "trainer": (30, "Проведення тренінгу / майстер-класу"),
    "event_coordinator": (30, "Координація події"),
    "representation": (15, "Представлення АМП на зовнішній активності"),
    "partner": (25, "Партнер реально долучився до співпраці"),
    "resource": (20, "Залучено корисний ресурс / обладнання"),
    "sponsor": (30, "Залучено підтверджену спонсорську підтримку"),
    "youth_policy": (15, "Участь у консультації / молодіжній політиці"),
    "mentoring": (15, "Наставництво / допомога новому учаснику"),
    "special": (40, "Особливий підтверджений внесок (максимум за одну дію)"),
}


# Активності, на які учасник подає заявку. Вони не замінюють автоматичні
# нарахування за QR-події, квести, волонтерські задачі чи рефералів.
CLAIMABLE_ACTIVITY_CATALOG = [
    {"code":"event_preparation","title":"Підготовка події","category":"events","xp":15,"hours":1.0,"description":"Допомога з підготовкою простору, матеріалів, реєстрації або логістики перед подією.","instructions":"У заявці коротко опиши, до якої події та яку саме частину підготовки береш на себе."},
    {"code":"event_volunteer","title":"Волонтерство під час події","category":"events","xp":20,"hours":2.0,"description":"Реєстрація учасників, навігація, допомога ведучим, технічна або організаційна підтримка.","instructions":"Вкажи подію та роль, яку готовий/а виконувати."},
    {"code":"cleanup","title":"Толока / благоустрій","category":"space","xp":20,"hours":2.0,"description":"Прибирання, облаштування, дрібні роботи та покращення простору АМП.","instructions":"Опиши, що саме плануєш зробити та коли."},
    {"code":"content","title":"Контент для АМП","category":"media","xp":10,"hours":0.5,"description":"Корисний фото-, відео- або текстовий матеріал для комунікацій АМП.","instructions":"Опиши формат контенту, тему та де він буде використаний."},
    {"code":"design","title":"Дизайн / афіша / візуал","category":"media","xp":15,"hours":1.0,"description":"Створення афіші, банера, шаблону, картки або іншого візуального матеріалу.","instructions":"Вкажи, який макет плануєш створити та для якої активності."},
    {"code":"idea_implemented","title":"Реалізація схваленої ідеї","category":"initiatives","xp":25,"hours":2.0,"description":"Практична реалізація власної або командної ідеї, яку попередньо схвалила команда АМП.","instructions":"Вкажи назву схваленої ідеї та свій план реалізації."},
    {"code":"own_event","title":"Власна активність / подія","category":"events","xp":35,"hours":3.0,"description":"Самостійна підготовка та проведення погодженої активності для учасників АМП.","instructions":"Опиши тему, формат, аудиторію, орієнтовну дату та що потрібно для проведення."},
    {"code":"trainer","title":"Проведення тренінгу / майстер-класу","category":"education","xp":30,"hours":2.0,"description":"Проведення навчальної активності для молоді АМП.","instructions":"Опиши тему, тривалість, цільову аудиторію та очікуваний результат."},
    {"code":"event_coordinator","title":"Координація події","category":"events","xp":30,"hours":3.0,"description":"Відповідальність за організацію окремої події або значного її блоку.","instructions":"Опиши подію та за який блок готовий/а відповідати."},
    {"code":"representation","title":"Представлення АМП назовні","category":"community","xp":15,"hours":1.0,"description":"Представлення АМП на зустрічі, навчанні, форумі, консультації або партнерській події.","instructions":"Вкажи захід і мету представлення АМП."},
    {"code":"partner","title":"Залучення партнера","category":"partnerships","xp":25,"hours":1.0,"description":"Пошук і доведення до реальної співпраці нового партнера для АМП.","instructions":"Опиши потенційного партнера та яку співпрацю пропонуєш."},
    {"code":"resource","title":"Залучення ресурсу / обладнання","category":"partnerships","xp":20,"hours":1.0,"description":"Залучення корисного обладнання, матеріалів, послуг або іншого ресурсу для АМП.","instructions":"Опиши ресурс, джерело та для чого він потрібен."},
    {"code":"sponsor","title":"Залучення спонсорської підтримки","category":"partnerships","xp":30,"hours":1.0,"description":"Залучення підтвердженої матеріальної або фінансової підтримки для погодженої потреби АМП.","instructions":"Опиши потенційного спонсора та ціль підтримки. Не давай обіцянок від імені АМП без погодження."},
    {"code":"youth_policy","title":"Участь у молодіжній політиці","category":"youth_policy","xp":15,"hours":1.0,"description":"Участь у консультаціях, опитуваннях, робочих групах або адвокаційних активностях молоді.","instructions":"Вкажи формат участі та очікуваний внесок."},
    {"code":"mentoring","title":"Наставництво новому учаснику","category":"community","xp":15,"hours":1.0,"description":"Допомога новому учаснику адаптуватися, розібратися з АМП та долучитися до активностей.","instructions":"Опиши, кому й у чому саме плануєш допомогти."},
]

AUTOMATIC_XP_GUIDE = [
    ("QR-відвідування події", "5–25 XP", "Нараховується після підтвердження присутності адміністратором; типовий захід — 10 XP."),
    ("Індивідуальний квест", "10–35 XP", "Після виконання та підтвердження квесту."),
    ("Командний квест", "5–20 XP", "Кожному активному учаснику команди після досягнення спільної цілі."),
    ("Волонтерська задача", "10–40 XP", "Після підтвердження виконання задачі."),
    ("Запрошення друга", "10→1 XP", "1-й успішний реферал кварталу — 10 XP, 2-й — 9 XP ... 10-й і наступні — 1 XP."),
]


@dataclass(frozen=True, slots=True)
class XPBounds:
    default: int
    minimum: int
    maximum: int
    note: str


XP_BOUNDS = {
    "event": XPBounds(10, 5, 25, "Події: 5–25 XP; типовий захід — 10 XP, навчальний/волонтерський — 15–20 XP."),
    "quest_individual": XPBounds(20, 10, 35, "Індивідуальний квест: 10–35 XP."),
    "quest_team": XPBounds(10, 5, 20, "Командний квест: 5–20 XP кожному учаснику."),
    "task": XPBounds(20, 10, 40, "Волонтерська задача: 10–40 XP залежно від складності та часу."),
    "manual_positive": XPBounds(15, 1, 40, "Ручний бонус: до 40 XP за одну підтверджену дію."),
}


def clamp_xp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def normalize_event_xp(value: int) -> int:
    b = XP_BOUNDS["event"]
    return clamp_xp(value, b.minimum, b.maximum)


def normalize_quest_xp(value: int, quest_type: str) -> int:
    key = "quest_team" if quest_type == "team" else "quest_individual"
    b = XP_BOUNDS[key]
    return clamp_xp(value, b.minimum, b.maximum)


def normalize_task_xp(value: int, hours: float = 0) -> int:
    """Clamp volunteer-task XP and provide a reasonable floor for long tasks.

    Hours do not automatically generate XP; they only prevent a long task from
    accidentally being created with an implausibly low reward.
    """
    b = XP_BOUNDS["task"]
    value = clamp_xp(value, b.minimum, b.maximum)
    if hours >= 4:
        value = max(value, 30)
    elif hours >= 2:
        value = max(value, 20)
    return value


def normalize_manual_xp(value: int) -> int:
    """Manual awards are intentionally conservative.

    Positive adjustments are limited to +40 XP. Negative corrections may be
    larger because they are used to fix erroneous historic transactions.
    """
    value = int(value)
    if value >= 0:
        return min(value, XP_BOUNDS["manual_positive"].maximum)
    return max(value, -500)


def referral_reward_for_position(position: int) -> int:
    """Quarterly referral reward: 1st=10, 2nd=9 ... 10th=1, later=1."""
    position = max(1, int(position))
    return max(1, 11 - position)


def get_level(xp: int) -> tuple[str, int | None]:
    current = LEVELS[0][1]
    next_threshold: int | None = None
    for i, (threshold, name) in enumerate(LEVELS):
        if xp >= threshold:
            current = name
            next_threshold = LEVELS[i + 1][0] if i + 1 < len(LEVELS) else None
        else:
            break
    return current, next_threshold


def progress_text(xp: int) -> str:
    level, next_threshold = get_level(xp)
    if next_threshold is None:
        return f"{level}\n📈 Прогрес рівня: {xp} XP\n🏆 Максимальний рівень досягнуто 🎉"
    return (
        f"{level}\n"
        f"📈 Прогрес рівня: <b>{xp} / {next_threshold} XP</b>\n"
        f"⚡ До наступного рівня залишилось: <b>{next_threshold - xp} XP</b>"
    )
