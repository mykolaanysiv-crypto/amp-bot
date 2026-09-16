from __future__ import annotations

from .time_utils import clock

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from alembic.config import Config
from alembic.script import ScriptDirectory

from .models import SystemSetting
from .observability import log_extra

log = logging.getLogger(__name__)

# Heartbeats deliberately live in the existing SystemSetting table so v1.12.1
# can improve production observability without a schema delta during the
# transitional Alembic adoption period.
HEARTBEAT_PREFIX = "runtime.heartbeat."
ALERT_PREFIX = "runtime.alert."

# Scheduler heartbeat freshness. The values are intentionally larger than the
# normal sleep intervals so planned sleeps are never treated as failures.
# A scheduler writes its own heartbeat at the beginning of every loop.
SCHEDULER_MAX_SILENCE_SECONDS: dict[str, int] = {
    "birthday_scheduler": 26 * 3600,
    "event_reminder_scheduler": 15 * 60,
    "event_feedback_scheduler": 45 * 60,
    "goal_reward_scheduler": 20 * 60,
    "streak_scheduler": 45 * 60,
    "notification_retry_scheduler": 3 * 60,
    "participant_inactivity_scheduler": 3 * 3600,
    "smart_opportunities_scheduler": 45 * 60,
    "season_history_scheduler": 3 * 3600,
    "donation_sync_scheduler": 20 * 60,
    "notification_health_scheduler": 20 * 60,
    "backup_health_scheduler": 7 * 3600,
    "content_lifecycle_scheduler": 20 * 60,
}

SCHEDULER_LABELS: dict[str, str] = {
    "birthday_scheduler": "Дні народження",
    "event_reminder_scheduler": "Нагадування про події",
    "event_feedback_scheduler": "Зворотний зв’язок після подій",
    "goal_reward_scheduler": "Цілі та нагороди",
    "streak_scheduler": "Серії участі",
    "notification_retry_scheduler": "Доставка Telegram-повідомлень",
    "participant_inactivity_scheduler": "Неактивні учасники",
    "smart_opportunities_scheduler": "Розумні можливості",
    "season_history_scheduler": "Історія сезонів",
    "donation_sync_scheduler": "Синхронізація донатів",
    "notification_health_scheduler": "Контроль сповіщень",
    "backup_health_scheduler": "Контроль резервних копій",
    "content_lifecycle_scheduler": "Автооновлення статусів",
}


@dataclass(slots=True)
class HeartbeatState:
    component: str
    status: str
    at: datetime | None
    started_at: datetime | None
    error: str
    age_seconds: float | None
    healthy: bool
    missing: bool = False


def _key(component: str) -> str:
    return f"{HEARTBEAT_PREFIX}{component}"[:120]


def _alert_key(component: str) -> str:
    # SystemSetting.key is varchar(120).
    return f"{ALERT_PREFIX}{component}"[:120]


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return clock.ensure_utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError):
        return None


def _decode_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        # Backward-compatible fallback if an operator ever recorded a raw ISO
        # timestamp while debugging.
        parsed = _parse_dt(raw)
        return {"at": parsed.isoformat() if parsed else ""}


async def _upsert_setting(session, key: str, value: str, *, now: datetime) -> None:
    result = await session.execute(
        update(SystemSetting)
        .where(SystemSetting.key == key)
        .values(value=value, updated_at=now)
    )
    if result.rowcount:
        return
    try:
        async with session.begin_nested():
            session.add(SystemSetting(key=key, value=value, updated_at=now))
            await session.flush()
    except IntegrityError:
        # Two dynos may create the same heartbeat marker concurrently during a
        # deploy. The winner is irrelevant; update the existing row.
        await session.execute(
            update(SystemSetting)
            .where(SystemSetting.key == key)
            .values(value=value, updated_at=now)
        )


async def record_heartbeat(
    db,
    component: str,
    *,
    status: str = "running",
    error: str = "",
    started_at: datetime | None = None,
    boot_id: str | None = None,
) -> None:
    now_utc = clock.now_utc()
    storage_now = clock.storage_utc(now_utc)
    key = _key(component)
    async with db.session_factory() as session:
        existing = await session.get(SystemSetting, key)
        previous = _decode_payload(existing.value if existing else None)
        payload = {
            "at": now_utc.isoformat(),
            "status": (status or "running")[:32],
            "error": (error or "")[:500],
            "started_at": (
                clock.ensure_utc(started_at).isoformat()
                if started_at
                else str(previous.get("started_at") or now_utc.isoformat())
            ),
            "boot_id": boot_id or str(previous.get("boot_id") or ""),
        }
        await _upsert_setting(
            session,
            key,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            now=storage_now,
        )
        await session.commit()


async def heartbeat_loop(
    db,
    component: str,
    *,
    interval_seconds: int = 30,
    initial_status: str = "running",
) -> None:
    """Persist a component heartbeat until cancelled.

    This loop is intentionally tiny and database-only. It never calls Telegram
    or an external provider, so a fresh worker marker remains a strong signal
    that the process and PostgreSQL connection are alive.
    """
    started_at = clock.now_utc()
    boot_id = uuid.uuid4().hex[:12]
    status = initial_status
    try:
        while True:
            try:
                await record_heartbeat(
                    db,
                    component,
                    status=status,
                    started_at=started_at,
                    boot_id=boot_id,
                )
                status = "running"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A heartbeat must never become the reason a healthy web/worker
                # process dies during a short database interruption.
                log.exception(
                    "Не вдалося оновити heartbeat для %s", component,
                    extra=log_extra("HEARTBEAT_WRITE_FAILED", component=component, exception_type=type(exc).__name__),
                )
            await asyncio.sleep(max(5, int(interval_seconds)))
    except asyncio.CancelledError:
        try:
            await record_heartbeat(
                db,
                component,
                status="stopping",
                started_at=started_at,
                boot_id=boot_id,
            )
        except Exception as exc:
            log.exception(
                "Не вдалося записати фінальний heartbeat для %s", component,
                extra=log_extra("HEARTBEAT_FINAL_WRITE_FAILED", component=component, exception_type=type(exc).__name__),
            )
        raise


async def scheduler_heartbeat(db, scheduler_name: str, *, status: str = "running", error: str = "") -> None:
    try:
        await record_heartbeat(db, f"scheduler:{scheduler_name}", status=status, error=error)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Scheduler work already has its own database/error handling. Telemetry
        # failure is logged but must not create a second cascading outage.
        log.exception(
            "Не вдалося оновити heartbeat scheduler %s", scheduler_name,
            extra=log_extra(
                "SCHEDULER_HEARTBEAT_FAILED",
                scheduler=scheduler_name,
                status=status,
                exception_type=type(exc).__name__,
            ),
        )


async def _direct_superadmin_alert(bot, settings, text_value: str) -> int:
    sent = 0
    for tg_id in sorted(settings.superadmin_ids):
        try:
            await bot.send_message(tg_id, text_value)
            sent += 1
        except Exception as exc:
            log.exception(
                "Не вдалося надіслати runtime-alert суперадміну",
                extra=log_extra("RUNTIME_ALERT_SEND_FAILED", tg_id=tg_id, exception_type=type(exc).__name__),
            )
    return sent


async def supervise_scheduler(
    scheduler_name: str,
    runner_factory: Callable[[], Awaitable[None]],
    *,
    db,
    bot,
    settings,
    restart_delay_seconds: int = 5,
) -> None:
    """Restart and immediately alert if an infinite scheduler exits unexpectedly."""
    label = SCHEDULER_LABELS.get(scheduler_name, scheduler_name)
    while True:
        try:
            await scheduler_heartbeat(db, scheduler_name, status="starting")
            await runner_factory()
            # Scheduler coroutines are designed to be infinite. A clean return
            # is therefore a production fault, not a normal completion.
            raise RuntimeError("scheduler returned unexpectedly")
        except asyncio.CancelledError:
            try:
                await scheduler_heartbeat(db, scheduler_name, status="stopping")
            except Exception as exc:
                log.exception("Не вдалося записати зупинку scheduler %s", scheduler_name, extra=log_extra("SCHEDULER_STOP_HEARTBEAT_FAILED", scheduler=scheduler_name, exception_type=type(exc).__name__))
            raise
        except Exception as exc:
            log.exception("Scheduler %s аварійно завершився", scheduler_name, extra=log_extra("SCHEDULER_CRASH", scheduler=scheduler_name, exception_type=type(exc).__name__))
            try:
                await scheduler_heartbeat(db, scheduler_name, status="failed", error=str(exc))
            except Exception as heartbeat_exc:
                log.exception("Не вдалося зафіксувати scheduler failure: %s", scheduler_name, extra=log_extra("SCHEDULER_FAILURE_HEARTBEAT_FAILED", scheduler=scheduler_name, exception_type=type(heartbeat_exc).__name__))
            await _direct_superadmin_alert(
                bot,
                settings,
                "🚨 <b>АМП: аварійна зупинка планувальника</b>\n\n"
                f"Завдання: <b>{label}</b>\n"
                f"Компонент: <code>{scheduler_name}</code>\n"
                "Система спробує автоматично перезапустити його.\n\n"
                "Перевірте 🩺 Стан системи та логи Heroku.",
            )
            await asyncio.sleep(max(1, int(restart_delay_seconds)))


def _state_from_payload(
    component: str,
    payload: dict[str, Any],
    *,
    max_age_seconds: int,
    now: datetime,
) -> HeartbeatState:
    at = _parse_dt(payload.get("at"))
    started_at = _parse_dt(payload.get("started_at"))
    status = str(payload.get("status") or "unknown")
    error = str(payload.get("error") or "")[:500]
    age = None if at is None else max(0.0, (now - at).total_seconds())
    healthy = bool(at and age is not None and age <= max_age_seconds and status not in {"failed", "stopped"})
    return HeartbeatState(
        component=component,
        status=status,
        at=at,
        started_at=started_at,
        error=error,
        age_seconds=round(age, 1) if age is not None else None,
        healthy=healthy,
        missing=at is None,
    )


async def runtime_health_snapshot(
    session,
    *,
    worker_stale_seconds: int = 120,
    startup_grace_seconds: int = 180,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = clock.ensure_utc(now) if now is not None else clock.now_utc()
    components = ["worker"] + [f"scheduler:{name}" for name in SCHEDULER_MAX_SILENCE_SECONDS]
    keys = [_key(name) for name in components]
    rows = list((await session.scalars(select(SystemSetting).where(SystemSetting.key.in_(keys)))).all())
    by_key = {row.key: _decode_payload(row.value) for row in rows}

    worker = _state_from_payload(
        "worker",
        by_key.get(_key("worker"), {}),
        max_age_seconds=max(30, int(worker_stale_seconds)),
        now=now,
    )
    worker_uptime = None
    if worker.started_at:
        worker_uptime = max(0.0, (now - worker.started_at).total_seconds())
    in_startup_grace = bool(worker.healthy and worker_uptime is not None and worker_uptime < max(0, startup_grace_seconds))

    schedulers: list[dict[str, Any]] = []
    for name, max_age in SCHEDULER_MAX_SILENCE_SECONDS.items():
        component = f"scheduler:{name}"
        state = _state_from_payload(
            component,
            by_key.get(_key(component), {}),
            max_age_seconds=max_age,
            now=now,
        )
        # A just-started worker needs a short grace period to create all
        # scheduler heartbeat rows. Once a row exists, a failed status is never
        # hidden by the grace period.
        healthy = state.healthy or (state.missing and in_startup_grace)
        schedulers.append({
            "name": name,
            "label": SCHEDULER_LABELS.get(name, name),
            "status": "starting" if state.missing and in_startup_grace else state.status,
            "at": state.at,
            "age_seconds": state.age_seconds,
            "max_age_seconds": max_age,
            "healthy": healthy,
            "missing": state.missing,
            "error": state.error,
        })

    schedulers_ok = all(item["healthy"] for item in schedulers)
    return {
        "worker": {
            "status": worker.status,
            "at": worker.at,
            "started_at": worker.started_at,
            "age_seconds": worker.age_seconds,
            "healthy": worker.healthy,
            "missing": worker.missing,
            "error": worker.error,
        },
        "schedulers": schedulers,
        "worker_ok": worker.healthy,
        "schedulers_ok": schedulers_ok,
        "ok": worker.healthy and schedulers_ok,
        "startup_grace": in_startup_grace,
    }


async def runtime_health_alert(
    bot,
    db,
    settings,
    *,
    repeat_seconds: int = 3600,
    worker_stale_seconds: int = 120,
    startup_grace_seconds: int = 180,
) -> dict[str, Any]:
    """Alert superadmins from the web process when worker/schedulers go stale.

    Running this monitor in web is intentional: it can still alert when the
    dedicated Telegram worker itself has stopped. Alerts contain only component
    names and timing metadata; no participant data are included.
    """
    now = clock.now_utc()
    storage_now = clock.storage_utc(now)
    async with db.session_factory() as session:
        snapshot = await runtime_health_snapshot(
            session,
            worker_stale_seconds=worker_stale_seconds,
            startup_grace_seconds=startup_grace_seconds,
            now=now,
        )
        incidents: list[tuple[str, str]] = []
        if not snapshot["worker_ok"]:
            worker = snapshot["worker"]
            age = worker.get("age_seconds")
            age_text = "немає heartbeat" if age is None else f"heartbeat {int(age)} с тому"
            incidents.append(("worker", f"Worker: {age_text}"))
        for item in snapshot["schedulers"]:
            if item["healthy"]:
                continue
            age = item.get("age_seconds")
            age_text = "немає heartbeat" if age is None else f"{int(age)} с без heartbeat"
            incidents.append((f"scheduler:{item['name']}", f"{item['label']}: {age_text}"))

        alerts_to_send: list[tuple[str, str]] = []
        for component, description in incidents:
            marker_key = _alert_key(component)
            marker = await session.get(SystemSetting, marker_key)
            last_alert = _parse_dt(marker.value if marker else None)
            if last_alert and now - last_alert < timedelta(seconds=max(60, int(repeat_seconds))):
                continue
            await _upsert_setting(session, marker_key, now.isoformat(), now=storage_now)
            alerts_to_send.append((component, description))
        if alerts_to_send:
            await session.commit()

    if not alerts_to_send:
        return {"incidents": len(incidents), "alerts": 0, "ok": not incidents}

    body = "\n".join(f"• {description}" for _, description in alerts_to_send[:15])
    sent = await _direct_superadmin_alert(
        bot,
        settings,
        "🚨 <b>АМП: проблема фонового процесу</b>\n\n"
        f"{body}\n\n"
        "Перевірте <b>🩺 Стан системи</b> та <code>/health/dependencies</code>.",
    )
    return {"incidents": len(incidents), "alerts": len(alerts_to_send), "recipients": sent, "ok": False}


def expected_alembic_head() -> str:
    cfg = Config("alembic.ini")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    return str(head or "")


async def database_probe(db, *, timeout_seconds: int = 3) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async def _probe() -> None:
            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))

        await asyncio.wait_for(_probe(), timeout=max(1, int(timeout_seconds)))
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return {"ok": True, "latency_ms": latency_ms, "error": ""}
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return {"ok": False, "latency_ms": latency_ms, "error": type(exc).__name__}


async def alembic_revision_status(db, *, expected_head: str) -> dict[str, Any]:
    try:
        async with db.session_factory() as session:
            current = await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        current = str(current or "")
        return {
            "ok": bool(current and current == expected_head),
            "current": current or None,
            "expected": expected_head,
        }
    except Exception as exc:
        return {"ok": False, "current": None, "expected": expected_head, "error": type(exc).__name__}
