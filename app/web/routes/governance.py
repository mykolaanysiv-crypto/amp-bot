from __future__ import annotations
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from app.governance import record_rule_change
from app.model_domains import GamificationRuleVersion, SystemSetting
from app.time_utils import clock
from app.web.dependencies import ctx, db, guard_superadmin, log_audit, templates

router=APIRouter()
LEAGUE_DEFAULTS={'league.silver_min':100,'league.gold_min':250,'league.platinum_min':500,'league.diamond_min':1000,'league.legendary_min':1500}

async def _league_values(session):
    out={}
    for key,default in LEAGUE_DEFAULTS.items():
        row=await session.get(SystemSetting,f'runtime.{key}')
        try: out[key]=int(row.value) if row else default
        except Exception: out[key]=default
    return out

@router.get('/admin/gamification/governance',response_class=HTMLResponse)
async def governance_page(request:Request):
    if r:=guard_superadmin(request): return r
    async with db.session_factory() as session:
        history=list((await session.scalars(select(GamificationRuleVersion).order_by(GamificationRuleVersion.created_at.desc()).limit(200))).all())
        leagues=await _league_values(session)
        return templates.TemplateResponse(request=request,name='gamification_governance.html',context=ctx(request,history=history,leagues=leagues))

@router.post('/admin/gamification/governance/leagues')
async def league_update(request:Request,reason:str=Form(...),silver:int=Form(...),gold:int=Form(...),platinum:int=Form(...),diamond:int=Form(...),legendary:int=Form(...)):
    if r:=guard_superadmin(request): return r
    vals={'league.silver_min':silver,'league.gold_min':gold,'league.platinum_min':platinum,'league.diamond_min':diamond,'league.legendary_min':legendary}
    ordered=[max(1,int(vals[k])) for k in LEAGUE_DEFAULTS]
    if ordered!=sorted(ordered) or len(set(ordered))!=len(ordered):
        return HTMLResponse('Пороги ліг мають строго зростати.',400)
    async with db.session_factory() as session:
        old=await _league_values(session); actor=request.session.get('admin_name','superadmin'); now=clock.storage_utc()
        for key,value in vals.items():
            row=await session.get(SystemSetting,f'runtime.{key}')
            if row: row.value=str(value); row.updated_at=now
            else: session.add(SystemSetting(key=f'runtime.{key}',value=str(value),updated_at=now))
            await record_rule_change(session,rule_key=key,field_name='threshold',old_value=old[key],new_value=value,author_label=actor,reason=reason,entity_type='league')
        await log_audit(session,'gamification_league_thresholds_update',actor_label=actor,entity_type='gamification',details=reason)
        await session.commit()
    return RedirectResponse('/admin/gamification/governance?saved=1',303)
