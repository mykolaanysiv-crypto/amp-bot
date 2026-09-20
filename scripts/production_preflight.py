from __future__ import annotations

from pathlib import Path
import ast

from app.version import APP_VERSION


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION.txt").read_text(encoding="utf-8").strip()
    if version != APP_VERSION:
        raise SystemExit(f"VERSION mismatch: VERSION.txt={version!r}, APP_VERSION={APP_VERSION!r}")

    procfile = (root / "Procfile").read_text(encoding="utf-8")
    required = (
        "web: python run_web.py",
        "worker: python run.py",
        "release: python -m scripts.heroku_release",
    )
    missing = [item for item in required if item not in procfile]
    if missing:
        raise SystemExit(f"Procfile preflight failed: missing {missing}")

    if not (root / "alembic.ini").exists() or not list((root / "migrations" / "versions").glob("*.py")):
        raise SystemExit("Alembic preflight failed: migration baseline missing")

    required_files = (
        root / "scripts" / "startup_smoke.py",
        root / "app" / "runtime_health.py",
        root / ".github" / "workflows" / "ci.yml",
    )
    missing_files = [str(path.relative_to(root)) for path in required_files if not path.exists()]
    if missing_files:
        raise SystemExit(f"Production stability files missing: {missing_files}")

    # Refactor guard: a single-dot import inside app.domain_services must point
    # to a real sibling module. Root app modules (donations, settlements,
    # reliability, ...) must use ``..module``. This catches the exact class of
    # regressions that previously escaped compileall and failed only at runtime.
    domain_dir = root / "app" / "domain_services"
    sibling_modules = {path.stem for path in domain_dir.glob("*.py")}
    bad_relative_imports: list[str] = []
    for path in domain_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                sibling = node.module.split(".", 1)[0]
                if sibling not in sibling_modules:
                    bad_relative_imports.append(
                        f"{path.relative_to(root)}:{node.lineno}: from .{node.module} import ..."
                    )
    if bad_relative_imports:
        raise SystemExit(
            "Domain-service import preflight failed; missing sibling module(s): "
            + "; ".join(bad_relative_imports)
        )

    # v1.13.0.2 startup-import guard: every explicit relative module import
    # inside app/ must resolve to a real Python module/package.  This catches
    # package-depth mistakes introduced while splitting a monolithic module,
    # e.g. ``app.handlers.start_flow`` accidentally importing ``..time_utils``
    # (which resolves to the nonexistent ``app.handlers.time_utils``) instead
    # of ``...time_utils``.  compileall cannot catch this class of runtime error.
    unresolved_relative_imports: list[str] = []
    app_dir = root / "app"
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel_module = path.relative_to(root).with_suffix("")
        module_parts = list(rel_module.parts)
        package_parts = module_parts[:-1]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.level or not node.module:
                continue
            up = node.level - 1
            if up > len(package_parts):
                unresolved_relative_imports.append(
                    f"{path.relative_to(root)}:{node.lineno}: relative import escapes package root"
                )
                continue
            target_parts = package_parts[: len(package_parts) - up] + node.module.split(".")
            module_file = root.joinpath(*target_parts).with_suffix(".py")
            package_init = root.joinpath(*target_parts) / "__init__.py"
            if not module_file.exists() and not package_init.exists():
                unresolved_relative_imports.append(
                    f"{path.relative_to(root)}:{node.lineno}: from {'.' * node.level}{node.module} import ... -> "
                    f"{'.'.join(target_parts)}"
                )
    if unresolved_relative_imports:
        raise SystemExit(
            "Startup import preflight failed: unresolved relative module import(s): "
            + "; ".join(unresolved_relative_imports)
        )


    # v1.12.2 hardening gates: one Clock boundary, no deprecated utcnow calls,
    # no silent broad-exception swallowing, and structured error context.
    time_source = (root / "app" / "time_utils.py").read_text(encoding="utf-8")
    if "class Clock" not in time_source or "clock = Clock()" not in time_source or "def now_utc" not in time_source:
        raise SystemExit("Time preflight failed: canonical Clock helper missing")

    direct_time_hits: list[str] = []
    silent_exception_hits: list[str] = []
    allowed_time_source = root / "app" / "time_utils.py"
    for scan_root in (root / "app", root / "scripts"):
        for path in scan_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            if path != allowed_time_source and path.name != "production_preflight.py":
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        if (node.value.id, node.attr) in {
                            ("datetime", "utcnow"),
                            ("datetime", "now"),
                            ("date", "today"),
                        }:
                            direct_time_hits.append(f"{path.relative_to(root)}:{node.lineno}:{node.value.id}.{node.attr}")
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                if broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    silent_exception_hits.append(f"{path.relative_to(root)}:{node.lineno}")
    if direct_time_hits:
        raise SystemExit("Time preflight failed: direct wall-clock API outside Clock: " + ", ".join(sorted(set(direct_time_hits))))
    if silent_exception_hits:
        raise SystemExit("Error preflight failed: silent broad exceptions at " + ", ".join(silent_exception_hits))

    observability_source = (root / "app" / "observability.py").read_text(encoding="utf-8")
    for token in ("error_code", "context", "def log_extra"):
        if token not in observability_source:
            raise SystemExit(f"Observability preflight failed: {token} missing")

    # v1.17.1 architecture cleanup: canonical packages are now the only
    # production import surface; transitional v1.13 compatibility facades are retired.
    factory_source = (root / "app" / "web" / "factory.py").read_text(encoding="utf-8")
    run_web_source = (root / "run_web.py").read_text(encoding="utf-8")
    if "def create_app()" not in factory_source:
        raise SystemExit("Architecture preflight failed: app.web.factory.create_app missing")
    if '"app.web.factory:create_app"' not in run_web_source or "factory=True" not in run_web_source:
        raise SystemExit("Architecture preflight failed: web runtime does not start through create_app factory mode")

    health_source = (root / "app" / "web" / "health_routes.py").read_text(encoding="utf-8")
    for endpoint in ("/health/live", "/health/ready", "/health/dependencies"):
        if endpoint not in health_source:
            raise SystemExit(f"Health preflight failed: {endpoint} missing")
    if "from fastapi.encoders import jsonable_encoder" not in health_source or "JSONResponse(jsonable_encoder(payload)" not in health_source:
        raise SystemExit("Health preflight failed: JSON boundary must encode datetime-safe payloads")

    architecture_paths = (
        root / "app" / "web" / "dependencies.py",
        root / "app" / "web" / "event_routes",
        root / "app" / "analytics_modules",
        root / "app" / "reporting",
        root / "app" / "model_domains",
        root / "app" / "handlers" / "start_flow",
        root / "app" / "jobs",
        root / "app" / "bot_runtime.py",
    )
    missing_architecture = [str(path.relative_to(root)) for path in architecture_paths if not path.exists()]
    if missing_architecture:
        raise SystemExit(f"Architecture preflight failed: missing split components {missing_architecture}")

    retired_facades = (
        root / "app" / "models.py",
        root / "app" / "services.py",
        root / "app" / "analytics.py",
        root / "app" / "reports.py",
        root / "app" / "web" / "app.py",
        root / "app" / "web" / "routes" / "events.py",
        root / "app" / "handlers" / "start.py",
    )
    remaining_facades = [str(path.relative_to(root)) for path in retired_facades if path.exists()]
    if remaining_facades:
        raise SystemExit("Architecture preflight failed: retired compatibility facades remain: " + ", ".join(remaining_facades))

    # Production code must not import the retired module names indirectly.
    banned_modules = {
        "app.models", "app.services", "app.analytics", "app.reports",
        "app.web.app", "app.web.routes.events", "app.handlers.start",
    }
    retired_import_hits: list[str] = []
    for scan_root in (root / "app", root / "scripts"):
        for path in scan_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in banned_modules:
                    retired_import_hits.append(f"{path.relative_to(root)}:{node.lineno}:{node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in banned_modules:
                            retired_import_hits.append(f"{path.relative_to(root)}:{node.lineno}:{alias.name}")
    if retired_import_hits:
        raise SystemExit("Architecture preflight failed: retired facade imports remain: " + ", ".join(retired_import_hits))

    main_lines = len((root / "app" / "main.py").read_text(encoding="utf-8").splitlines())
    if main_lines > 140:
        raise SystemExit(f"Architecture preflight failed: app/main.py={main_lines}>140")

    wildcard_imports: list[str] = []
    for path in (root / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                wildcard_imports.append(f"{path.relative_to(root)}:{node.lineno}")
    if wildcard_imports:
        raise SystemExit("Architecture preflight failed: wildcard imports remain at " + ", ".join(wildcard_imports))

    # Release asset-cache guard: historical regression tests key static assets
    # to VERSION.txt.  A patch release must update the three public/admin login
    # templates together or browsers can keep stale CSS/logo assets.
    cache_token = f"?v={APP_VERSION}"
    for template_rel in (
        "app/web/templates/base.html",
        "app/web/templates/login.html",
        "app/web/templates/login_2fa.html",
    ):
        template_source = (root / template_rel).read_text(encoding="utf-8")
        if cache_token not in template_source:
            raise SystemExit(
                f"Release asset preflight failed: {template_rel} does not use current cache token {cache_token}"
            )


    # v1.13.1 participant profile/badges/analytics UX guards.
    participant_home_source = (root / "app" / "handlers" / "participant_home.py").read_text(encoding="utf-8")
    gamification_source = (root / "app" / "domain_services" / "gamification.py").read_text(encoding="utf-8")
    analytics_template = (root / "app" / "web" / "templates" / "analytics.html").read_text(encoding="utf-8")
    analytics_detail_template = (root / "app" / "web" / "templates" / "analytics_detail.html").read_text(encoding="utf-8")
    admin_css = (root / "app" / "web" / "static" / "admin.css").read_text(encoding="utf-8")
    if "row.description or row.category" not in participant_home_source or "row.reason or row.category" in participant_home_source:
        raise SystemExit("Profile XP preflight failed: XP history is not using canonical transaction.description")
    for token in ('callback_data="badges:all"', 'callback_data="badges:mine"', "TELEGRAM_FIRE_CUSTOM_EMOJI_ID"):
        if token not in participant_home_source:
            raise SystemExit(f"Badge/profile UX preflight failed: missing {token}")
    if "automatic_badge:{user.id}:{badge.id}" not in gamification_source or "Вітаємо! Ви отримали новий бейдж" not in gamification_source:
        raise SystemExit("Badge notification preflight failed: automatic badge notification wiring missing")
    if "analytics-chart-clickable" not in analytics_template or "Деталізація вибраного значення" not in analytics_detail_template:
        raise SystemExit("Analytics UX preflight failed: chart drill-down UI missing")
    if "@media (min-width:1024px) and (max-width:1365px){.admin-topbar{left:232px}}" not in admin_css:
        raise SystemExit("Admin layout preflight failed: topbar/search laptop alignment guard missing")

    # v1.13.0.4 CI/localization guard. Historical source-inspection tests must
    # follow the canonical Ukrainian Notification Center label and the Smart
    # Opportunities regression must not reintroduce Python 3.13 utcnow warnings.
    notification_regression = (root / "tests" / "test_v190_notification_center.py").read_text(encoding="utf-8")
    if '"Streak"' in notification_regression or '"Серії участі"' not in notification_regression:
        raise SystemExit("CI localization preflight failed: Notification Center historical test label is stale")
    smart_regression = (root / "tests" / "test_v192_smart_opportunities_seasons.py").read_text(encoding="utf-8")
    if "datetime.utcnow()" in smart_regression or "clock.storage_utc()" not in smart_regression:
        raise SystemExit("CI time preflight failed: Smart Opportunities test must use project Clock")

    # v1.13.0.3 Telegram/Web UX regression guards.  Architecture Completion
    # moved the participant router one package higher; /start and /menu for an
    # active user must resolve that facade correctly.  Keep /smart and full
    # participant-facing reward titles wired, and do not regress known English
    # labels in the web admin UI.
    start_common = (root / "app" / "handlers" / "start_flow" / "common.py").read_text(encoding="utf-8")
    if "from .. import participant" not in start_common or "from . import participant" in start_common:
        raise SystemExit("Telegram navigation preflight failed: start/menu participant lazy import is wrong")

    bot_runtime_source = (root / "app" / "bot_runtime.py").read_text(encoding="utf-8")
    opp_source = (root / "app" / "handlers" / "participant_opportunities.py").read_text(encoding="utf-8")
    middleware_source = (root / "app" / "telegram_middleware.py").read_text(encoding="utf-8")
    if 'BotCommand(command="smart", description="Персональні можливості")' not in bot_runtime_source:
        raise SystemExit("Telegram command preflight failed: /smart missing from public bot commands")
    if 'Command("smart")' not in opp_source or '"/smart"' not in middleware_source:
        raise SystemExit("Telegram command preflight failed: /smart handler/FSM navigation wiring missing")

    keyboard_source = (root / "app" / "keyboards.py").read_text(encoding="utf-8")
    rewards_start = keyboard_source.find("def rewards_keyboard")
    rewards_end = keyboard_source.find("def tasks_keyboard", rewards_start)
    rewards_block = keyboard_source[rewards_start:rewards_end]
    if "entity_button_text" not in rewards_block or "compact_button_text" in rewards_block:
        raise SystemExit("Reward UX preflight failed: participant reward titles are being truncated")

    visible_templates = "\n".join(
        path.read_text(encoding="utf-8") for path in (root / "app" / "web" / "templates").glob("*.html")
    )
    forbidden_web_labels = (
        "Participant 360", "Referrals", ">Timeline<", "SEASONS & HISTORY",
        "❄️ Freeze", "SLA прострочено", "granular permission", "ручного override", ">Streak<",
    )
    leaking_labels = [token for token in forbidden_web_labels if token in visible_templates]
    if leaking_labels:
        raise SystemExit("Web localization preflight failed: visible English labels remain: " + ", ".join(leaking_labels))

    # v1.14.0 Ambassador cabinets + donation XP guards.
    donation_source = (root / "app" / "donations.py").read_text(encoding="utf-8")
    ambassador_handler = (root / "app" / "handlers" / "ambassadors.py").read_text(encoding="utf-8")
    ambassador_route = (root / "app" / "web" / "routes" / "ambassadors.py").read_text(encoding="utf-8")
    if "DONATION_XP_KOP_PER_POINT = 500" not in donation_source or "backfill_donation_xp" not in donation_source:
        raise SystemExit("Donation XP preflight failed: 1 XP = 5 UAH/backfill wiring missing")
    if "AmbassadorReportState" not in ambassador_handler or "ambassador:event_qr" not in (root / "app" / "handlers" / "events.py").read_text(encoding="utf-8"):
        raise SystemExit("Ambassador cabinet preflight failed: reports/event QR wiring missing")
    if "/admin/ambassadors" not in ambassador_route or "AMBASSADOR_RESPONSIBILITIES" not in ambassador_route:
        raise SystemExit("Ambassador web preflight failed: admin/superadmin cabinet missing")

    # v1.17.1 Alembic full-adoption + schema continuity guards.
    db_source = (root / "app" / "db.py").read_text(encoding="utf-8")
    if "_migrate_v10_to_v11" in db_source or "Base.metadata.create_all" in db_source:
        raise SystemExit("Alembic preflight failed: runtime legacy schema mutation remains in app/db.py")
    startup_smoke_source = (root / "scripts" / "startup_smoke.py").read_text(encoding="utf-8")
    try:
        migrate_pos = startup_smoke_source.index("upgrade_head()")
        db_init_pos = startup_smoke_source.index("asyncio.run(_db_init_phase())", migrate_pos)
        bootstrap_pos = startup_smoke_source.index("asyncio.run(_bootstrap_defaults_phase())", db_init_pos)
        web_pos = startup_smoke_source.index("asyncio.run(_web_startup_phase())", bootstrap_pos)
    except ValueError as exc:
        raise SystemExit("Release-order preflight failed: canonical startup phases are missing") from exc
    if not (migrate_pos < db_init_pos < bootstrap_pos < web_pos):
        raise SystemExit("Release-order preflight failed: expected Alembic -> db.init -> bootstrap -> web lifespan")

    baseline_source = (root / "migrations" / "versions" / "20260915_0001_v1111_baseline.py").read_text(encoding="utf-8")
    if "op.create_table(" not in baseline_source or "Base.metadata.create_all" in baseline_source:
        raise SystemExit("Alembic preflight failed: baseline is not a frozen Alembic schema bootstrap")
    legacy_content_views_migration = (root / "migrations" / "versions" / "20260915_0002_content_views.py").read_text(encoding="utf-8")
    if 'revision: str = "20260915_0002"' not in legacy_content_views_migration:
        raise SystemExit("Alembic preflight failed: v1.12 content views migration missing")
    migration_source = (root / "migrations" / "versions" / "20260917_0003_ambassador_cabinets.py").read_text(encoding="utf-8")
    if 'revision: str = "20260917_0003"' not in migration_source or 'down_revision: Union[str, None] = "20260915_0002"' not in migration_source:
        raise SystemExit("Alembic preflight failed: v1.14 ambassador migration 20260917_0003 missing")
    survey_migration_source = (root / "migrations" / "versions" / "20260918_0004_survey_audience.py").read_text(encoding="utf-8")
    if 'revision: str = "20260918_0004"' not in survey_migration_source or 'down_revision: Union[str, None] = "20260917_0003"' not in survey_migration_source:
        raise SystemExit("Alembic preflight failed: v1.15 migration chain broken")
    adoption_migration = (root / "migrations" / "versions" / "20260920_0009_alembic_full_adoption.py").read_text(encoding="utf-8")
    if 'revision: str = "20260920_0009"' not in adoption_migration or 'down_revision: Union[str, None] = "20260920_0008"' not in adoption_migration:
        raise SystemExit("Alembic preflight failed: v1.17.1 adoption head 20260920_0009 missing")
    privacy_migration = (root / "migrations" / "versions" / "20260920_0010_privacy_data_integrity.py").read_text(encoding="utf-8")
    if 'revision: str = "20260920_0010"' not in privacy_migration or 'down_revision: Union[str, None] = "20260920_0009"' not in privacy_migration:
        raise SystemExit("Alembic preflight failed: v1.17.2 privacy head 20260920_0010 missing")

    schema_guard = root / "scripts" / "schema_drift_check.py"
    if not schema_guard.exists():
        raise SystemExit("Alembic preflight failed: schema_drift_check.py missing")
    ci_source = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for required_ci_token in ("schema_drift_check", "test_alembic_upgrade_from_previous_production_schema", "test_latest_revision_downgrade_upgrade_roundtrip"):
        if required_ci_token not in ci_source:
            raise SystemExit(f"Alembic preflight failed: CI gate {required_ci_token} missing")

    # v1.14.0.2 Telegram profile guard.  The profile handler renders the
    # ambassador responsibility condition with UserRole.AMBASSADOR.  Because
    # participant_home imports symbols explicitly from participant_common,
    # UserRole must be included in that import list or the handler crashes at
    # runtime with NameError as soon as «Мій профіль» is opened.
    participant_home_source = (root / "app" / "handlers" / "participant_home.py").read_text(encoding="utf-8")
    if "UserRole.AMBASSADOR.value" in participant_home_source:
        tree = ast.parse(participant_home_source, filename="app/handlers/participant_home.py")
        imported_user_role = any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == "UserRole" for alias in node.names)
            for node in ast.walk(tree)
        )
        if not imported_user_role:
            raise SystemExit("Telegram profile preflight failed: UserRole is used but not explicitly imported")

    # v1.15.0 targeting, event analytics, opportunity lifecycle and badge-edit guards.
    survey_model_source = (root / "app" / "model_domains" / "engagement.py").read_text(encoding="utf-8")
    survey_audience_source = (root / "app" / "survey_audience.py").read_text(encoding="utf-8")
    survey_web_source = (root / "app" / "web" / "routes" / "surveys.py").read_text(encoding="utf-8")
    survey_tg_source = (root / "app" / "handlers" / "surveys.py").read_text(encoding="utf-8")
    surveys_template = (root / "app" / "web" / "templates" / "surveys.html").read_text(encoding="utf-8")
    for token in ("audience_type", "audience_event_id", "class SurveyAudienceUser"):
        if token not in survey_model_source:
            raise SystemExit(f"Survey targeting preflight failed: model token {token} missing")
    model_init_source = (root / "app" / "model_domains" / "__init__.py").read_text(encoding="utf-8")
    if "SurveyAudienceUser" not in model_init_source:
        raise SystemExit("Survey targeting preflight failed: canonical model package does not export SurveyAudienceUser")
    for token in ("EVENT_AUDIENCE_STATUSES", "eligible_user_ids", "survey_available_to_user", "eligible_users"):
        if token not in survey_audience_source:
            raise SystemExit(f"Survey targeting preflight failed: helper {token} missing")
    if "eligible_users(session, survey)" not in survey_web_source or "survey_available_to_user" not in survey_tg_source:
        raise SystemExit("Survey targeting preflight failed: web publish/Telegram access guard missing")
    if 'value="users"' not in surveys_template or 'value="event"' not in surveys_template:
        raise SystemExit("Survey targeting preflight failed: audience controls missing from web UI")

    report_period_source = (root / "app" / "reporting" / "periods.py").read_text(encoding="utf-8")
    reports_template = (root / "app" / "web" / "templates" / "reports.html").read_text(encoding="utf-8")
    if "ISO-тиждень" in report_period_source + reports_template or "понеділок–неділя" not in report_period_source + reports_template:
        raise SystemExit("Reporting preflight failed: week wording is not understandable Ukrainian")

    event_overview_source = (root / "app" / "web" / "event_routes" / "overview.py").read_text(encoding="utf-8")
    event_template = (root / "app" / "web" / "templates" / "event_detail.html").read_text(encoding="utf-8")
    for token in ("attendance_rate", "feedback_response_rate", "xp_total", "unique_views"):
        if token not in event_overview_source:
            raise SystemExit(f"Event analytics preflight failed: {token} missing")
    if "Базова аналітика події" not in event_template:
        raise SystemExit("Event analytics preflight failed: event card analytics UI missing")

    opportunity_helper = (root / "app" / "opportunity_utils.py").read_text(encoding="utf-8")
    opportunity_web = (root / "app" / "web" / "routes" / "opportunities.py").read_text(encoding="utf-8")
    opportunity_tg = (root / "app" / "handlers" / "participant_opportunities.py").read_text(encoding="utf-8")
    opportunity_nav_tg = (root / "app" / "handlers" / "participant_tasks.py").read_text(encoding="utf-8")
    opportunity_template = (root / "app" / "web" / "templates" / "opportunities.html").read_text(encoding="utf-8")
    if "timedelta(days=3)" not in opportunity_helper or any("opportunity_sort_key" not in src for src in (opportunity_web, opportunity_tg, opportunity_nav_tg)):
        raise SystemExit("Opportunity preflight failed: automatic ordering/3-day urgency missing")
    urgent_phrase = "У вас є остання можливість долучитись до"
    opportunity_detail_for_urgency = (root / "app" / "web" / "templates" / "opportunity_detail.html").read_text(encoding="utf-8")
    if any(urgent_phrase not in src for src in (opportunity_tg, opportunity_nav_tg, opportunity_detail_for_urgency)):
        raise SystemExit("Opportunity preflight failed: deadline urgency messaging missing")

    requests_source = (root / "app" / "web" / "routes" / "requests.py").read_text(encoding="utf-8")
    for role_token in ("UserRole.SUPERADMIN.value", "UserRole.ADMIN.value", "UserRole.COORDINATOR.value", "UserRole.AMBASSADOR.value"):
        if role_token not in requests_source:
            raise SystemExit(f"Case assignee preflight failed: {role_token} missing")
    if "Відповідальним за кейс може бути лише активний" not in requests_source:
        raise SystemExit("Case assignee preflight failed: server-side role validation missing")

    badge_route_source = (root / "app" / "web" / "routes" / "gamification.py").read_text(encoding="utf-8")
    badges_template_source = (root / "app" / "web" / "templates" / "badges.html").read_text(encoding="utf-8")
    donation_source = (root / "app" / "donations.py").read_text(encoding="utf-8")
    badge_seed_source = (root / "app" / "domain_services" / "gamification.py").read_text(encoding="utf-8")
    if "_is_system_badge_rule" not in badge_route_source or "system_badge_ids" not in badges_template_source:
        raise SystemExit("Badge editing preflight failed: system/ambassador badge edit safeguards missing")
    if "Системний донатний бейдж" not in badges_template_source:
        raise SystemExit("Badge editing preflight failed: Ukrainian system donation badge label missing")
    if "Existing system badges are intentionally not overwritten here" not in badge_seed_source:
        raise SystemExit("Badge editing preflight failed: bootstrap still risks overwriting admin edits")
    if "preserve administrator-edited" not in donation_source:
        raise SystemExit("Badge editing preflight failed: donation badge presentation persistence missing")

    # v1.15.1 management UX guards: easier survey audience selection, safe deletes,
    # compact opportunity board and event-like opportunity detail/management page.
    survey_detail_template = (root / "app" / "web" / "templates" / "survey_detail.html").read_text(encoding="utf-8")
    for source in (surveys_template, survey_detail_template):
        for token in ("survey-user-picker", "Пошук учасника", "Обрати показаних", "surveyAudienceCount"):
            if token not in source:
                raise SystemExit(f"Survey audience UX preflight failed: missing {token}")
        if "Ctrl/Cmd + клік" in source:
            raise SystemExit("Survey audience UX preflight failed: legacy multi-select instructions remain")
    if ".survey-event-picker" not in admin_css or ".survey-audience-panel" not in admin_css:
        raise SystemExit("Survey audience UX preflight failed: aligned audience panel CSS missing")

    rewards_template_source = (root / "app" / "web" / "templates" / "rewards.html").read_text(encoding="utf-8")
    if '@router.post("/admin/rewards/{reward_id}/delete")' not in badge_route_source or "web_reward_delete_blocked_history" not in badge_route_source:
        raise SystemExit("Reward delete preflight failed: safe delete/history protection missing")
    if 'action="/admin/rewards/{{r.id}}/delete"' not in rewards_template_source:
        raise SystemExit("Reward delete preflight failed: delete UI missing")
    badge_seed_helper = (root / "app" / "badge_seeds.py").read_text(encoding="utf-8")
    badge_model_source = (root / "app" / "model_domains" / "gamification.py").read_text(encoding="utf-8")
    badge_seed_migration = (root / "migrations" / "versions" / "20260918_0005_badge_seed_keys.py").read_text(encoding="utf-8")
    if '@router.post("/admin/badges/{badge_id}/delete")' not in badge_route_source or "mark_badge_seed_deleted(session, badge.seed_key)" not in badge_route_source:
        raise SystemExit("Badge delete preflight failed: durable delete/tombstone missing")
    if 'action="/admin/badges/{{b.id}}/delete"' not in badges_template_source or "система не створить його повторно" not in badges_template_source:
        raise SystemExit("Badge delete preflight failed: delete UI/durable delete explanation missing")
    if "BADGE_DELETE_PREFIX" not in badge_seed_helper or "badge_seed_is_deleted" not in badge_seed_helper or "seed_key:" not in badge_model_source:
        raise SystemExit("Badge delete preflight failed: stable seed identity/tombstone helper missing")
    if 'revision: str = "20260918_0005"' not in badge_seed_migration or 'down_revision: Union[str, None] = "20260918_0004"' not in badge_seed_migration:
        raise SystemExit("Badge delete preflight failed: Alembic 20260918_0005 chain missing")
    if "badge_seed_is_deleted(session, seed_key)" not in badge_seed_source or "badge_seed_is_deleted(session, seed_key)" not in donation_source:
        raise SystemExit("Badge delete preflight failed: bootstrap/donation seed recreation guard missing")

    opportunity_detail_template = (root / "app" / "web" / "templates" / "opportunity_detail.html").read_text(encoding="utf-8")
    opportunity_public_template = (root / "app" / "web" / "templates" / "opportunity_public.html").read_text(encoding="utf-8")
    if '@router.get("/admin/opportunities/{opportunity_id}"' not in opportunity_web or '@router.get("/opportunity/{opportunity_id}"' not in opportunity_web:
        raise SystemExit("Opportunity detail preflight failed: admin/public detail routes missing")
    for token in ("Аналітика можливості", "Поділитися можливістю", "КЕРУВАННЯ МОЖЛИВІСТЮ", "Видалити можливість"):
        if token not in opportunity_detail_template:
            raise SystemExit(f"Opportunity detail preflight failed: missing {token}")
    if "opportunity-board" not in opportunity_template or "opportunity-card-actions" not in opportunity_template:
        raise SystemExit("Opportunity board preflight failed: compact equal-card board missing")
    if "Долучитися / дізнатися більше" not in opportunity_public_template:
        raise SystemExit("Opportunity share preflight failed: public action missing")


    # v1.17.2 Privacy & Data Integrity 2.0 guards.
    crypto_source = (root / "app" / "field_crypto.py").read_text(encoding="utf-8")
    identity_source = (root / "app" / "model_domains" / "identity.py").read_text(encoding="utf-8")
    integrity_source = (root / "app" / "data_integrity.py").read_text(encoding="utf-8")
    retention_source = (root / "app" / "privacy_retention.py").read_text(encoding="utf-8")
    media_source = (root / "app" / "web" / "media_routes.py").read_text(encoding="utf-8")
    backup_workflow = (root / ".github" / "workflows" / "backup.yml").read_text(encoding="utf-8")
    for token in ("FIELD_ENCRYPTION_KEY", "FIELD_ENCRYPTION_PREVIOUS_KEYS", "enc:v1:", "def reencrypt_field"):
        if token not in crypto_source:
            raise SystemExit(f"Privacy preflight failed: field encryption token {token} missing")
    for field_name in ("vulnerability_categories", "restoration_answers_json", "deletion_reason", "registration_rejection_reason"):
        if f"{field_name}: Mapped[str | None] = mapped_column(EncryptedText()" not in identity_source:
            raise SystemExit(f"Privacy preflight failed: {field_name} is not EncryptedText")
    for token in ("duplicate_phone", "duplicate_email", "orphan_records", "wallet_xp_mismatch", "attendance_anomaly", "expired_reservation", "missing_media"):
        if token not in integrity_source:
            raise SystemExit(f"Data-integrity preflight failed: {token} check missing")
    for token in ("RegistrationJourney", "WebAdminSession", "NotificationDelivery", "TEMP_MEDIA_CATEGORIES"):
        if token not in retention_source:
            raise SystemExit(f"Retention preflight failed: {token} cleanup missing")
    if "web_sensitive_media_download" not in media_source:
        raise SystemExit("Privacy preflight failed: sensitive media download audit missing")
    for token in ("verify_backup_restore.sh", "pg_restore", "restore-verified"):
        if token not in backup_workflow and token != "pg_restore":
            raise SystemExit(f"Backup restore preflight failed: {token} missing")
    if not (root / "scripts" / "verify_backup_restore.sh").exists():
        raise SystemExit("Backup restore preflight failed: verify_backup_restore.sh missing")

    print(f"Production preflight OK for AMP v{APP_VERSION}")


if __name__ == "__main__":
    main()
