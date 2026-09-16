from __future__ import annotations

from fastapi import APIRouter
from .dependencies import (
    Bot, Form, HTMLResponse, HTTPException, LOGIN_LOCK_MINUTES, LOGIN_MAX_ATTEMPTS,
    OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES, PERMISSION_GROUPS, RedirectResponse, Request, User,
    UserRole, WebAdminSession, WebStaffAccount, browser_label, client_ip, clock, ctx, datetime,
    db, dump_permissions, effective_permissions, func, generate_csrf_token, generate_otp,
    generate_session_token, generate_temporary_password, guard, guard_superadmin, hash_password,
    log_audit, logged_in, or_, otp_hash, password_errors, select, session_expiry, settings,
    templates, timedelta, token_hash, token_urlsafe, verify_otp, verify_password, _csrf_token,
)

router = APIRouter()

async def root():
    return RedirectResponse("/admin")


@router.get("/admin", include_in_schema=False)
async def admin_root(request: Request):
    return RedirectResponse("/admin/dashboard" if logged_in(request) else "/admin/login")


async def _audit_auth(action: str, *, actor_label: str, details: str = "", account_id: int | None = None) -> None:
    async with db.session_factory() as session:
        await log_audit(session, action, actor_label=actor_label, entity_type="web_staff_account", entity_id=account_id, details=details)
        await session.commit()


async def _send_web_2fa_code(account: WebStaffAccount, code: str) -> None:
    tg_id = account.two_factor_tg_id
    if not tg_id and account.role == "superadmin" and settings.superadmin_ids:
        tg_id = min(settings.superadmin_ids)
    if not tg_id or not settings.bot_token:
        raise HTTPException(
            status_code=503,
            detail="Для цього акаунта не налаштовано Telegram для двоетапного входу. Зверніться до суперадміністратора.",
        )
    bot = Bot(settings.bot_token)
    try:
        await bot.send_message(
            tg_id,
            "🔐 Код входу в web-панель АМП\n\n"
            f"Код: {code}\n"
            f"Дійсний {OTP_TTL_MINUTES} хв.\n\n"
            "Якщо це не ви — не передавайте код нікому та змініть пароль.",
        )
    finally:
        await bot.session.close()


async def _establish_web_session(request: Request, db_session, account: WebStaffAccount) -> None:
    raw_token = generate_session_token()
    now = clock.storage_utc()
    ua = str(request.headers.get("user-agent") or "")[:500]
    ip = client_ip(list(request.scope.get("headers") or []), request.client.host if request.client else None)
    db_session.add(WebAdminSession(
        account_id=account.id,
        token_hash=token_hash(raw_token),
        user_agent=ua,
        ip_address=ip,
        created_at=now,
        last_seen_at=now,
        expires_at=session_expiry(now),
    ))
    account.last_login_at = now
    account.failed_attempts = 0
    account.locked_until = None
    account.updated_at = now
    await log_audit(
        db_session, "web_login", actor_label=account.display_name,
        entity_type="web_staff_account", entity_id=account.id,
        details=f"Успішний вхід; {browser_label(ua)}",
    )
    await db_session.commit()

    csrf = generate_csrf_token()
    request.session.clear()
    request.session["csrf_token"] = csrf
    request.session["admin_auth"] = True
    request.session["admin_account_id"] = account.id
    request.session["admin_name"] = account.display_name
    request.session["admin_login"] = account.username
    request.session["admin_role"] = account.role
    request.session["admin_permissions"] = sorted(effective_permissions(account.role, account.permissions_json))
    request.session["admin_session_token"] = raw_token


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if logged_in(request):
        return RedirectResponse("/admin/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error=None))


@router.post("/admin/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    now = clock.storage_utc()
    async with db.session_factory() as session:
        account = await session.scalar(select(WebStaffAccount).where(WebStaffAccount.username == username))
        if not account or not account.active:
            await log_audit(session, "web_login_failed", actor_label=f"login:{username or 'порожньо'}", entity_type="web_auth", details="Невідомий або вимкнений акаунт")
            await session.commit()
            return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error="Невірний логін або пароль"), status_code=401)

        if account.locked_until and account.locked_until > now:
            await log_audit(session, "web_login_blocked", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"Блокування до {account.locked_until.isoformat()}")
            await session.commit()
            return templates.TemplateResponse(
                request=request, name="login.html",
                context=ctx(request, error=f"Вхід тимчасово заблоковано після невдалих спроб. Спробуйте після {account.locked_until.strftime('%H:%M')}"),
                status_code=429,
            )

        if not verify_password(password, account.password_hash):
            account.failed_attempts = int(account.failed_attempts or 0) + 1
            remaining = max(0, LOGIN_MAX_ATTEMPTS - account.failed_attempts)
            if account.failed_attempts >= LOGIN_MAX_ATTEMPTS:
                account.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            account.updated_at = now
            await log_audit(
                session, "web_login_failed", actor_label=account.display_name,
                entity_type="web_staff_account", entity_id=account.id,
                details=f"Невірний пароль; спроба {account.failed_attempts}/{LOGIN_MAX_ATTEMPTS}",
            )
            await session.commit()
            error = (
                f"Забагато невдалих спроб. Вхід заблоковано на {LOGIN_LOCK_MINUTES} хв."
                if account.locked_until else f"Невірний логін або пароль. Залишилось спроб: {remaining}."
            )
            return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error=error), status_code=401)

        account.failed_attempts = 0
        account.locked_until = None
        account.updated_at = now
        requires_2fa = account.role == "superadmin" or bool(account.two_factor_enabled)
        if requires_2fa:
            code = generate_otp()
            nonce = token_urlsafe(16)
            try:
                await _send_web_2fa_code(account, code)
            except HTTPException as exc:
                await log_audit(session, "web_2fa_unavailable", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=str(exc.detail))
                await session.commit()
                return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error=str(exc.detail)), status_code=503)
            await log_audit(session, "web_login_password_ok_2fa", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details="Пароль правильний; надіслано одноразовий код")
            await session.commit()
            csrf = _csrf_token(request)
            request.session.clear()
            request.session["csrf_token"] = csrf
            request.session["pending_2fa_account_id"] = account.id
            request.session["pending_2fa_nonce"] = nonce
            request.session["pending_2fa_hash"] = otp_hash(code, nonce)
            request.session["pending_2fa_expires"] = (now + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
            request.session["pending_2fa_attempts"] = 0
            return RedirectResponse("/admin/login/2fa", status_code=303)

        await _establish_web_session(request, session, account)
        target = "/admin/account/password?required=1" if account.must_change_password else "/admin/dashboard"
        return RedirectResponse(target, status_code=303)


@router.get("/admin/login/2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request):
    if not request.session.get("pending_2fa_account_id"):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request=request, name="login_2fa.html", context=ctx(request, error=None))


@router.post("/admin/login/2fa", response_class=HTMLResponse)
async def login_2fa(request: Request, code: str = Form(...)):
    account_id = request.session.get("pending_2fa_account_id")
    nonce = str(request.session.get("pending_2fa_nonce") or "")
    expected = str(request.session.get("pending_2fa_hash") or "")
    expires_raw = str(request.session.get("pending_2fa_expires") or "")
    attempts = int(request.session.get("pending_2fa_attempts") or 0)
    if not account_id or not nonce or not expected:
        return RedirectResponse("/admin/login", status_code=303)
    try:
        expires = datetime.fromisoformat(expires_raw)
    except ValueError:
        expires = datetime.min
    if clock.storage_utc() > expires:
        csrf = _csrf_token(request)
        request.session.clear(); request.session["csrf_token"] = csrf
        return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error="Код двоетапного входу застарів. Увійдіть ще раз."), status_code=401)

    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id))
        if not account or not account.active:
            return RedirectResponse("/admin/login", status_code=303)
        if not verify_otp(code, nonce, expected):
            attempts += 1
            request.session["pending_2fa_attempts"] = attempts
            await log_audit(session, "web_2fa_failed", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"Невірний одноразовий код; спроба {attempts}/{OTP_MAX_ATTEMPTS}")
            await session.commit()
            if attempts >= OTP_MAX_ATTEMPTS:
                csrf = _csrf_token(request)
                request.session.clear(); request.session["csrf_token"] = csrf
                return templates.TemplateResponse(request=request, name="login.html", context=ctx(request, error="Забагато невдалих кодів двоетапного входу. Увійдіть заново."), status_code=401)
            return templates.TemplateResponse(request=request, name="login_2fa.html", context=ctx(request, error=f"Невірний код. Залишилось спроб: {OTP_MAX_ATTEMPTS-attempts}."), status_code=401)
        await log_audit(session, "web_2fa_success", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details="Двоетапний вхід підтверджено")
        await _establish_web_session(request, session, account)
        target = "/admin/account/password?required=1" if account.must_change_password else "/admin/dashboard"
        return RedirectResponse(target, status_code=303)


@router.post("/admin/logout")
async def logout(request: Request):
    raw_token = str(request.session.get("admin_session_token") or "")
    actor = request.session.get("admin_name", "web")
    account_id = request.session.get("admin_account_id")
    if raw_token:
        async with db.session_factory() as session:
            row = await session.scalar(select(WebAdminSession).where(WebAdminSession.token_hash == token_hash(raw_token)))
            if row and row.revoked_at is None:
                row.revoked_at = clock.storage_utc()
            await log_audit(session, "web_logout", actor_label=actor, entity_type="web_staff_account", entity_id=account_id, details="Сесію завершено користувачем")
            await session.commit()
    request.session.clear()
    request.session["csrf_token"] = generate_csrf_token()
    return RedirectResponse("/admin/login", status_code=303)


async def _account_security_context(request: Request, *, error: str | None = None, success: str | None = None, required: bool = False):
    account_id = request.session.get("admin_account_id")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id)) if account_id else None
        sessions = []
        if account:
            sessions = list((await session.scalars(
                select(WebAdminSession).where(
                    WebAdminSession.account_id == account.id,
                    WebAdminSession.revoked_at.is_(None),
                ).order_by(WebAdminSession.last_seen_at.desc())
            )).all())
    current_hash = token_hash(str(request.session.get("admin_session_token") or ""))
    return ctx(
        request, account=account, web_sessions=sessions, current_session_hash=current_hash,
        browser_label=browser_label, error=error, success=success, password_required=required,
    )


@router.get("/admin/account", response_class=HTMLResponse)
async def account_security(request: Request):
    if r := guard(request): return r
    context = await _account_security_context(request)
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@router.get("/admin/account/password", response_class=HTMLResponse)
async def account_password_page(request: Request, required: int = 0):
    if r := guard(request): return r
    context = await _account_security_context(request, required=bool(required))
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@router.post("/admin/account/password", response_class=HTMLResponse)
async def account_password_change(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if r := guard(request): return r
    account_id = request.session.get("admin_account_id")
    raw_token = str(request.session.get("admin_session_token") or "")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id)) if account_id else None
        if not account:
            request.session.clear()
            return RedirectResponse("/admin/login", 303)
        if not verify_password(current_password, account.password_hash):
            await log_audit(session, "web_password_change_failed", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details="Невірний поточний пароль")
            await session.commit()
            context = await _account_security_context(request, error="Поточний пароль введено неправильно.", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        if new_password != confirm_password:
            context = await _account_security_context(request, error="Новий пароль і підтвердження не збігаються.", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        errors = password_errors(new_password, username=account.username)
        if errors:
            context = await _account_security_context(request, error="Пароль не відповідає вимогам: " + ", ".join(errors) + ".", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        if verify_password(new_password, account.password_hash):
            context = await _account_security_context(request, error="Новий пароль має відрізнятися від поточного.", required=account.must_change_password)
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        account.password_hash = hash_password(new_password)
        account.must_change_password = False
        account.password_changed_at = clock.storage_utc()
        account.updated_at = clock.storage_utc()
        # Password change invalidates all other devices, while the current one stays active.
        current_hash = token_hash(raw_token)
        other_sessions = (await session.scalars(select(WebAdminSession).where(
            WebAdminSession.account_id == account.id,
            WebAdminSession.revoked_at.is_(None),
            WebAdminSession.token_hash != current_hash,
        ))).all()
        for row in other_sessions:
            row.revoked_at = clock.storage_utc()
        await log_audit(session, "web_password_changed", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"Пароль змінено; завершено інших сесій: {len(other_sessions)}")
        await session.commit()
    context = await _account_security_context(request, success="Пароль успішно змінено. Інші активні сесії завершено.")
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@router.post("/admin/account/2fa", response_class=HTMLResponse)
async def account_2fa_update(request: Request, enabled: str = Form(""), telegram_id: str = Form("")):
    if r := guard(request): return r
    account_id = request.session.get("admin_account_id")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, int(account_id)) if account_id else None
        if not account:
            return RedirectResponse("/admin/login", 303)
        want_enabled = bool(enabled) or account.role == "superadmin"
        tg_id = None
        if telegram_id.strip():
            try:
                tg_id = int(telegram_id.strip())
            except ValueError:
                context = await _account_security_context(request, error="Telegram ID має бути числом.")
                return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        if want_enabled and not tg_id:
            tg_id = account.two_factor_tg_id or (min(settings.superadmin_ids) if account.role == "superadmin" and settings.superadmin_ids else None)
        if want_enabled and not tg_id:
            context = await _account_security_context(request, error="Для двоетапного входу потрібно вказати ідентифікатор Telegram.")
            return templates.TemplateResponse(request=request, name="account_security.html", context=context, status_code=400)
        account.two_factor_enabled = want_enabled
        account.two_factor_tg_id = tg_id if want_enabled else None
        account.updated_at = clock.storage_utc()
        await log_audit(session, "web_2fa_settings", actor_label=account.display_name, entity_type="web_staff_account", entity_id=account.id, details=f"enabled={account.two_factor_enabled}; telegram_id={'set' if account.two_factor_tg_id else 'none'}")
        await session.commit()
    context = await _account_security_context(request, success="Налаштування двоетапного входу збережено.")
    return templates.TemplateResponse(request=request, name="account_security.html", context=context)


@router.post("/admin/account/sessions/{session_id}/revoke")
async def account_session_revoke(request: Request, session_id: int):
    if r := guard(request): return r
    account_id = int(request.session.get("admin_account_id") or 0)
    raw_token = str(request.session.get("admin_session_token") or "")
    async with db.session_factory() as session:
        row = await session.get(WebAdminSession, session_id)
        if not row or row.account_id != account_id:
            raise HTTPException(status_code=404, detail="Сесію не знайдено")
        row.revoked_at = clock.storage_utc()
        await log_audit(session, "web_session_revoked", actor_label=request.session.get("admin_name", "web"), entity_type="web_admin_session", entity_id=row.id, details="Сесію завершено з профілю")
        await session.commit()
        is_current = row.token_hash == token_hash(raw_token)
    if is_current:
        request.session.clear(); request.session["csrf_token"] = generate_csrf_token()
        return RedirectResponse("/admin/login", 303)
    return RedirectResponse("/admin/account", 303)


async def _security_accounts_context(request: Request, *, temp_password: str | None = None, temp_username: str | None = None, success: str | None = None):
    async with db.session_factory() as session:
        accounts = list((await session.scalars(select(WebStaffAccount).order_by(WebStaffAccount.role.desc(), WebStaffAccount.display_name.asc()))).all())
        active_counts = {}
        for account in accounts:
            active_counts[account.id] = int(await session.scalar(select(func.count(WebAdminSession.id)).where(
                WebAdminSession.account_id == account.id,
                WebAdminSession.revoked_at.is_(None),
                or_(WebAdminSession.expires_at.is_(None), WebAdminSession.expires_at > clock.storage_utc()),
            )) or 0)
        telegram_staff = list((await session.scalars(
            select(User).where(User.role.in_([UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value]))
            .order_by(User.role.desc(), User.full_name.asc())
        )).all())
    return ctx(
        request, staff_accounts=accounts, telegram_staff=telegram_staff, active_session_counts=active_counts,
        permission_groups=PERMISSION_GROUPS, effective_permissions=effective_permissions,
        temp_password=temp_password, temp_username=temp_username, success=success, now=clock.storage_utc(),
    )


@router.get("/admin/security", response_class=HTMLResponse)
async def security_accounts(request: Request):
    if r := guard_superadmin(request): return r
    return templates.TemplateResponse(request=request, name="security_accounts.html", context=await _security_accounts_context(request))


@router.post("/admin/security/accounts/{account_id}/permissions")
async def security_account_permissions(request: Request, account_id: int):
    if r := guard_superadmin(request): return r
    form = await request.form()
    selected = [str(value) for value in form.getlist("permissions")]
    mode = str(form.get("mode") or "custom")
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Акаунт не знайдено")
        if account.role == UserRole.SUPERADMIN.value:
            account.permissions_json = None
            note = "Суперадміністратор: повний доступ незмінний"
        elif mode == "inherit":
            account.permissions_json = None
            note = "права=налаштування_ролі"
        else:
            account.permissions_json = dump_permissions(selected)
            note = f"права={account.permissions_json}"
        account.updated_at = clock.storage_utc()
        await log_audit(session, "web_permissions_update", actor_label=request.session.get("admin_name", "web"), entity_type="web_staff_account", entity_id=account.id, details=note)
        await session.commit()
    return RedirectResponse("/admin/security", 303)


@router.post("/admin/security/telegram/{user_id}/permissions")
async def security_telegram_permissions(request: Request, user_id: int):
    if r := guard_superadmin(request): return r
    form = await request.form()
    selected = [str(value) for value in form.getlist("permissions")]
    mode = str(form.get("mode") or "custom")
    async with db.session_factory() as session:
        user = await session.get(User, user_id)
        if not user or user.role not in {UserRole.COORDINATOR.value, UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
            raise HTTPException(status_code=404, detail="Працівника не знайдено")
        if user.role == UserRole.SUPERADMIN.value:
            user.staff_permissions_json = None
            note = "Суперадміністратор: повний доступ незмінний"
        elif mode == "inherit":
            user.staff_permissions_json = None
            note = "права=налаштування_ролі"
        else:
            user.staff_permissions_json = dump_permissions(selected)
            note = f"права={user.staff_permissions_json}"
        await log_audit(session, "telegram_permissions_update", actor_label=request.session.get("admin_name", "web"), entity_type="user", entity_id=user.id, details=note)
        await session.commit()
    return RedirectResponse("/admin/security", 303)


@router.post("/admin/security/accounts/{account_id}/reset-password", response_class=HTMLResponse)
async def security_reset_password(request: Request, account_id: int):
    if r := guard_superadmin(request): return r
    temp_password = generate_temporary_password()
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Акаунт не знайдено")
        account.password_hash = hash_password(temp_password)
        account.must_change_password = True
        account.failed_attempts = 0
        account.locked_until = None
        account.password_changed_at = clock.storage_utc()
        account.updated_at = clock.storage_utc()
        rows = (await session.scalars(select(WebAdminSession).where(WebAdminSession.account_id == account.id, WebAdminSession.revoked_at.is_(None)))).all()
        for row in rows:
            row.revoked_at = clock.storage_utc()
        await log_audit(session, "web_password_reset", actor_label=request.session.get("admin_name", "web"), entity_type="web_staff_account", entity_id=account.id, details=f"Створено тимчасовий пароль; завершено сесій: {len(rows)}")
        await session.commit()
        username = account.username
    context = await _security_accounts_context(request, temp_password=temp_password, temp_username=username, success="Тимчасовий пароль створено. Покажіть його користувачу один раз безпечним каналом.")
    return templates.TemplateResponse(request=request, name="security_accounts.html", context=context)


@router.post("/admin/security/accounts/{account_id}/sessions/revoke-all")
async def security_revoke_all_sessions(request: Request, account_id: int):
    if r := guard_superadmin(request): return r
    current_account_id = int(request.session.get("admin_account_id") or 0)
    async with db.session_factory() as session:
        account = await session.get(WebStaffAccount, account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Акаунт не знайдено")
        rows = (await session.scalars(select(WebAdminSession).where(WebAdminSession.account_id == account.id, WebAdminSession.revoked_at.is_(None)))).all()
        for row in rows:
            row.revoked_at = clock.storage_utc()
        await log_audit(session, "web_sessions_revoke_all", actor_label=request.session.get("admin_name", "web"), entity_type="web_staff_account", entity_id=account.id, details=f"Завершено сесій: {len(rows)}")
        await session.commit()
    if account_id == current_account_id:
        request.session.clear(); request.session["csrf_token"] = generate_csrf_token()
        return RedirectResponse("/admin/login", 303)
    return RedirectResponse("/admin/security", 303)
