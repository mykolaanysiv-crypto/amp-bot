from ..time_utils import clock
from .admin_common import *  # noqa: F401,F403

@router.callback_query(F.data == "admin:create_quest")
async def quest_create_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminQuestState.title)
    await call.message.answer("🎯 Назва квесту?")
    await call.answer()


@router.message(AdminQuestState.title)
async def q_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminQuestState.description)
    await message.answer("Опиши умови квесту.")


@router.message(AdminQuestState.description)
async def q_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminQuestState.xp_reward)
    await message.answer("Нагорода XP? Для індивідуального квесту допустимо 10–35 XP.")


@router.message(AdminQuestState.xp_reward)
async def q_xp(message: Message, state: FSMContext) -> None:
    try:
        xp = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть ціле число.")
        return
    xp = normalize_quest_xp(xp, "individual")
    await state.update_data(xp_reward=xp)
    await state.set_state(AdminQuestState.deadline_day)
    await message.answer("📅 День дедлайну квесту (1–31) або слово <b>немає</b>, якщо дедлайн не потрібен.")


async def _finish_tg_quest(message: Message, state: FSMContext, db: Database, ends: datetime | None) -> None:
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            return
        quest=Quest(title=data["title"], description=data["description"], xp_reward=data["xp_reward"], ends_at=ends, created_by=admin.id)
        session.add(quest); await session.flush()
        await _queue_new_entity_notice(session,f"🎯 <b>Новий квест</b>\n\n<b>{quest.title}</b>\n⚡ {quest.xp_reward} XP\n\nВідкрий «🎯 Квести» у боті, щоб долучитися.","quest_created",f"quest_created:{quest.id}")
        await session.commit()
    await state.clear()
    text = "✅ Квест створено."
    if ends:
        text += f"\n📅 Дедлайн: {ends.strftime('%d.%m.%Y')} о {ends.strftime('%H:%M')}"
    await message.answer(text)


@router.message(AdminQuestState.deadline_day)
async def q_deadline_day(message: Message, state: FSMContext, db: Database) -> None:
    raw = (message.text or "").strip().lower()
    if raw == "немає":
        await _finish_tg_quest(message, state, db, None)
        return
    try:
        day = int(raw)
        if not 1 <= day <= 31:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть день числом від 1 до 31 або «немає».")
        return
    await state.update_data(deadline_day=day)
    await state.set_state(AdminQuestState.deadline_month)
    await message.answer("📅 Місяць дедлайну числом від 1 до 12.")


@router.message(AdminQuestState.deadline_month)
async def q_deadline_month(message: Message, state: FSMContext) -> None:
    try:
        month = int((message.text or "").strip())
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть місяць числом від 1 до 12.")
        return
    await state.update_data(deadline_month=month)
    await state.set_state(AdminQuestState.deadline_year)
    await message.answer("📅 Рік дедлайну, наприклад <b>2026</b>.")


@router.message(AdminQuestState.deadline_year)
async def q_deadline_year(message: Message, state: FSMContext) -> None:
    try:
        year = int((message.text or "").strip())
        if not 2026 <= year <= 2100:
            raise ValueError
    except ValueError:
        await message.answer("Вкажіть рік від 2026 до 2100.")
        return
    await state.update_data(deadline_year=year)
    await state.set_state(AdminQuestState.deadline_time)
    await message.answer("🕐 Час дедлайну у форматі <b>ГГ:ХХ</b>, наприклад 18:00.")


@router.message(AdminQuestState.deadline_time)
async def q_deadline_time(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "quests.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip()
    data = await state.get_data()
    try:
        hour, minute = [int(x) for x in raw.split(":", 1)]
        ends = datetime(int(data["deadline_year"]), int(data["deadline_month"]), int(data["deadline_day"]), hour, minute)
    except Exception:
        await message.answer("Некоректна дата або час. Введіть час у форматі ГГ:ХХ, наприклад 18:00.")
        return
    await _finish_tg_quest(message, state, db, ends)


@router.callback_query(F.data == "admin:quest_approvals")
async def quest_approvals(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        rows = (
            await session.execute(
                select(QuestParticipation, User, Quest)
                .join(User, User.id == QuestParticipation.user_id)
                .join(Quest, Quest.id == QuestParticipation.quest_id)
                .where(QuestParticipation.status == "completed")
                .order_by(QuestParticipation.completed_at)
            )
        ).all()
        if not rows:
            await call.message.answer("🎯 Немає квестів на підтвердженні.")
        for part, user, quest in rows[:30]:
            await call.message.answer(
                f"🎯 <b>{quest.title}</b>\n👤 {user.full_name}\n⚡ {quest.xp_reward} XP",
                reply_markup=_single_button("✅ Підтвердити", f"admin:approve_quest:{part.id}"),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:approve_quest:"))
async def approve_quest(call: CallbackQuery, db: Database, bot: Bot) -> None:
    part_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        part = await session.get(QuestParticipation, part_id)
        if not admin or not part or part.status != "completed":
            await call.answer("Неактуально", show_alert=True)
            return
        user = await session.get(User, part.user_id)
        quest = await session.get(Quest, part.quest_id)
        if not user or not quest:
            return
        quest.xp_reward = normalize_quest_xp(quest.xp_reward, quest.quest_type)
        total, level, leveled = await add_xp(session, user, quest.xp_reward, f"Квест «{quest.title}»", category="quest", created_by=admin.id)
        part.status = "approved"
        part.approved_at = clock.storage_utc()
        await evaluate_automatic_badges(session, user)
        text = f"🏆 Квест <b>{quest.title}</b> підтверджено!\n+{quest.xp_reward} XP\nВсього: {total} XP"
        if leveled:
            text += f"\n🎉 Новий рівень: <b>{level}</b>"
        await _queue_user_notice(session, user, text, source="xp_achievement", title="Квест підтверджено", entity_type="quest", entity_id=quest.id, dedupe_key=f"quest_approved:{quest.id}:{user.id}")
        await session.commit()
        await call.answer("Підтверджено")


@router.callback_query(F.data == "admin:award_badge")
async def badge_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminBadgeAwardState.user_id)
    await call.message.answer("🏅 Вкажіть номер учасника (число).")
    await call.answer()


@router.message(AdminBadgeAwardState.user_id)
async def badge_user(message: Message, state: FSMContext, db: Database) -> None:
    try:
        user_id = int((message.text or "").replace("АМП-", "").replace("AMP-", "").lstrip("0") or "0")
    except ValueError:
        await message.answer("Некоректний номер.")
        return
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        badges = (await session.scalars(select(Badge).where(Badge.active == True).order_by(Badge.id))).all()  # noqa: E712
        if not user:
            await message.answer("Учасника не знайдено.")
            return
        if not badges:
            await message.answer("Немає бейджів у довіднику.")
            await state.clear()
            return
        await state.update_data(user_id=user_id)
        await state.set_state(AdminBadgeAwardState.badge_id)
        text = "Оберіть номер бейджа:\n" + "\n".join(f"<code>{b.id}</code> — {b.icon} {b.name}" for b in badges)
        await message.answer(text)


@router.message(AdminBadgeAwardState.badge_id)
async def badge_finish(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    if not await _require_permission(message, db, "gamification.manage"):
        await state.clear()
        return
    try:
        badge_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть номер бейджа.")
        return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        user = await session.get(User, data["user_id"])
        badge = await session.get(Badge, badge_id)
        if not admin or not user or not badge:
            await message.answer("Не знайдено.")
            await state.clear()
            return
        existing = await session.scalar(select(UserBadge).where(UserBadge.user_id == user.id, UserBadge.badge_id == badge.id))
        if existing:
            await message.answer("Цей бейдж уже є в учасника.")
            await state.clear()
            return
        session.add(UserBadge(user_id=user.id, badge_id=badge.id, awarded_by=admin.id))
        await _queue_user_notice(session, user, f"🏅 Новий бейдж!\n{badge.icon} <b>{badge.name}</b>\n{badge.description}", source="badge", title="Новий бейдж", entity_type="badge", entity_id=badge.id, dedupe_key=f"manual_badge:{badge.id}:{user.id}")
        await session.commit()
        await message.answer(f"✅ Бейдж {badge.icon} {badge.name} видано {user.full_name}.")
    await state.clear()


@router.callback_query(F.data == "admin:create_reward")
async def reward_start(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    async with db.session_factory() as session:
        if not await _admin(session, call.from_user.id):
            await call.answer("Недостатньо прав для цієї дії", show_alert=True)
            return
    if not await _require_admin(call, db):
        return
    await state.set_state(AdminRewardState.title)
    await call.message.answer("🎁 Назва винагороди?")
    await call.answer()


@router.message(AdminRewardState.title)
async def reward_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or "").strip())
    await state.set_state(AdminRewardState.description)
    await message.answer("Опис винагороди?")


@router.message(AdminRewardState.description)
async def reward_desc(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AdminRewardState.min_xp)
    await message.answer("Мінімальний XP для доступу?")


@router.message(AdminRewardState.min_xp)
async def reward_xp(message: Message, state: FSMContext) -> None:
    try:
        min_xp = int((message.text or "").strip())
    except ValueError:
        await message.answer("Вкажіть число.")
        return
    await state.update_data(min_xp=min_xp)
    await state.set_state(AdminRewardState.stock)
    await message.answer("Кількість у наявності або <b>безліміт</b>.")


@router.message(AdminRewardState.stock)
async def reward_finish(message: Message, state: FSMContext, db: Database) -> None:
    if not await _require_permission(message, db, "gamification.manage"):
        await state.clear()
        return
    raw = (message.text or "").strip().lower()
    stock = None
    if raw != "безліміт":
        try:
            stock = int(raw)
        except ValueError:
            await message.answer("Вкажіть число або «безліміт».")
            return
    data = await state.get_data()
    async with db.session_factory() as session:
        admin = await _admin(session, message.from_user.id)
        if not admin:
            return
        session.add(Reward(title=data["title"], description=data["description"], min_xp=data["min_xp"], stock=stock))
        await session.commit()
    await state.clear()
    await message.answer("✅ Винагороду додано.")


@router.callback_query(F.data == "admin:reward_claims")
async def reward_claims(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        if not admin:
            return
        rows = (
            await session.execute(
                select(RewardClaim, User, Reward)
                .join(User, User.id == RewardClaim.user_id)
                .join(Reward, Reward.id == RewardClaim.reward_id)
                .where(RewardClaim.status == "requested")
            )
        ).all()
        if not rows:
            await call.message.answer("🎁 Нових заявок немає.")
        for claim, user, reward in rows:
            await call.message.answer(
                f"🎁 <b>{reward.title}</b>\n👤 {user.full_name}",
                reply_markup=_two_buttons("✅ Видано", f"admin:fulfill_reward:{claim.id}", "↩ Відхилити", f"admin:reject_reward:{claim.id}"),
            )
        await call.answer()


@router.callback_query(F.data.startswith("admin:fulfill_reward:"))
async def fulfill_reward(call: CallbackQuery, db: Database, bot: Bot) -> None:
    claim_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        claim = await session.get(RewardClaim, claim_id)
        if not admin or not claim or claim.status != "requested":
            await call.answer("Неактуально", show_alert=True)
            return
        reward = await session.get(Reward, claim.reward_id)
        user = await session.get(User, claim.user_id)
        claim.status = "fulfilled"
        claim.fulfilled_at = clock.storage_utc()
        if user and reward:
            await _queue_user_notice(session, user, f"🎁 Винагороду <b>{reward.title}</b> позначено як видану. Дякуємо за активність!", source="reward", title="Винагороду видано", entity_type="reward_claim", entity_id=claim.id, dedupe_key=f"reward_fulfilled:{claim.id}")
        await session.commit()
        await call.answer("Видано")


@router.callback_query(F.data.startswith("admin:reject_reward:"))
async def reject_reward(call: CallbackQuery, db: Database, bot: Bot) -> None:
    claim_id = int(call.data.split(":")[2])
    async with db.session_factory() as session:
        admin = await _admin(session, call.from_user.id)
        claim = await session.get(RewardClaim, claim_id)
        if not admin or not claim or claim.status != "requested":
            await call.answer("Неактуально", show_alert=True)
            return
        reward = await session.get(Reward, claim.reward_id)
        user = await session.get(User, claim.user_id)
        claim.status = "rejected"
        if user:
            user.wallet_xp += int(claim.xp_spent or 0)
        if reward and reward.stock is not None:
            reward.stock += 1
        if user and reward:
            await _queue_user_notice(session, user, f"↩ Заявку на <b>{reward.title}</b> відхилено. {claim.xp_spent} XP повернуто у гаманець.", source="reward", title="Заявку на винагороду відхилено", entity_type="reward_claim", entity_id=claim.id, dedupe_key=f"reward_rejected:{claim.id}")
        await session.commit()
        await call.answer("XP повернуто")


