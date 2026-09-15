from .common import *  # noqa: F401,F403
from .gamification import current_season, season_xp, xp_total
from .users import age_on

def export_event_participants_pdf(
    event: Event,
    registrations: list[tuple[EventRegistration, User]],
    *,
    include_sensitive: bool = False,
) -> bytes:
    """Build a print-friendly branded PDF register for one event.

    The default document is deliberately data-minimized.  Sensitive contact,
    gender and vulnerability fields are added only for a superadmin route.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from textwrap import shorten

    plt.rcParams["font.family"] = "DejaVu Sans"
    out = BytesIO()
    logo_path = Path("app/web/static/amp_logo.png")
    logo = plt.imread(str(logo_path)) if logo_path.exists() else None
    privacy = (
        "КОНФІДЕНЦІЙНО • розширений список • доступ лише суперадміністратору"
        if include_sensitive else
        "Внутрішній робочий список • без контактних і чутливих соціальних даних"
    )
    if include_sensitive:
        headers = ["№", "ПІБ", "Вік", "Стать", "Соціальний статус", "Email", "Телефон", "Фото/відео", "Статус", "ID АМП"]
        widths = [0.035, 0.16, 0.045, 0.075, 0.18, 0.14, 0.10, 0.09, 0.095, 0.08]
    else:
        headers = ["№", "ПІБ", "Вік", "Статус участі", "ID АМП"]
        widths = [0.06, 0.40, 0.09, 0.27, 0.18]

    rows_per_page = 22 if include_sensitive else 28
    chunks = [registrations[i:i + rows_per_page] for i in range(0, len(registrations), rows_per_page)] or [[]]
    with PdfPages(out) as pdf:
        for page_no, chunk in enumerate(chunks, start=1):
            fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
            # branded masthead
            fig.patches.extend([plt.Rectangle((0, .89), 1, .11, transform=fig.transFigure, color="#0B5B6C", zorder=-1)])
            if logo is not None:
                axl = fig.add_axes([.035, .905, .075, .07]); axl.imshow(logo); axl.axis("off")
            fig.text(.125, .948, "АМПасадори", fontsize=20, weight="bold", color="white", va="center")
            fig.text(.125, .916, "Список учасників події", fontsize=11.5, color="#DDF8FA", va="center")
            fig.text(.965, .948, f"{page_no}/{len(chunks)}", fontsize=9, color="white", ha="right", va="center")

            fig.text(.04, .845, event.title, fontsize=16, weight="bold", color="#173B43")
            meta = f"{event.starts_at.strftime('%d.%m.%Y • %H:%M')}   •   {event.location or 'Локацію не зазначено'}   •   {len(registrations)} реєстрацій"
            fig.text(.04, .812, meta, fontsize=9.5, color="#607C83")
            fig.text(.04, .782, privacy, fontsize=8.2, color="#7A9095")

            ax = fig.add_axes([.035, .09, .93, .66]); ax.axis("off")
            body=[]
            for i, (reg, user) in enumerate(chunk, start=(page_no-1)*rows_per_page+1):
                age = age_on(user.birth_date, event.starts_at.date()) if user.birth_date else "—"
                if include_sensitive:
                    vulnerabilities = ", ".join(vulnerability_labels(user.vulnerability_categories)) or "—"
                    body.append([
                        i,
                        shorten(user.full_name or "—", width=32, placeholder="…"),
                        age,
                        gender_label(user.gender) if user.gender else "—",
                        shorten(vulnerabilities, width=45, placeholder="…"),
                        shorten(user.email or "—", width=28, placeholder="…"),
                        user.phone or "—",
                        media_consent_label(user.media_consent),
                        event_registration_status_label(reg.status),
                        f"АМП-{user.id:04d}",
                    ])
                else:
                    body.append([i, user.full_name or "—", age, event_registration_status_label(reg.status), f"АМП-{user.id:04d}"])
            if body:
                table = ax.table(cellText=body, colLabels=headers, cellLoc="left", colLoc="left", loc="upper left", colWidths=widths)
                table.auto_set_font_size(False); table.set_fontsize(7.2 if include_sensitive else 8.6); table.scale(1, 1.42)
                for (r,c), cell in table.get_celld().items():
                    cell.set_edgecolor("#D4E6E9")
                    cell.set_linewidth(.55)
                    cell.PAD=.12
                    if r == 0:
                        cell.set_facecolor("#EAF8FA"); cell.set_text_props(weight="bold", color="#0B5B6C")
                    elif r % 2 == 0:
                        cell.set_facecolor("#F7FBFC")
                    else:
                        cell.set_facecolor("white")
            else:
                ax.text(.5,.55,"На подію ще ніхто не зареєструвався",ha="center",va="center",fontsize=13,color="#71888E")
            fig.text(.04,.035,"АМП • Анисівський молодіжний простір",fontsize=8,color="#0B5B6C")
            fig.text(.96,.035,f"Сформовано {datetime.now().strftime('%d.%m.%Y %H:%M')}",fontsize=7.5,color="#71888E",ha="right")
            pdf.savefig(fig, bbox_inches="tight", pad_inches=.03); plt.close(fig)
    return out.getvalue()


def export_event_participants_excel(
    event: Event,
    registrations: list[tuple[EventRegistration, User]],
    *,
    include_sensitive: bool = False,
) -> bytes:
    """Build an event-specific participant register.

    The default workbook is data-minimized and contains only operational fields.
    Sensitive contact, gender and vulnerability data are included only when
    ``include_sensitive=True`` and the web route has already enforced
    superadmin access.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Учасники події"
    ws.sheet_view.showGridLines = False

    dark_teal = "0B5B6C"
    turquoise = "06B8C5"
    light_teal = "EAF8FA"
    pale = "F5FBFC"
    white = "FFFFFF"
    text = "173B43"
    muted = "6C858B"
    line = "CFE5E9"

    thin = Side(style="thin", color=line)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    if include_sensitive:
        headers = [
            "№", "ПІБ", "Вік", "Стать", "Соціальний статус",
            "Електронна пошта", "Телефон", "Згода на фото/відеозйомку",
            "Статус участі", "ID АМП", "Підтверджено", "Цифровий код підтвердження",
        ]
        note = "Конфіденційно • розширений експорт • лише для суперадміністратора"
        widths = {"A": 6, "B": 26, "C": 8, "D": 18, "E": 36, "F": 28, "G": 18, "H": 25, "I": 22, "J": 13, "K": 19, "L": 68}
    else:
        headers = ["№", "ПІБ", "Вік", "Статус участі", "ID АМП", "Підтверджено", "Цифровий код підтвердження"]
        note = "Внутрішній робочий список • без чутливих контактних і соціальних даних"
        widths = {"A": 6, "B": 32, "C": 10, "D": 25, "E": 15, "F": 19, "G": 68}

    max_col = len(headers)
    end_col_letter = get_column_letter(max_col)

    ws.merge_cells(f"A1:{end_col_letter}1")
    ws["A1"] = "Список учасників події"
    ws["A1"].font = Font(name="Arial", size=18, bold=True, color=white)
    ws["A1"].fill = PatternFill("solid", fgColor=dark_teal)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells(f"A2:{end_col_letter}2")
    ws["A2"] = note
    ws["A2"].font = Font(name="Arial", size=10, italic=True, color=muted)
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws["A2"].fill = PatternFill("solid", fgColor=pale)

    meta = [
        ("Назва події", event.title),
        ("Дата", event.starts_at.strftime("%d.%m.%Y")),
        ("Час", event.starts_at.strftime("%H:%M")),
        ("Місце", event.location or "—"),
        ("Кількість реєстрацій", len(registrations)),
    ]
    for idx, (label_text, value) in enumerate(meta, start=4):
        ws[f"A{idx}"] = label_text
        ws[f"A{idx}"].font = Font(name="Arial", size=11, bold=True, color=dark_teal)
        ws[f"A{idx}"].fill = PatternFill("solid", fgColor=light_teal)
        ws[f"A{idx}"].border = border
        ws[f"A{idx}"].alignment = Alignment(vertical="center")
        if max_col > 1:
            ws.merge_cells(start_row=idx, start_column=2, end_row=idx, end_column=max_col)
            cell = ws.cell(idx, 2)
            cell.value = value
            cell.font = Font(name="Arial", size=11, color=text)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            for col in range(2, max_col + 1):
                ws.cell(idx, col).border = border
                ws.cell(idx, col).fill = PatternFill("solid", fgColor=white)
        ws.row_dimensions[idx].height = 24

    header_row = 10
    for col, value in enumerate(headers, start=1):
        cell = ws.cell(header_row, col, value)
        cell.font = Font(name="Arial", size=10, bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=turquoise)
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[header_row].height = 34

    status_labels = {
        "registered": "Зареєстрований",
        "reserved": "Місце зарезервовано",
        "waitlisted": "У черзі",
        "checked_in": "Відмічено присутність",
        "attended": "Був присутній",
        "no_show": "Не прийшов",
        "cancelled": "Скасував",
    }
    event_day = event.starts_at.date()
    for number, (reg, user) in enumerate(registrations, start=1):
        row = header_row + number
        if include_sensitive:
            values = [
                number,
                user.full_name or "—",
                age_on(user.birth_date, event_day) if user.birth_date else None,
                gender_label(user.gender),
                "; ".join(vulnerability_labels(user.vulnerability_categories)) or "Не зазначено",
                user.email or "—",
                user.phone or "—",
                media_consent_label(user.media_consent),
                status_labels.get(reg.status, reg.status or "—"),
                f"АМП-{user.id:04d}",
                reg.confirmed_at.strftime("%d.%m.%Y %H:%M") if reg.confirmed_at else "—",
                reg.attendance_signature or "—",
            ]
        else:
            values = [
                number,
                user.full_name or "—",
                age_on(user.birth_date, event_day) if user.birth_date else None,
                status_labels.get(reg.status, reg.status or "—"),
                f"АМП-{user.id:04d}",
                reg.confirmed_at.strftime("%d.%m.%Y %H:%M") if reg.confirmed_at else "—",
                reg.attendance_signature or "—",
            ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row, col, value)
            cell.font = Font(name="Arial", size=10, color=text)
            cell.border = border
            cell.fill = PatternFill("solid", fgColor=white if number % 2 else pale)
            cell.alignment = Alignment(
                horizontal="center" if col in ({1, 3, 4, 8, 9, 10, 11} if include_sensitive else {1, 3, 4, 5, 6}) else "left",
                vertical="center",
                wrap_text=True,
            )
        ws.row_dimensions[row].height = 30

    last_row = max(header_row, header_row + len(registrations))
    ws.auto_filter.ref = f"A{header_row}:{end_col_letter}{last_row}"
    ws.freeze_panes = f"A{header_row + 1}"
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.sheet_properties.tabColor = turquoise
    ws.page_margins.left = 0.35; ws.page_margins.right = 0.35; ws.page_margins.top = 0.55; ws.page_margins.bottom = 0.55
    ws.oddHeader.center.text = "&BАМПасадори • Список учасників події"
    ws.oddHeader.center.size = 10
    ws.oddFooter.left.text = "АМП • Анисівський молодіжний простір"
    ws.oddFooter.right.text = "Сторінка &P з &N"
    ws.sheet_view.zoomScale = 90
    wb.properties.title = f"Учасники події — {event.title}"
    wb.properties.subject = "АМПасадори • реєстр учасників події"
    wb.properties.creator = "АМП XP / АМПасадори"

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


async def export_basic_excel(session: AsyncSession) -> bytes:
    """Data-minimized operational export available to regular web admins."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Учасники"
    ws.append(["ID АМП", "ПІБ", "Вік", "Статус", "Роль", "Населений пункт", "XP загальний", "XP сезону", "Волонтерські години"])
    users = (await session.scalars(select(User).order_by(User.full_name.asc()))).all()
    season = await current_season(session)
    for u in users:
        ws.append([
            f"АМП-{u.id:04d}",
            u.full_name,
            age_on(u.birth_date) if u.birth_date else None,
            u.status,
            u.role,
            u.settlement,
            await xp_total(session, u.id),
            await season_xp(session, u.id, season.id if season else None),
            u.volunteer_hours,
        ])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:I{max(1, ws.max_row)}"
    for col, width in {"A": 14, "B": 32, "C": 8, "D": 16, "E": 18, "F": 24, "G": 14, "H": 14, "I": 20}.items():
        ws.column_dimensions[col].width = width

    ws2 = wb.create_sheet("Події")
    ws2.append(["ID", "Назва", "Дата", "Місце", "XP", "Години", "Статус"])
    events = (await session.scalars(select(Event).order_by(Event.starts_at.desc()))).all()
    for e in events:
        ws2.append([e.id, e.title, e.starts_at, e.location, e.xp_reward, e.volunteer_hours, e.status])

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


async def export_excel(session: AsyncSession) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Учасники"
    ws.append(["ID", "ID Telegram", "Прізвище", "Ім’я", "ПІБ", "Дата народження", "Вік", "Стать", "Телефон", "Email", "Telegram", "Статус", "Роль", "Населений пункт", "Соціальний статус / категорії вразливості", "Згода на фото/відео", "XP загальний", "XP сезону", "XP-гаманець", "Волонтерські години", "Код запрошення", "Ознайомлення з даними — версія", "Ознайомлення — дата", "Блокування до", "Причина блокування"])
    users = (await session.scalars(select(User).order_by(User.id))).all()
    season = await current_season(session)
    for u in users:
        first_name, last_name = split_display_name(u.full_name, u.first_name, u.last_name)
        ws.append([
            u.id,
            u.tg_id,
            last_name,
            first_name,
            u.full_name,
            u.birth_date,
            age_on(u.birth_date) if u.birth_date else None,
            gender_label(u.gender),
            u.phone,
            u.email,
            f"@{u.username}" if u.username else "",
            u.status,
            u.role,
            u.settlement,
            "; ".join(vulnerability_labels(u.vulnerability_categories)),
            media_consent_label(u.media_consent),
            await xp_total(session, u.id),
            await season_xp(session, u.id, season.id if season else None),
            u.wallet_xp,
            u.volunteer_hours,
            u.referral_code,
            u.privacy_notice_version,
            u.privacy_acknowledged_at,
            u.blocked_until,
            u.block_reason,
        ])

    ws2 = wb.create_sheet("XP журнал")
    ws2.append(["ID", "ID учасника", "XP", "Категорія", "Опис", "ID сезону", "Дата"])
    txs = (await session.scalars(select(XPTransaction).order_by(XPTransaction.created_at.desc()))).all()
    for t in txs:
        ws2.append([t.id, t.user_id, t.amount, t.category, t.description, t.season_id, t.created_at])

    ws3 = wb.create_sheet("Події")
    ws3.append(["ID", "Назва", "Дата", "Локація", "XP", "Години", "Статус"])
    events = (await session.scalars(select(Event).order_by(Event.starts_at.desc()))).all()
    for e in events:
        ws3.append([e.id, e.title, e.starts_at, e.location, e.xp_reward, e.volunteer_hours, e.status])

    ws4 = wb.create_sheet("Реферали")
    ws4.append(["ID", "ID запрошувача", "ID запрошеного", "Статус", "XP", "Дата"])
    refs = (await session.scalars(select(Referral).order_by(Referral.created_at.desc()))).all()
    for r in refs:
        ws4.append([r.id, r.inviter_user_id, r.invited_user_id, r.status, r.xp_reward, r.created_at])

    ws5 = wb.create_sheet("Бейджі")
    ws5.append(["ID учасника", "ID бейджа", "Дата"])
    awarded = (await session.scalars(select(UserBadge).order_by(UserBadge.awarded_at.desc()))).all()
    for row in awarded:
        ws5.append([row.user_id, row.badge_id, row.awarded_at])

    ws6 = wb.create_sheet("Винагороди")
    ws6.append(["ID", "Назва", "Вартість XP", "Залишок", "Активна", "Фото"])
    rewards = (await session.scalars(select(Reward).order_by(Reward.id))).all()
    for r in rewards:
        ws6.append([r.id, r.title, r.min_xp, r.stock, r.active, r.image_path])

    ws7 = wb.create_sheet("Заявки на винагороди")
    ws7.append(["ID", "ID винагороди", "ID учасника", "Статус", "XP витрачено", "Дата заявки", "Дата видачі"])
    claims = (await session.scalars(select(RewardClaim).order_by(RewardClaim.requested_at.desc()))).all()
    for c in claims:
        ws7.append([c.id, c.reward_id, c.user_id, c.status, c.xp_spent, c.requested_at, c.fulfilled_at])

    ws8 = wb.create_sheet("Волонтерські задачі")
    ws8.append(["ID", "Назва", "XP", "Години", "Дедлайн", "Статус", "Макс. учасників", "Фото"])
    tasks = (await session.scalars(select(VolunteerTask).order_by(VolunteerTask.created_at.desc()))).all()
    for t in tasks:
        ws8.append([t.id, t.title, t.xp_reward, t.hours_reward, t.deadline, t.status, t.max_participants, t.image_path])

    ws8b = wb.create_sheet("Участь у задачах")
    ws8b.append(["ID", "ID задачі", "ID учасника", "Статус", "Долучився", "Подано", "Підтверджено", "Коментар"])
    task_parts = (await session.scalars(select(VolunteerTaskParticipation).order_by(VolunteerTaskParticipation.joined_at.desc()))).all()
    for p in task_parts:
        ws8b.append([p.id, p.task_id, p.user_id, p.status, p.joined_at, p.submitted_at, p.approved_at, p.admin_note])

    ws9 = wb.create_sheet("Ідеї")
    ws9.append(["ID", "ID учасника", "Назва", "Напрям", "Проблема", "Рішення", "Аудиторія", "Результат", "Ресурси", "Статус", "Відповідальний", "Примітка", "Створено", "Оновлено"])
    ideas = (await session.scalars(select(Idea).order_by(Idea.created_at.desc()))).all()
    for i in ideas:
        ws9.append([i.id, i.user_id, i.title, i.category, i.problem, i.description, i.audience, i.expected_result, i.resources, i.status, i.responsible_user_id, i.admin_note, i.created_at, i.updated_at])

    ws10 = wb.create_sheet("Звернення")
    ws10.append(["ID", "ID учасника", "Тип", "Тема", "Опис", "Пріоритет", "Статус", "Відповідальний", "Відповідь", "Внутрішня примітка", "Фото", "Створено", "Оновлено", "Вирішено"])
    cases = (await session.scalars(select(RequestCase).order_by(RequestCase.created_at.desc()))).all()
    for c in cases:
        ws10.append([c.id, c.user_id, c.category, c.title, c.description, c.priority, c.status, c.assigned_user_id, c.admin_response, c.internal_note, c.image_path, c.created_at, c.updated_at, c.resolved_at])

    ws11 = wb.create_sheet("Каталог активностей")
    ws11.append(["ID", "Код", "Назва", "Категорія", "XP", "Години", "Активна", "Пояснення"])
    activity_types = (await session.scalars(select(ActivityType).order_by(ActivityType.sort_order, ActivityType.id))).all()
    for a in activity_types:
        ws11.append([a.id, a.code, a.title, a.category, a.xp_reward, a.hours_reward, a.active, a.description])

    ws12 = wb.create_sheet("Заявки на активності")
    ws12.append(["ID", "ID активності", "ID учасника", "Статус", "План", "Результат", "XP", "Години", "Подано", "Схвалено", "Виконано"])
    apps = (await session.scalars(select(ActivityApplication).order_by(ActivityApplication.requested_at.desc()))).all()
    for a in apps:
        ws12.append([a.id, a.activity_type_id, a.user_id, a.status, a.plan_text, a.result_note, a.xp_reward, a.hours_reward, a.requested_at, a.approved_at, a.completed_at])

    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


