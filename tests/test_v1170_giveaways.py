from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.giveaways import eligible_user_ids, run_draw
from app.models import Giveaway, GiveawayEntry, GiveawayPrize, GiveawayWinner, UserRole
from app.time_utils import clock
from tests.conftest import create_user

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_giveaway_surface_is_wired_into_web_and_telegram():
    migration = read("migrations/versions/20260919_0007_giveaways.py")
    web = read("app/web/routes/giveaways.py")
    tg = read("app/handlers/giveaways.py")
    sidebar = read("app/web/templates/base.html")
    keyboards = read("app/keyboards.py")
    assert 'revision: str = "20260919_0007"' in migration
    assert 'down_revision: Union[str, None] = "20260919_0006"' in migration
    assert 'giveaway_prizes' in migration and 'giveaway_entries' in migration and 'giveaway_winners' in migration
    assert '/admin/giveaways/{giveaway_id}/draw' in web
    assert 'run_draw(session, giveaway)' in web
    assert '🎲 Розіграші' in sidebar
    assert '🎲 Розіграші' in keyboards
    assert 'GiveawayEntryState.photo' in tg
    assert 'фото-підтвердження обов’язкове' in tg


def test_giveaway_media_privacy_contract():
    security = read("app/security.py")
    assert '"giveaway_prizes"' in security
    assert '"giveaway_proofs"' in security
    assert 'PUBLIC_MEDIA_CATEGORIES' in security
    assert 'STAFF_PRIVATE_MEDIA_CATEGORIES' in security


def test_giveaway_randomizer_is_auditable_and_winner_notification_is_queued():
    logic = read("app/giveaways.py")
    web = read("app/web/routes/giveaways.py")
    assert "secrets.token_hex(32)" in logic
    assert "hashlib.sha256" in logic
    assert 'draw_algorithm = "sha256-seeded-order-v1"' in logic
    assert "if existing:" in logic
    assert "len(users) < len(units)" in logic
    assert "giveaway_winner:" in web
    assert "Вітаємо! Ви перемогли в розіграші" in web
    assert "З вами зв’яжеться адміністратор АМП" in web


async def test_automatic_draw_has_distinct_winners_and_is_idempotent(db):
    now = clock.storage_utc()
    async with db.session_factory() as session:
        users = [await create_user(session, tg_id=11700 + i, name=f"Учасник {i}") for i in range(1, 6)]
        giveaway = Giveaway(
            title="Тестовий розіграш",
            participation_mode="automatic",
            audience_type="all",
            starts_at=now - timedelta(hours=1),
            ends_at=now - timedelta(minutes=1),
            status="closed",
            created_at=now,
            updated_at=now,
        )
        session.add(giveaway)
        await session.flush()
        session.add_all([
            GiveawayPrize(giveaway_id=giveaway.id, title="Подарунок A", quantity=2, sort_order=1, created_at=now),
            GiveawayPrize(giveaway_id=giveaway.id, title="Подарунок B", quantity=1, sort_order=2, created_at=now),
        ])
        await session.flush()
        eligible = await eligible_user_ids(session, giveaway)
        assert set(eligible) >= {u.id for u in users}
        winners, seed = await run_draw(session, giveaway)
        assert len(winners) == 3
        assert len({w.user_id for w in winners}) == 3
        assert seed and giveaway.status == "drawn"
        await session.flush()
        entries = list((await session.scalars(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway.id))).all())
        assert len(entries) >= 5
        again, again_seed = await run_draw(session, giveaway)
        assert [w.user_id for w in again] == [w.user_id for w in winners]
        assert again_seed == seed
        stored = list((await session.scalars(select(GiveawayWinner).where(GiveawayWinner.giveaway_id == giveaway.id))).all())
        assert len(stored) == 3


async def test_team_audience_excludes_regular_participant(db):
    now = clock.storage_utc()
    async with db.session_factory() as session:
        participant = await create_user(session, tg_id=11801, name="Звичайний Учасник")
        ambassador = await create_user(session, tg_id=11802, name="АМПасадор", role=UserRole.AMBASSADOR.value)
        coordinator = await create_user(session, tg_id=11803, name="Координатор", role=UserRole.COORDINATOR.value)
        giveaway = Giveaway(title="Командний", participation_mode="automatic", audience_type="team", status="active", starts_at=now, ends_at=now + timedelta(days=1), created_at=now, updated_at=now)
        session.add(giveaway)
        await session.flush()
        ids = set(await eligible_user_ids(session, giveaway))
        assert ambassador.id in ids and coordinator.id in ids
        assert participant.id not in ids
