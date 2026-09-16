from __future__ import annotations

from .dependencies import (
    APP_VERSION, BROADCAST_TEMPLATES, BroadcastCampaign, BroadcastRecipient, BroadcastTemplate,
    Event, HTTPException, Request, SystemSetting, User, UserStatus, asyncio, clock, ctx, db,
    hashlib, job_lock, log_audit, log_extra, logging, or_, personalize_message,
    queue_telegram_delivery, select, update, template_options, datetime,
)

_broadcast_tasks: set[asyncio.Task] = set()

def _track_broadcast_task(task: asyncio.Task) -> None:
    _broadcast_tasks.add(task)
    task.add_done_callback(_broadcast_tasks.discard)

def _schedule_broadcast(campaign_id: int) -> None:
    _track_broadcast_task(asyncio.create_task(_deliver_broadcast_campaign(campaign_id), name=f"broadcast_{campaign_id}"))

async def _queue_system_broadcast(
    session,
    users: list[User],
    message_text: str,
    *,
    author_label: str,
    audience_label: str,
    template_code: str,
) -> None:
    """Queue system audience messages in the canonical v1.9 Notification Center.

    The legacy BroadcastCampaign tables stay available for manual communication
    campaigns and historical audit, but automatic entity notices no longer create
    a parallel delivery pipeline.
    """
    unique: dict[int, User] = {}
    for user in users:
        if user and user.tg_id and user.status == UserStatus.ACTIVE.value:
            unique[user.id] = user
    recipients = list(unique.values())
    if not recipients:
        return None
    digest = hashlib.sha256(message_text.strip().encode("utf-8")).hexdigest()[:16]
    for user in recipients:
        await queue_telegram_delivery(
            session, user.tg_id, message_text.strip(),
            source=template_code or "system",
            title=audience_label[:180],
            recipient_user_id=user.id,
            dedupe_key=f"system_notice:{template_code}:{digest}:user:{user.id}",
        )
    return None

def _entity_notice_text(entity_label: str, title: str, reason: str, *, deleted: bool = False) -> str:
    reason = (reason or "").strip()
    action = "скасовано та видалено із системи" if deleted else "скасовано"
    return (
        f"⚠️ {entity_label} «{title}» {action}.\n\n"
        f"Вибачте, {entity_label.lower()} «{title}» {action} через: {reason}.\n\n"
        "Прийміть наші вибачення. Дякуємо за розуміння 💙"
    )

def _postponed_notice_text(entity_label: str, title: str, new_at: datetime, reason: str) -> str:
    return (
        f"📅 {entity_label} «{title}» перенесено.\n\n"
        f"Нова актуальна дата та час: <b>{new_at.strftime('%d.%m.%Y о %H:%M')}</b>.\n"
        f"Причина: {reason.strip()}.\n\n"
        "Перепрошуємо за зміни та дякуємо за розуміння 💙"
    )

async def _retire_legacy_version_broadcasts() -> None:
    """Stop queued legacy `system_update` campaigns before recovery.

    v1.8.2.4 and older delivered version notices through BroadcastCampaign. If
    a deploy restarted while such a campaign was still queued/sending, startup
    recovery could resume it and the new startup notifier could create another
    notice. v1.8.2.5 uses the deduplicated outbox instead, so unfinished legacy
    version campaigns are explicitly retired before `_recover_pending_broadcasts`.
    """
    try:
        async with db.session_factory() as session:
            ids = list((await session.scalars(
                select(BroadcastCampaign.id).where(
                    BroadcastCampaign.source == "system",
                    BroadcastCampaign.template_code == "system_update",
                    BroadcastCampaign.status.in_(["queued", "sending"]),
                )
            )).all())
            if not ids:
                return
            now = clock.storage_utc()
            await session.execute(
                update(BroadcastCampaign)
                .where(BroadcastCampaign.id.in_(ids))
                .values(status="completed_with_errors", completed_at=now)
            )
            await session.execute(
                update(BroadcastRecipient)
                .where(
                    BroadcastRecipient.campaign_id.in_(ids),
                    BroadcastRecipient.status.in_(["pending", "retry"]),
                )
                .values(
                    status="failed",
                    next_retry_at=None,
                    error_text="Superseded by idempotent version outbox v1.8.2.5",
                )
            )
            await log_audit(
                session,
                "legacy_version_broadcast_retired",
                actor_label="Система АМП",
                entity_type="broadcast",
                details=f"Зупинено незавершених legacy version campaigns: {len(ids)}.",
            )
            await session.commit()
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "Не вдалося завершити legacy version campaigns",
            extra=log_extra("LEGACY_VERSION_CAMPAIGN_RETIRE_FAILED", exception_type=type(exc).__name__),
        )

async def _announce_version_update() -> None:
    """Notify participants once per deployed APP_VERSION across concurrent dynos.

    The database lease closes the race where two startup processes both read the
    previous SystemSetting before either one commits, which used to create two
    identical version broadcasts.
    """
    try:
        async with job_lock(db, f"version_announce:{APP_VERSION}", ttl_seconds=300) as acquired:
            if not acquired:
                return
            await _announce_version_update_locked()
    except Exception as exc:
        logging.getLogger(__name__).exception(
            "Не вдалося підготувати одноразове повідомлення про версію",
            extra=log_extra("VERSION_ANNOUNCEMENT_PREPARE_FAILED", version=APP_VERSION, exception_type=type(exc).__name__),
        )

async def _announce_version_update_locked() -> None:
    """Queue exactly one version notice per participant and APP_VERSION.

    Older releases created a normal BroadcastCampaign at startup. In practice a
    campaign could be recovered/scheduled by more than one startup path, which
    made duplicate version messages possible. Version announcements now use the
    durable Telegram outbox directly with a UNIQUE per-user dedupe key.

    Idempotency layers:
      1. distributed startup job lock;
      2. SystemSetting last_announced_app_version;
      3. UNIQUE notification_deliveries.dedupe_key per version + user.
    """
    async with db.session_factory() as session:
        state = await session.get(SystemSetting, "last_announced_app_version")
        if state and state.value == APP_VERSION:
            return

        users = list((await session.scalars(
            select(User).where(
                User.status == UserStatus.ACTIVE.value,
                User.tg_id.is_not(None),
            ).order_by(User.id.asc())
        )).all())

        message = (
            f"🔄 АМПасадори оновлено до версії v{APP_VERSION}!\n\n"
            "Ми оновили Telegram-бот і систему АМП: додали нові можливості та виправлення. "
            "Усі ваші XP, реєстрації та історія активності збережені.\n\n"
            "Щоб побачити актуальне меню, натисніть /menu або /start. 💙"
        )
        queued = 0
        for user in users:
            row = await queue_telegram_delivery(
                session,
                user.tg_id,
                message,
                source="system_version_update",
                dedupe_key=f"system_version_update:{APP_VERSION}:user:{user.id}",
                parse_mode="HTML",
            )
            if row is not None:
                queued += 1

        now = clock.storage_utc()
        if state:
            state.value = APP_VERSION
            state.updated_at = now
        else:
            session.add(SystemSetting(key="last_announced_app_version", value=APP_VERSION, updated_at=now))
        await log_audit(
            session,
            "system_version_update",
            actor_label="Система АМП",
            entity_type="system",
            details=(
                f"Зафіксовано запуск версії v{APP_VERSION}; "
                f"активних одержувачів: {len(users)}; outbox записів: {queued}."
            ),
        )
        await session.commit()

async def _recover_pending_broadcasts() -> None:
    """Resume queued/interrupted campaigns after a dyno restart or deploy."""
    try:
        async with db.session_factory() as session:
            ids = (await session.scalars(
                select(BroadcastCampaign.id).where(BroadcastCampaign.status.in_(["queued", "sending"]))
            )).all()
        for campaign_id in ids:
            _schedule_broadcast(int(campaign_id))
    except Exception as exc:
        # A fresh database may be in the middle of its first startup. The next
        # manually created campaign still works; do not block the whole app.
        logging.getLogger("amp.broadcast_resume").warning(
            "Не вдалося відновити queued/sending broadcast campaigns",
            extra=log_extra("BROADCAST_RESUME_FAILED", exception_type=type(exc).__name__),
        )

async def _broadcast_retry_scheduler() -> None:
    """Resume due broadcast recipients without waiting for a dyno restart."""
    log = logging.getLogger("amp.broadcast_retry")
    while True:
        try:
            async with job_lock(db, "broadcast_retry_scan", ttl_seconds=45) as acquired:
                if acquired:
                    now = clock.storage_utc()
                    async with db.session_factory() as session:
                        campaign_ids = list((await session.scalars(
                            select(BroadcastRecipient.campaign_id)
                            .join(BroadcastCampaign, BroadcastCampaign.id == BroadcastRecipient.campaign_id)
                            .where(
                                BroadcastCampaign.status.in_(["queued", "sending"]),
                                BroadcastRecipient.status.in_(["pending", "retry"]),
                                or_(BroadcastRecipient.next_retry_at.is_(None), BroadcastRecipient.next_retry_at <= now),
                            )
                            .distinct()
                            .limit(50)
                        )).all())
                    for campaign_id in campaign_ids:
                        _schedule_broadcast(int(campaign_id))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception(
                "Помилка retry-сканера розсилок: %s", exc,
                extra=log_extra("BROADCAST_RETRY_SCAN_FAILED", exception_type=type(exc).__name__),
            )
        await asyncio.sleep(60)

async def _deliver_broadcast_campaign(campaign_id: int) -> None:
    """Queue every manual broadcast recipient into the canonical Notification Center.

    Delivery itself is performed by the same retry worker as reminders, cases,
    surveys and system messages. BroadcastCampaign/BroadcastRecipient remain as
    campaign/audience history and are synchronized from Notification results.
    """
    async with job_lock(db, f"broadcast:{campaign_id}", ttl_seconds=240) as acquired:
        if not acquired:
            return
        async with db.session_factory() as session:
            campaign = await session.get(BroadcastCampaign, campaign_id)
            if not campaign or campaign.status in {"completed", "completed_with_errors", "failed"}:
                return
            campaign.status = "sending"
            campaign.started_at = campaign.started_at or clock.storage_utc()
            campaign.completed_at = None
            rows = (await session.execute(
                select(BroadcastRecipient, User)
                .join(User, User.id == BroadcastRecipient.user_id)
                .where(
                    BroadcastRecipient.campaign_id == campaign_id,
                    BroadcastRecipient.status.in_(["pending", "retry"]),
                )
                .order_by(BroadcastRecipient.id.asc())
            )).all()
            for recipient, user in rows:
                text = personalize_message(campaign.message_text, user)
                if len(text) > 4096:
                    recipient.status = "failed"
                    recipient.error_text = "Повідомлення після персоналізації перевищує 4096 символів"
                    recipient.next_retry_at = None
                    continue
                await queue_telegram_delivery(
                    session, recipient.recipient_tg_id, text,
                    source="broadcast", notification_type="broadcast", title=f"Розсилка №{campaign.id}",
                    recipient_user_id=user.id, entity_type="broadcast_recipient", entity_id=recipient.id,
                    dedupe_key=f"broadcast:{campaign.id}:recipient:{recipient.id}", parse_mode=None,
                )
                recipient.status = "pending"
                recipient.error_text = ""
                recipient.next_retry_at = None
            await session.commit()

def _clean_broadcast_text(text: str, template_code: str | None = None) -> str:
    value = (text or "").strip()
    if not value and template_code in BROADCAST_TEMPLATES:
        value = BROADCAST_TEMPLATES[template_code]["text"]
    if not value:
        raise HTTPException(status_code=400, detail="Напишіть текст повідомлення або оберіть шаблон.")
    if len(value) > 3800:
        raise HTTPException(status_code=400, detail="Повідомлення завелике. Скоротіть текст до 3800 символів.")
    return value

async def _broadcast_form_context(session, request: Request, **extra):
    settlements = [x for x in (await session.scalars(
        select(User.settlement)
        .where(User.status == UserStatus.ACTIVE.value, User.settlement.is_not(None), User.settlement != "")
        .distinct()
        .order_by(User.settlement.asc())
    )).all() if x]
    events = (await session.scalars(select(Event).order_by(Event.starts_at.desc()).limit(100))).all()
    campaigns = (await session.scalars(
        select(BroadcastCampaign).order_by(BroadcastCampaign.created_at.desc()).limit(30)
    )).all()
    custom_templates = list((await session.scalars(
        select(BroadcastTemplate).order_by(BroadcastTemplate.active.desc(), BroadcastTemplate.title.asc())
    )).all())
    available_templates = template_options() + [
        (f"custom:{item.id}", f"⭐ {item.title}", item.text)
        for item in custom_templates if item.active
    ]
    data = {
        "settlements": settlements,
        "events": events,
        "campaigns": campaigns,
        "broadcast_templates": available_templates,
        "custom_templates": custom_templates,
        "preview": None,
        "form_data": {},
    }
    data.update(extra)
    return ctx(request, **data)
