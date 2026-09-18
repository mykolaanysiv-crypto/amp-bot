from ..observability import log_extra
from ..time_utils import clock
from ..opportunity_utils import deadline_urgency, opportunity_sort_key
import logging

from .participant_common import (
    ActivityApplication, ActivityType, CallbackQuery, Database, F, Idea, InlineKeyboardBuilder, Message, Opportunity, RequestCase, UserStatus, VolunteerTask, VolunteerTaskParticipation, activity_status_label, content_view_stat, current_season, entity_button_text, escape, func, get_user_by_tg, idea_status_label, label, league_for_xp, league_leaderboard_rows, process_expired_content, record_content_view, request_status_label, router, season_leaderboard_rows, season_xp, select, telegram_photo_input
)

@router.message(F.text.in_({"✅ Волонтерство", "✅ Волонтерські задачі"}))
async def tasks(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        changed = await process_expired_content(session)
        if changed:
            await session.commit()
        user = await get_user_by_tg(session, message.from_user.id)
        if not user or user.status != UserStatus.ACTIVE.value:
            return
        now = clock.storage_utc()
        rows = (
            await session.scalars(
                select(VolunteerTask)
                .where(
                    VolunteerTask.status.in_(["open", "active", "postponed"]),
                    (VolunteerTask.deadline.is_(None)) | (VolunteerTask.deadline >= now),
                )
                .order_by(VolunteerTask.deadline.is_(None), VolunteerTask.deadline.asc(), VolunteerTask.id.desc())
            )
        ).all()
        mine = {
            p.task_id: p
            for p in (await session.scalars(
                select(VolunteerTaskParticipation)
                .where(VolunteerTaskParticipation.user_id == user.id)
            )).all()
        }
        visible = []
        for task in rows:
            count = await session.scalar(
                select(func.count(VolunteerTaskParticipation.id)).where(
                    VolunteerTaskParticipation.task_id == task.id,
                    VolunteerTaskParticipation.status != "cancelled",
                )
            ) or 0
            part = mine.get(task.id)
            if part or (task.status in {"open", "active", "postponed"} and count < max(1, int(task.max_participants or 1))):
                visible.append((task, part, int(count)))
        if not visible:
            await message.answer("✅ Доступних волонтерських задач зараз немає.")
            return
        b = InlineKeyboardBuilder()
        task_lines = []
        for idx, (task, part, count) in enumerate(visible, start=1):
            if part and part.status == "submitted":
                prefix = "⏳"
                state_text = "на перевірці"
            elif part and part.status == "approved":
                prefix = "✅"
                state_text = "підтверджено"
            elif part:
                prefix = "🟡"
                state_text = "ви долучилися"
            else:
                prefix = "🟢"
                state_text = "є місце"
            deadline = task.deadline.strftime("%d.%m.%Y %H:%M") if task.deadline else "без дедлайну"
            task_lines.append(
                f"<b>{idx}. {escape(task.title)}</b>\n{prefix} {state_text} • 👥 {count}/{max(1, int(task.max_participants or 1))} • 📆 {deadline}"
            )
            b.button(
                text=entity_button_text(f"{prefix} {task.title}"),
                callback_data=f"task:{task.id}",
            )
        b.adjust(1)
        await message.answer(
            "✅ <b>Волонтерські задачі</b>\n\n"
            "🟢 є місце • 🟡 ви долучилися • ⏳ на перевірці • ✅ підтверджено\n\n"
            + "\n\n".join(task_lines),
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data.regexp(r"^task:\d+$"))
async def task_detail(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        try:
            changed = await process_expired_content(session)
            if changed:
                await session.commit()
        except Exception as exc:
            await session.rollback()
            logging.getLogger("amp.volunteer_tasks").exception(
                "Lifecycle refresh failed while opening task %s", task_id,
                extra=log_extra("VOLUNTEER_TASK_LIFECYCLE_REFRESH_FAILED", entity_type="volunteer_task", entity_id=task_id, exception_type=type(exc).__name__),
            )
        user = await get_user_by_tg(session, call.from_user.id)
        task = await session.get(VolunteerTask, task_id)
        if not user or not task:
            await call.answer("Не знайдено", show_alert=True)
            return
        mine = await session.scalar(
            select(VolunteerTaskParticipation).where(
                VolunteerTaskParticipation.task_id == task.id,
                VolunteerTaskParticipation.user_id == user.id,
            )
        )
        await record_content_view(session, "volunteer_task", task.id, user=user)
        await session.flush()
        view_stat = await content_view_stat(session, "volunteer_task", task.id)
        count = await session.scalar(
            select(func.count(VolunteerTaskParticipation.id)).where(
                VolunteerTaskParticipation.task_id == task.id,
                VolunteerTaskParticipation.status != "cancelled",
            )
        ) or 0
        maximum = max(1, int(task.max_participants or 1))
        deadline = task.deadline.strftime("%d.%m.%Y") if task.deadline else "без дедлайну"
        b = InlineKeyboardBuilder()
        is_available = task.status in {"open", "active", "postponed"} and (task.deadline is None or task.deadline >= clock.local_wall())
        if is_available:
            if not mine and count < maximum:
                b.button(text="🙋 Долучитися", callback_data=f"task_claim:{task.id}")
            elif mine and mine.status in {"joined", "returned"}:
                b.button(text="✅ На перевірку", callback_data=f"task_done:{task.id}")
            elif mine and mine.status == "submitted":
                b.button(text="⏳ Очікує перевірки", callback_data="noop")
            elif mine and mine.status == "approved":
                b.button(text="🏆 Підтверджено", callback_data="noop")
            if mine and mine.status in {"joined", "returned", "submitted"}:
                b.button(text="❌ Скасувати участь", callback_data=f"task_cancel_join:{task.id}")
        b.button(text="⬅️ Назад", callback_data="nav:tasks")
        b.adjust(1)
        await session.commit()
        safe_title = escape(task.title or "Волонтерська задача")
        safe_description = escape(task.description or "Без додаткового опису.")
        text = (
            f"🧰 <b>{safe_title}</b>\n"
            f"📆 Дедлайн: {deadline}\n"
            f"👥 Учасники: <b>{count}/{maximum}</b>\n"
            f"⚡ {task.xp_reward} XP • ⏱ {task.hours_reward:g} год.\n"
            f"👁 Переглядів: <b>{view_stat['views']}</b>\n\n"
            f"{safe_description}"
        )
        if mine:
            status_names = {"joined":"Виконується", "returned":"Повернуто на доопрацювання", "submitted":"На перевірці", "approved":"Підтверджено"}
            text += f"\n\nВаш статус: <b>{status_names.get(mine.status, mine.status)}</b>"
            if mine.admin_note:
                text += f"\n💬 Коментар координатора: {escape(mine.admin_note)}"
        photo = await telegram_photo_input(db, task.image_path)
        if photo and len(text) <= 950:
            await call.message.answer_photo(photo, caption=text, reply_markup=b.as_markup() if b.buttons else None)
        elif photo:
            await call.message.answer_photo(photo, caption=f"🧰 <b>{safe_title}</b>\n👁 {view_stat['views']} переглядів")
            await call.message.answer(text, reply_markup=b.as_markup() if b.buttons else None)
        else:
            await call.message.answer(text, reply_markup=b.as_markup() if b.buttons else None)
        await call.answer()


@router.callback_query(F.data.startswith("task_claim:"))
async def task_claim(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        task = await session.get(VolunteerTask, task_id)
        if not user or not task or task.status not in {"open", "active", "postponed"} or (task.deadline and clock.local_wall_to_utc(task.deadline) < clock.now_utc()):
            await call.answer("Задача недоступна", show_alert=True)
            return
        existing = await session.scalar(select(VolunteerTaskParticipation).where(
            VolunteerTaskParticipation.task_id == task.id,
            VolunteerTaskParticipation.user_id == user.id,
        ))
        if existing and existing.status != "cancelled":
            await call.answer("Ви вже долучилися до цієї задачі", show_alert=True)
            return
        count = await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(
            VolunteerTaskParticipation.task_id == task.id,
            VolunteerTaskParticipation.status != "cancelled",
        )) or 0
        if count >= max(1, int(task.max_participants or 1)):
            await call.answer("Усі місця вже зайняті", show_alert=True)
            return
        if existing:
            existing.status = "joined"
            existing.joined_at = clock.storage_utc()
            existing.submitted_at = None
            existing.approved_at = None
            existing.admin_note = ""
        else:
            session.add(VolunteerTaskParticipation(task_id=task.id, user_id=user.id, status="joined"))
        await session.commit()
        await call.message.answer(f"✅ Ви долучилися до задачі <b>{task.title}</b>. Після виконання відкрийте її ще раз і надішліть результат на перевірку.")
        await call.answer()


@router.callback_query(F.data.startswith("task_done:"))
async def task_done(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":")[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        task = await session.get(VolunteerTask, task_id)
        part = await session.scalar(select(VolunteerTaskParticipation).where(
            VolunteerTaskParticipation.task_id == task_id,
            VolunteerTaskParticipation.user_id == user.id if user else -1,
        ))
        if not user or not task or task.status not in {"open", "active", "postponed"} or (task.deadline and clock.local_wall_to_utc(task.deadline) < clock.now_utc()):
            await call.answer("Дедлайн задачі завершено", show_alert=True)
            return
        if not part or part.status not in {"joined", "returned"}:
            await call.answer("Неактуально", show_alert=True)
            return
        part.status = "submitted"
        part.submitted_at = clock.storage_utc()
        await session.commit()
        await call.message.answer("⏳ Виконання передано координатору на підтвердження.")
        await call.answer()


@router.callback_query(F.data.startswith("task_cancel_join:"))
async def task_cancel_join(call: CallbackQuery, db: Database) -> None:
    task_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        if not user:
            await call.answer(); return
        part = await session.scalar(select(VolunteerTaskParticipation).where(VolunteerTaskParticipation.task_id == task_id, VolunteerTaskParticipation.user_id == user.id))
        if not part or part.status == "approved":
            await call.answer("Участь уже не можна скасувати", show_alert=True); return
        part.status = "cancelled"
        part.submitted_at = None
        part.admin_note = "Скасовано учасником"
        await session.commit()
    await call.message.answer("❌ Участь у волонтерській задачі скасовано. Історію запису збережено.")
    await call.answer()


@router.callback_query(F.data == "nav:opportunities")
async def nav_opportunities(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        rows=list((await session.scalars(select(Opportunity).where(Opportunity.active == True,(Opportunity.deadline.is_(None)) | (Opportunity.deadline >= clock.local_wall())))).all())  # noqa: E712
        rows.sort(key=opportunity_sort_key)
        if not user or not rows:
            await call.message.answer("🌍 Зараз немає актуальних можливостей для молоді.")
        else:
            b=InlineKeyboardBuilder(); lines=["🌍 <b>Можливості для молоді</b>","","<b>Оберіть можливість:</b>"]
            for idx,o in enumerate(rows[:20],1):
                deadline=o.deadline.strftime("%d.%m.%Y") if o.deadline else "без дедлайну"
                urgent=bool(deadline_urgency(o).get("urgent"))
                urgent_text=f"\n🔥 <b>У вас є остання можливість долучитись до «{escape(o.title)}»</b>" if urgent else ""
                lines.append(f"\n<b>{idx}. {escape(o.title)}</b>\n📆 {deadline} • {escape(o.kind or 'можливість')}{urgent_text}")
                b.button(text=entity_button_text(f"{'🔥' if urgent else '🌍'} {o.title}"),callback_data=f"opp:{o.id}")
            b.adjust(1); await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "nav:activities")
async def nav_activities(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        rows=(await session.scalars(select(ActivityType).where(ActivityType.active == True).order_by(ActivityType.sort_order,ActivityType.title))).all()  # noqa: E712
        mine=(await session.scalars(select(ActivityApplication).where(ActivityApplication.user_id==user.id).order_by(ActivityApplication.requested_at.desc()).limit(12))).all()
        b=InlineKeyboardBuilder(); lines=["⚡ <b>Активності АМП XP</b>","","<b>Доступні активності:</b>"]
        for idx,item in enumerate(rows,1):
            lines.append(f"\n<b>{idx}. {escape(item.title)}</b>\n⚡ {item.xp_reward} XP • ⏱ {item.hours_reward:g} год.")
            b.button(text=entity_button_text(f"⚡ {item.title} · {item.xp_reward} XP"),callback_data=f"activity:{item.id}")
        if mine: b.button(text="📋 Мої заявки",callback_data="activity:mine")
        b.adjust(1); await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "nav:activity_mine")
async def nav_activity_mine(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        rows=(await session.execute(select(ActivityApplication,ActivityType).join(ActivityType,ActivityType.id==ActivityApplication.activity_type_id).where(ActivityApplication.user_id==user.id).order_by(ActivityApplication.requested_at.desc()).limit(15))).all()
        b=InlineKeyboardBuilder(); lines=["📋 <b>Мої заявки на активності</b>"]
        for app,item in rows:
            lines.append(f"\n<b>#{app.id} • {item.title}</b>\n{activity_status_label(app.status)} • {app.xp_reward} XP")
            b.button(text=entity_button_text(f"📋 #{app.id} · {item.title}"),callback_data=f"activity_app:{app.id}")
        b.button(text="⬅️ Назад",callback_data="nav:activities"); b.adjust(1)
        await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "nav:tasks")
async def nav_tasks(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        await process_expired_content(session); await session.commit()
        user=await get_user_by_tg(session,call.from_user.id)
        if not user: await call.answer(); return
        now=clock.local_wall(); rows=(await session.scalars(select(VolunteerTask).where(VolunteerTask.status.in_(["open","active","postponed"]),(VolunteerTask.deadline.is_(None)) | (VolunteerTask.deadline>=now)).order_by(VolunteerTask.deadline.is_(None),VolunteerTask.deadline.asc(),VolunteerTask.id.desc()))).all()
        mine={p.task_id:p for p in (await session.scalars(select(VolunteerTaskParticipation).where(VolunteerTaskParticipation.user_id==user.id))).all()}
        b=InlineKeyboardBuilder(); lines=["✅ <b>Волонтерські задачі</b>"]
        for task in rows:
            count=int(await session.scalar(select(func.count(VolunteerTaskParticipation.id)).where(VolunteerTaskParticipation.task_id==task.id,VolunteerTaskParticipation.status!="cancelled")) or 0); part=mine.get(task.id)
            if not part and count>=max(1,int(task.max_participants or 1)): continue
            prefix="⏳" if part and part.status=="submitted" else "✅" if part and part.status=="approved" else "🟡" if part else "🟢"
            lines.append(f"\n<b>{escape(task.title)}</b>\n{prefix} • 👥 {count}/{max(1,int(task.max_participants or 1))}")
            b.button(text=entity_button_text(f"{prefix} {task.title}"),callback_data=f"task:{task.id}")
        b.adjust(1); await call.message.answer("\n".join(lines),reply_markup=b.as_markup())
    await call.answer()


@router.message(F.text == "📊 Рейтинг")
async def leaderboard(message: Message, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, message.from_user.id)
        season = await current_season(session)
        if not user or not season:
            await message.answer("📊 Активний сезон ще не налаштований.")
            return
        sxp = await season_xp(session, user.id, season.id)
        league = league_for_xp(sxp)
        b = InlineKeyboardBuilder()
        b.button(text="🌍 Загальний рейтинг · ТОП-20", callback_data="rating:overall")
        b.button(text=f"{league.icon} Рейтинг моєї ліги", callback_data="rating:league")
        b.adjust(1)
        privacy_note = "\n\n🔒 Твій профіль прихований із публічного рейтингу." if user.leaderboard_opt_in is False else ""
        await message.answer(
            f"📊 <b>Рейтинг сезону «{escape(season.name)}»</b>\n\n"
            f"Твоя ліга: <b>{league.icon} {league.title}</b>\n"
            f"Сезонний XP: <b>{sxp}</b>{privacy_note}",
            reply_markup=b.as_markup(),
        )


@router.callback_query(F.data == "rating:overall")
async def rating_overall(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        season = await current_season(session)
        if not season:
            await call.answer("Активного сезону немає", show_alert=True); return
        rows = await season_leaderboard_rows(session, season, limit=20)
        lines = [f"🌍 <b>Загальний ТОП-20 · {escape(season.name)}</b>"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (_, name, xp) in enumerate(rows, 1):
            prefix = medals[i-1] if i <= 3 else f"{i}."
            lg = league_for_xp(int(xp or 0))
            lines.append(f"{prefix} {escape(name)} — <b>{int(xp or 0)} XP</b> · {lg.icon}")
        if len(lines) == 1:
            lines.append("Рейтинг поки порожній.")
        b = InlineKeyboardBuilder()
        b.button(text="🏆 Рейтинг моєї ліги", callback_data="rating:league")
        await call.message.answer("\n".join(lines), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data == "rating:league")
async def rating_league(call: CallbackQuery, db: Database) -> None:
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        season = await current_season(session)
        if not user or not season:
            await call.answer("Дані недоступні", show_alert=True); return
        sxp = await season_xp(session, user.id, season.id)
        league = league_for_xp(sxp)
        rows = await league_leaderboard_rows(session, season, league)
        position = next((i for i, row in enumerate(rows, 1) if row[0] == user.id), None)
        place_text = f"<b>{position}</b> із {len(rows)}" if position else "<b>не публікується</b>"
        lines = [
            f"{league.icon} <b>{league.title}</b>",
            f"Твоє місце: {place_text} · <b>{sxp} XP</b>",
            "",
            "<b>ТОП-10 ліги</b>",
        ]
        medals = ["🥇", "🥈", "🥉"]
        for i, (_, name, xp) in enumerate(rows[:10], 1):
            prefix = medals[i-1] if i <= 3 else f"{i}."
            lines.append(f"{prefix} {escape(name)} — <b>{int(xp or 0)} XP</b>")
        if not rows:
            lines.append("У лізі поки немає учасників.")
        b = InlineKeyboardBuilder()
        b.button(text="🌍 Загальний ТОП-20", callback_data="rating:overall")
        await call.message.answer("\n".join(lines), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("assigned_idea:"))
async def assigned_idea_detail(call: CallbackQuery, db: Database) -> None:
    idea_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        idea = await session.get(Idea, idea_id)
        if not user or not idea or (idea.responsible_user_id != user.id and idea.user_id != user.id and user.role not in {"admin", "superadmin", "coordinator"}):
            await call.answer("Немає доступу", show_alert=True); return
        deadline = idea.implementation_deadline.strftime("%d.%m.%Y %H:%M") if idea.implementation_deadline else "не встановлено"
        await call.message.answer(
            f"💡 <b>{escape(idea.title)}</b>\n"
            f"Статус: <b>{escape(idea_status_label(idea.status))}</b>\n"
            f"Прогрес: <b>{int(idea.progress_percent or 0)}%</b>\n"
            f"Дедлайн: {deadline}\n\n"
            f"<b>Проблема / потреба</b>\n{escape(idea.problem or '—')}\n\n"
            f"<b>Що пропонується</b>\n{escape(idea.description or '—')}\n\n"
            f"<b>Завдання</b>\n{escape(idea.project_tasks or '—')}"
        )
    await call.answer()


@router.callback_query(F.data.startswith("assigned_request:"))
async def assigned_request_detail(call: CallbackQuery, db: Database) -> None:
    case_id = int(call.data.split(":", 1)[1])
    async with db.session_factory() as session:
        user = await get_user_by_tg(session, call.from_user.id)
        case = await session.get(RequestCase, case_id)
        if not user or not case or (case.assigned_user_id != user.id and case.user_id != user.id and user.role not in {"admin", "superadmin", "coordinator"}):
            await call.answer("Немає доступу", show_alert=True); return
        number = case.case_number or f"AMP-{case.created_at.year}-{case.id:04d}"
        deadline = case.response_deadline.strftime("%d.%m.%Y %H:%M") if case.response_deadline else "не встановлено"
        await call.message.answer(
            f"🆘 <b>{escape(number)} · {escape(case.title)}</b>\n"
            f"Статус: <b>{escape(request_status_label(case.status))}</b>\n"
            f"Пріоритет: <b>{escape(label(case.priority))}</b>\n"
            f"Дедлайн: {deadline}\n\n"
            f"{escape(case.description or '—')}"
        )
    await call.answer()


@router.message(F.text == "📜 Правила")
async def rules(message: Message) -> None:
    await message.answer(
        "📜 <b>Правила та авторські права АМП XP</b>\n\n"
        "• XP отримуються лише за підтверджену активність.\n"
        "• У розділі «⚡ Активності» спочатку подається заявка з планом; виконання починається після дозволу координатора, а XP нараховуються після фінального підтвердження.\n"
        "• Загальний XP показує досвід і визначає рівень. Окремий XP-гаманець можна обмінювати на винагороди.\n"
        "• QR події фіксує присутність; XP нараховуються після підтвердження координатором.\n"
        "• Персональний QR-бейдж призначений для ідентифікації учасника та не замінює QR події.\n"
        "• Не можна передавати свій QR або акаунт іншій людині.\n"
        "• За порушення безпеки діє Регламент АМПасадорів, а не система «штрафних балів».\n"
        "• Обмежені можливості можуть враховувати XP, але відбір не базується лише на балах.\n\n"
        "© <b>АМПасадори / Анисівський молодіжний простір</b>. Логотип, айдентика, тексти, макети та створені командою матеріали використовуються для діяльності АМП. Не змінюйте логотип, не використовуйте його для сторонніх зборів, реклами чи комерційних матеріалів без погодження команди. Права третіх осіб на фото, музику, шрифти та інший контент мають бути дотримані."
    )


