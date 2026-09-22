from __future__ import annotations

from app.time_utils import clock

from fastapi import APIRouter
from app.web.dependencies import (
    File, Form, HTMLResponse, HTTPException, RedirectResponse, Request, Response, Survey, SurveyQuestion, SurveyResponse, UploadFile, User, UserStatus, build_survey_stats, ctx, datetime, db, delete, delete_image, func, guard, guard_permission, json, log_audit, or_, save_image, select, survey_excel, survey_pdf, survey_question_png, templates, timedelta
)
from app.content_views import content_view_stat, content_view_stats
from app.model_domains import Event, SurveyAudienceUser
from app.survey_audience import audience_summary, eligible_users, normalize_audience_type
from app.web.dependencies import _refresh_lifecycle
from app.web.broadcast_runtime import (
    _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

from app.governance import record_field_changes, record_rule_change

router = APIRouter()

@router.get("/admin/surveys", response_class=HTMLResponse)
async def surveys_page(request: Request, q: str = "", status: str = "", period: str = "", type: str = "", sort: str = "newest"):
    if r := guard(request): return r
    async with db.session_factory() as session:
        await _refresh_lifecycle(session)
        stmt=select(Survey)
        if q: stmt=stmt.where(or_(Survey.title.ilike(f"%{q}%"),Survey.description.ilike(f"%{q}%")))
        if status: stmt=stmt.where(Survey.status == status)
        cutoff_map={"7d":7,"30d":30,"90d":90}
        if period in cutoff_map: stmt=stmt.where(Survey.created_at >= clock.storage_utc()-timedelta(days=cutoff_map[period]))
        if type == "rewarded": stmt=stmt.where(Survey.xp_reward > 0)
        elif type == "no_reward": stmt=stmt.where(Survey.xp_reward == 0)
        order_map={"oldest":Survey.created_at.asc(),"title":Survey.title.asc(),"deadline":Survey.ends_at.asc().nullslast(),"newest":Survey.created_at.desc()}
        rows=list((await session.scalars(stmt.order_by(order_map.get(sort,Survey.created_at.desc())))).all())
        counts = {sid: int(c or 0) for sid, c in (await session.execute(select(SurveyResponse.survey_id, func.count(SurveyResponse.id)).group_by(SurveyResponse.survey_id))).all()}
        qcounts = {sid: int(c or 0) for sid, c in (await session.execute(select(SurveyQuestion.survey_id, func.count(SurveyQuestion.id)).group_by(SurveyQuestion.survey_id))).all()}
        view_stats = await content_view_stats(session, "survey", [item.id for item in rows])
        audience_meta = {item.id: await audience_summary(session, item) for item in rows}
        audience_users = list((await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name.asc()))).all())
        audience_events = list((await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(150))).all())
    return templates.TemplateResponse(request=request,name="surveys.html",context=ctx(request,rows=rows,counts=counts,qcounts=qcounts,view_stats=view_stats,audience_meta=audience_meta,audience_users=audience_users,audience_events=audience_events,q=q,status=status,period=period,type=type,sort=sort))


@router.post("/admin/surveys/create")
async def survey_create(request: Request):
    if r := guard(request): return r
    form = await request.form()
    title = str(form.get("title") or "").strip()
    if not title: raise HTTPException(400, "Вкажіть назву опитування")
    description = str(form.get("description") or "").strip()
    try:
        xp_reward = max(0, min(40, int(form.get("xp_reward") or 0)))
    except (TypeError, ValueError):
        xp_reward = 0
    ends_at = str(form.get("ends_at") or "").strip()
    deadline = datetime.fromisoformat(ends_at) if ends_at else None
    audience_type = normalize_audience_type(str(form.get("audience_type") or "all"))
    audience_event_id = int(form.get("audience_event_id")) if audience_type == "event" and str(form.get("audience_event_id") or "").isdigit() else None
    selected_user_ids = sorted({int(v) for v in form.getlist("audience_user_ids") if str(v).isdigit()}) if audience_type == "users" else []
    if audience_type == "users" and not selected_user_ids:
        raise HTTPException(400, "Для вибіркового опитування оберіть щонайменше одного учасника")
    if audience_type == "event" and not audience_event_id:
        raise HTTPException(400, "Оберіть подію, учасникам якої буде доступне опитування")
    async with db.session_factory() as session:
        if audience_event_id and not await session.get(Event, audience_event_id):
            raise HTTPException(400, "Обрану подію не знайдено")
        row = Survey(
            title=title, description=description, xp_reward=xp_reward, status="draft", ends_at=deadline,
            audience_type=audience_type, audience_event_id=audience_event_id,
            created_by_label=request.session.get("admin_name","web"), updated_at=clock.storage_utc(),
        )
        session.add(row); await session.flush()
        actor=request.session.get("admin_name","web")
        await record_field_changes(session, rule_prefix="survey", entity_type="survey", entity_id=row.id, old_values={}, new_values={"xp_reward": row.xp_reward}, author_label=actor, reason="Створення опитування")
        for user_id in selected_user_ids:
            session.add(SurveyAudienceUser(survey_id=row.id, user_id=user_id))
        await log_audit(session,"web_survey_create",actor_label=request.session.get("admin_name","web"),entity_type="survey",entity_id=row.id,details=f"{row.title}; audience={audience_type}")
        await session.commit()
        sid=row.id
    return RedirectResponse(f"/admin/surveys/{sid}",303)


@router.get("/admin/surveys/{survey_id}", response_class=HTMLResponse)
async def survey_detail(request: Request, survey_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if not survey: raise HTTPException(404,"Опитування не знайдено")
        questions=list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id).order_by(SurveyQuestion.sort_order,SurveyQuestion.id))).all())
        responses=(await session.execute(select(SurveyResponse,User).join(User,User.id==SurveyResponse.user_id).where(SurveyResponse.survey_id==survey_id).order_by(SurveyResponse.completed_at.desc()))).all()
        stats, decoded_answers = build_survey_stats(questions, responses)
        view_stat = await content_view_stat(session, "survey", survey.id)
        selected_audience_ids = set((await session.scalars(select(SurveyAudienceUser.user_id).where(SurveyAudienceUser.survey_id == survey.id))).all())
        audience_users = list((await session.scalars(select(User).where(User.status == UserStatus.ACTIVE.value).order_by(User.full_name.asc()))).all())
        audience_events = list((await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(150))).all())
        audience_label, audience_count = await audience_summary(session, survey)
    return templates.TemplateResponse(
        request=request, name="survey_detail.html",
        context=ctx(request, survey=survey, questions=questions, responses=responses, stats=stats, decoded_answers=decoded_answers, view_stat=view_stat,
                    selected_audience_ids=selected_audience_ids, audience_users=audience_users, audience_events=audience_events, audience_label=audience_label, audience_count=audience_count),
    )


@router.post("/admin/surveys/{survey_id}/identity")
async def survey_identity_update(request: Request, survey_id: int):
    if r := guard(request): return r
    form = await request.form()
    title = str(form.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Вкажіть назву опитування")
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if not survey:
            raise HTTPException(404, "Опитування не знайдено")
        survey.title = title[:180]
        survey.description = str(form.get("description") or "").strip()
        survey.updated_at = clock.storage_utc()
        await log_audit(session, "web_survey_identity_update", actor_label=request.session.get("admin_name", "web"), entity_type="survey", entity_id=survey.id, details=survey.title)
        await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}#survey-identity", 303)


@router.post("/admin/surveys/{survey_id}/update")
async def survey_update(request: Request, survey_id: int):
    if r := guard(request): return r
    form = await request.form()
    audience_type = normalize_audience_type(str(form.get("audience_type") or "all"))
    audience_event_id = int(form.get("audience_event_id")) if audience_type == "event" and str(form.get("audience_event_id") or "").isdigit() else None
    selected_user_ids = sorted({int(v) for v in form.getlist("audience_user_ids") if str(v).isdigit()}) if audience_type == "users" else []
    if audience_type == "users" and not selected_user_ids:
        raise HTTPException(400, "Для вибіркового опитування оберіть щонайменше одного учасника")
    if audience_type == "event" and not audience_event_id:
        raise HTTPException(400, "Оберіть подію для цільової аудиторії")
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if not survey: raise HTTPException(404,"Опитування не знайдено")
        old_rules={"xp_reward": survey.xp_reward}
        if audience_event_id and not await session.get(Event, audience_event_id):
            raise HTTPException(400, "Обрану подію не знайдено")
        try: survey.xp_reward=max(0,min(40,int(form.get("xp_reward") or 0)))
        except (TypeError, ValueError): survey.xp_reward=0
        raw_ends=str(form.get("ends_at") or "").strip()
        survey.ends_at=datetime.fromisoformat(raw_ends) if raw_ends else None
        survey.audience_type=audience_type
        survey.audience_event_id=audience_event_id
        survey.updated_at=clock.storage_utc()
        await session.execute(delete(SurveyAudienceUser).where(SurveyAudienceUser.survey_id == survey.id))
        for user_id in selected_user_ids:
            session.add(SurveyAudienceUser(survey_id=survey.id, user_id=user_id))
        actor=request.session.get("admin_name","web")
        await record_field_changes(session, rule_prefix="survey", entity_type="survey", entity_id=survey.id, old_values=old_rules, new_values={"xp_reward": survey.xp_reward}, author_label=actor, reason="Редагування опитування")
        await log_audit(session,"web_survey_update",actor_label=actor,entity_type="survey",entity_id=survey.id,details=f"settings; audience={audience_type}")
        await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}#survey-settings",303)


@router.post("/admin/surveys/{survey_id}/questions/create")
async def survey_question_create(
    request: Request, survey_id: int, text: str=Form(...), question_type: str=Form("single"),
    options: str=Form(""), required: str|None=Form(None), photo: UploadFile | None=File(None),
):
    if r := guard(request): return r
    if question_type not in {"single","multiple","text"}: raise HTTPException(400,"Некоректний тип питання")
    if question_type != "text" and len([x for x in options.splitlines() if x.strip()]) < 2: raise HTTPException(400,"Для питання з варіантами додайте щонайменше 2 варіанти — кожен з нового рядка")
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if not survey: raise HTTPException(404,"Опитування не знайдено")
        if survey.status != "draft": raise HTTPException(409,"Питання можна змінювати лише в чернетці")
        max_order=int(await session.scalar(select(func.coalesce(func.max(SurveyQuestion.sort_order),0)).where(SurveyQuestion.survey_id==survey_id)) or 0)
        image_path = await save_image(photo, "survey_questions") if photo and photo.filename else None
        q=SurveyQuestion(
            survey_id=survey_id, text=text.strip(), question_type=question_type,
            options_text='\n'.join(x.strip() for x in options.splitlines() if x.strip()),
            required=bool(required), sort_order=max_order+10, image_path=image_path,
        )
        session.add(q); await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}",303)


@router.post("/admin/surveys/{survey_id}/questions/{question_id}/update")
async def survey_question_update(
    request: Request, survey_id: int, question_id: int,
    text: str=Form(...), question_type: str=Form("single"), options: str=Form(""),
    required: str|None=Form(None), photo: UploadFile | None=File(None), remove_image: str|None=Form(None),
):
    if r := guard(request): return r
    if question_type not in {"single", "multiple", "text"}:
        raise HTTPException(400, "Некоректний тип питання")
    clean_options = [x.strip() for x in options.splitlines() if x.strip()]
    if question_type != "text" and len(clean_options) < 2:
        raise HTTPException(400, "Для питання з варіантами додайте щонайменше 2 варіанти")
    old_path = None
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        q = await session.get(SurveyQuestion, question_id)
        if not survey or not q or q.survey_id != survey_id:
            raise HTTPException(404, "Питання не знайдено")
        if survey.status != "draft":
            raise HTTPException(409, "Питання можна редагувати лише в чернетці")
        old_path = q.image_path
        q.text = text.strip()
        q.question_type = question_type
        q.options_text = "" if question_type == "text" else "\n".join(clean_options)
        q.required = bool(required)
        if remove_image:
            q.image_path = None
        elif photo and photo.filename:
            q.image_path = await save_image(photo, "survey_questions")
        await log_audit(session, "web_survey_question_update", actor_label=request.session.get("admin_name", "web"), entity_type="survey_question", entity_id=q.id, details=f"survey={survey_id}")
        await session.commit()
        new_path = q.image_path
    if old_path and old_path != new_path:
        await delete_image(old_path)
    return RedirectResponse(f"/admin/surveys/{survey_id}#question-{question_id}", 303)


@router.post("/admin/surveys/{survey_id}/questions/{question_id}/move")
async def survey_question_move(request: Request, survey_id: int, question_id: int):
    if r := guard(request): return r
    form = await request.form()
    direction = str(form.get("direction") or "")
    if direction not in {"up", "down"}:
        raise HTTPException(400, "Некоректний напрямок")
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if not survey:
            raise HTTPException(404, "Опитування не знайдено")
        if survey.status != "draft":
            raise HTTPException(409, "Порядок питань можна змінювати лише в чернетці")
        rows = list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id).order_by(SurveyQuestion.sort_order, SurveyQuestion.id))).all())
        index = next((i for i, item in enumerate(rows) if item.id == question_id), None)
        if index is None:
            raise HTTPException(404, "Питання не знайдено")
        other_index = index - 1 if direction == "up" else index + 1
        if 0 <= other_index < len(rows):
            rows[index].sort_order, rows[other_index].sort_order = rows[other_index].sort_order, rows[index].sort_order
            await log_audit(session, "web_survey_question_move", actor_label=request.session.get("admin_name", "web"), entity_type="survey_question", entity_id=question_id, details=f"direction={direction}")
            await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}#question-{question_id}", 303)


@router.post("/admin/surveys/{survey_id}/questions/{question_id}/delete")
async def survey_question_delete(request: Request, survey_id: int, question_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id); q=await session.get(SurveyQuestion,question_id)
        image_path = None
        if survey and q and q.survey_id==survey_id and survey.status=="draft":
            image_path = q.image_path
            await session.delete(q); await session.commit()
        if image_path:
            await delete_image(image_path)
    return RedirectResponse(f"/admin/surveys/{survey_id}",303)


@router.post("/admin/surveys/{survey_id}/questions/{question_id}/photo")
async def survey_question_photo(
    request: Request, survey_id: int, question_id: int, photo: UploadFile | None=File(None), remove: str|None=Form(None),
):
    if r := guard(request): return r
    old_path = None
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        q = await session.get(SurveyQuestion, question_id)
        if not survey or not q or q.survey_id != survey_id:
            raise HTTPException(404, "Питання не знайдено")
        if survey.status != "draft":
            raise HTTPException(409, "Фото питання можна змінювати лише в чернетці")
        old_path = q.image_path
        if remove:
            q.image_path = None
        elif photo and photo.filename:
            q.image_path = await save_image(photo, "survey_questions")
        else:
            raise HTTPException(400, "Оберіть фото або дію видалення")
        await session.commit()
    if old_path and (remove or old_path != q.image_path):
        await delete_image(old_path)
    return RedirectResponse(f"/admin/surveys/{survey_id}#question-{question_id}",303)


@router.get("/admin/surveys/{survey_id}/export.xlsx")
async def survey_export_excel(request: Request, survey_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if not survey: raise HTTPException(404, "Опитування не знайдено")
        questions = list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id).order_by(SurveyQuestion.sort_order,SurveyQuestion.id))).all())
        responses = (await session.execute(select(SurveyResponse,User).join(User,User.id==SurveyResponse.user_id).where(SurveyResponse.survey_id==survey_id).order_by(SurveyResponse.completed_at.desc()))).all()
        stats, decoded = build_survey_stats(questions, responses)
    payload = survey_excel(survey, questions, responses, stats, decoded)
    return Response(content=payload, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="AMP_survey_{survey_id}.xlsx"'})


@router.get("/admin/surveys/{survey_id}/export.pdf")
async def survey_export_pdf(request: Request, survey_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        if not survey: raise HTTPException(404, "Опитування не знайдено")
        questions = list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id).order_by(SurveyQuestion.sort_order,SurveyQuestion.id))).all())
        responses = (await session.execute(select(SurveyResponse,User).join(User,User.id==SurveyResponse.user_id).where(SurveyResponse.survey_id==survey_id).order_by(SurveyResponse.completed_at.desc()))).all()
        stats, decoded = build_survey_stats(questions, responses)
    payload = survey_pdf(survey, questions, responses, stats, decoded)
    return Response(content=payload, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="AMP_survey_{survey_id}.pdf"'})


@router.get("/admin/surveys/{survey_id}/questions/{question_id}/result.png")
async def survey_question_result_png(request: Request, survey_id: int, question_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        q = await session.get(SurveyQuestion, question_id)
        if not survey or not q or q.survey_id != survey_id: raise HTTPException(404, "Питання не знайдено")
        questions = list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id).order_by(SurveyQuestion.sort_order,SurveyQuestion.id))).all())
        responses = (await session.execute(select(SurveyResponse,User).join(User,User.id==SurveyResponse.user_id).where(SurveyResponse.survey_id==survey_id))).all()
        stats, _decoded = build_survey_stats(questions, responses)
    payload = survey_question_png(survey, q, stats[q.id], len(responses))
    return Response(content=payload, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="AMP_survey_{survey_id}_question_{question_id}.png"'})


@router.get("/admin/surveys/{survey_id}/responses/{response_id}", response_class=HTMLResponse)
async def survey_response_detail(request: Request, survey_id: int, response_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey = await session.get(Survey, survey_id)
        response = await session.get(SurveyResponse, response_id)
        if not survey or not response or response.survey_id != survey_id: raise HTTPException(404, "Відповідь не знайдено")
        user = await session.get(User, response.user_id)
        questions = list((await session.scalars(select(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id).order_by(SurveyQuestion.sort_order,SurveyQuestion.id))).all())
        try:
            answers = json.loads(response.answers_json or "{}")
        except Exception:
            answers = {}
    return templates.TemplateResponse(request=request, name="survey_response_detail.html", context=ctx(request, survey=survey, response=response, user=user, questions=questions, answers=answers))


@router.post("/admin/surveys/{survey_id}/publish")
async def survey_publish(request: Request, survey_id: int):
    if r := guard(request): return r
    campaign_id=None
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if not survey: raise HTTPException(404,"Опитування не знайдено")
        if survey.status != "draft": raise HTTPException(409,"Опитування вже було опубліковано або закрито")
        qcount=int(await session.scalar(select(func.count(SurveyQuestion.id)).where(SurveyQuestion.survey_id==survey_id)) or 0)
        if qcount==0: raise HTTPException(400,"Додайте хоча б одне питання")
        survey.status="published"; survey.starts_at=survey.starts_at or clock.storage_utc(); survey.updated_at=clock.storage_utc()
        users=await eligible_users(session, survey)
        text=(f"📋 Нове опитування в АМП: «{survey.title}»\n\n{survey.description[:700]}\n\n🎁 За повне проходження: {survey.xp_reward} XP.\nВідкрий у боті розділ «📋 Опитування», щоб пройти його.")
        campaign_id=await _queue_system_broadcast(session,users,text,author_label=request.session.get("admin_name","web"),audience_label=f"Нове опитування: {survey.title}",template_code="survey_published")
        await log_audit(session,"web_survey_publish",actor_label=request.session.get("admin_name","web"),entity_type="survey",entity_id=survey.id,details=f"Опубліковано; одержувачів {len(users)}")
        await session.commit()
    if campaign_id: _schedule_broadcast(campaign_id)
    return RedirectResponse(f"/admin/surveys/{survey_id}",303)


@router.post("/admin/surveys/{survey_id}/close")
async def survey_close(request: Request, survey_id: int):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if survey: survey.status="closed"; survey.updated_at=clock.storage_utc(); await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}",303)


@router.post("/admin/surveys/{survey_id}/delete")
async def survey_delete(request: Request, survey_id: int):
    if r := guard_permission(request, "surveys.manage"): return r
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if survey:
            question_images = list((await session.scalars(select(SurveyQuestion.image_path).where(SurveyQuestion.survey_id==survey_id, SurveyQuestion.image_path.is_not(None)))).all())
            await session.execute(delete(SurveyResponse).where(SurveyResponse.survey_id==survey_id))
            await session.execute(delete(SurveyAudienceUser).where(SurveyAudienceUser.survey_id==survey_id))
            await session.execute(delete(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id))
            await session.delete(survey); await session.commit()
            for image_path in question_images:
                if image_path:
                    await delete_image(image_path)
    return RedirectResponse("/admin/surveys",303)

