from __future__ import annotations

from fastapi import APIRouter
from app.web.app import *  # noqa: F401,F403 - transitional shared web dependencies
from app.content_views import content_view_stat, content_view_stats
from app.web.app import (
    _refresh_lifecycle, _queue_system_broadcast, _entity_notice_text, _postponed_notice_text,
    _schedule_broadcast, _clean_broadcast_text, _broadcast_form_context,
)

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
        if period in cutoff_map: stmt=stmt.where(Survey.created_at >= datetime.utcnow()-timedelta(days=cutoff_map[period]))
        if type == "rewarded": stmt=stmt.where(Survey.xp_reward > 0)
        elif type == "no_reward": stmt=stmt.where(Survey.xp_reward == 0)
        order_map={"oldest":Survey.created_at.asc(),"title":Survey.title.asc(),"deadline":Survey.ends_at.asc().nullslast(),"newest":Survey.created_at.desc()}
        rows=list((await session.scalars(stmt.order_by(order_map.get(sort,Survey.created_at.desc())))).all())
        counts = {sid: int(c or 0) for sid, c in (await session.execute(select(SurveyResponse.survey_id, func.count(SurveyResponse.id)).group_by(SurveyResponse.survey_id))).all()}
        qcounts = {sid: int(c or 0) for sid, c in (await session.execute(select(SurveyQuestion.survey_id, func.count(SurveyQuestion.id)).group_by(SurveyQuestion.survey_id))).all()}
        view_stats = await content_view_stats(session, "survey", [item.id for item in rows])
    return templates.TemplateResponse(request=request,name="surveys.html",context=ctx(request,rows=rows,counts=counts,qcounts=qcounts,view_stats=view_stats,q=q,status=status,period=period,type=type,sort=sort))


@router.post("/admin/surveys/create")
async def survey_create(request: Request, title: str=Form(...), description: str=Form(""), xp_reward: int=Form(0), ends_at: str=Form("")):
    if r := guard(request): return r
    title = title.strip()
    if not title: raise HTTPException(400, "Вкажіть назву опитування")
    deadline = datetime.fromisoformat(ends_at) if (ends_at or "").strip() else None
    async with db.session_factory() as session:
        row = Survey(title=title, description=description.strip(), xp_reward=max(0,min(40,int(xp_reward or 0))), status="draft", ends_at=deadline, created_by_label=request.session.get("admin_name","web"), updated_at=datetime.utcnow())
        session.add(row); await session.flush()
        await log_audit(session,"web_survey_create",actor_label=request.session.get("admin_name","web"),entity_type="survey",entity_id=row.id,details=row.title)
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
    return templates.TemplateResponse(
        request=request, name="survey_detail.html",
        context=ctx(request, survey=survey, questions=questions, responses=responses, stats=stats, decoded_answers=decoded_answers, view_stat=view_stat),
    )


@router.post("/admin/surveys/{survey_id}/update")
async def survey_update(request: Request, survey_id: int, title: str=Form(...), description: str=Form(""), xp_reward: int=Form(0), ends_at: str=Form("")):
    if r := guard(request): return r
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if not survey: raise HTTPException(404,"Опитування не знайдено")
        survey.title=title.strip(); survey.description=description.strip(); survey.xp_reward=max(0,min(40,int(xp_reward or 0))); survey.ends_at=datetime.fromisoformat(ends_at) if (ends_at or '').strip() else None; survey.updated_at=datetime.utcnow()
        await log_audit(session,"web_survey_update",actor_label=request.session.get("admin_name","web"),entity_type="survey",entity_id=survey.id,details=survey.title)
        await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}",303)


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
        survey.status="published"; survey.starts_at=survey.starts_at or datetime.utcnow(); survey.updated_at=datetime.utcnow()
        users=list((await session.scalars(select(User).where(User.status==UserStatus.ACTIVE.value,User.tg_id.is_not(None)).order_by(User.id))).all())
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
        if survey: survey.status="closed"; survey.updated_at=datetime.utcnow(); await session.commit()
    return RedirectResponse(f"/admin/surveys/{survey_id}",303)


@router.post("/admin/surveys/{survey_id}/delete")
async def survey_delete(request: Request, survey_id: int):
    if r := guard_permission(request, "surveys.manage"): return r
    async with db.session_factory() as session:
        survey=await session.get(Survey,survey_id)
        if survey:
            question_images = list((await session.scalars(select(SurveyQuestion.image_path).where(SurveyQuestion.survey_id==survey_id, SurveyQuestion.image_path.is_not(None)))).all())
            await session.execute(delete(SurveyResponse).where(SurveyResponse.survey_id==survey_id))
            await session.execute(delete(SurveyQuestion).where(SurveyQuestion.survey_id==survey_id))
            await session.delete(survey); await session.commit()
            for image_path in question_images:
                if image_path:
                    await delete_image(image_path)
    return RedirectResponse("/admin/surveys",303)

