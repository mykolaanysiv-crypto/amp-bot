from __future__ import annotations

from pathlib import Path

import pytest

from app.data_integrity import duplicate_match_reasons, scan_data_integrity, user_reference_summary
from app.model_domains import User, XPTransaction
from tests.conftest import create_user

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v11721_version_and_ui_controls():
    version = read("VERSION.txt").strip()
    assert tuple(map(int, version.split("."))) >= (1, 17, 2, 1)
    assert read("VERSION_CHECK.txt").strip() == version
    routes = read("app/web/routes/data_integrity.py")
    users = read("app/web/routes/users.py")
    integrity_tpl = read("app/web/templates/data_integrity.html")
    users_tpl = read("app/web/templates/users.html")
    assert '/admin/data-integrity/duplicate-delete' in routes
    assert 'web_duplicate_user_removed' in routes
    assert 'guard_superadmin(request)' in routes
    assert '/admin/users/{user_id}/status-direct' in users
    assert 'web_user_status_direct_change' in users
    assert 'Введіть ВИДАЛИТИ' in integrity_tpl
    assert 'canonical_user_id' in integrity_tpl
    assert 'status-direct' in integrity_tpl
    assert 'status-direct' in users_tpl


@pytest.mark.asyncio
async def test_duplicate_scan_exposes_actionable_groups(db):
    async with db.session_factory() as session:
        left = await create_user(session, tg_id=911001, name="Іваненко Іван")
        right = await create_user(session, tg_id=911002, name="Іваненко Іван")
        left.phone = "+380 67 111 22 33"
        right.phone = "380671112233"
        left.email = "dup@example.org"
        right.email = "DUP@example.org"
        await session.commit()

        reasons = duplicate_match_reasons(left, right)
        assert "phone" in reasons
        assert "email" in reasons

        report = await scan_data_integrity(session)
        groups = report["duplicate_groups"]
        group = next(g for g in groups if {left.id, right.id}.issubset(set(g["member_ids"])))
        assert len(group["members"]) == 2
        assert "Однаковий телефон" in group["reasons"]
        assert "Однаковий email" in group["reasons"]


@pytest.mark.asyncio
async def test_reference_summary_prevents_unsafe_physical_delete(db):
    async with db.session_factory() as session:
        user = await create_user(session, tg_id=911003, name="Дублікат Історичний")
        await session.commit()
        empty_refs = await user_reference_summary(session, user.id)
        assert empty_refs == []

        session.add(XPTransaction(user_id=user.id, amount=5, category="test", description="history"))
        await session.commit()
        refs = await user_reference_summary(session, user.id)
        assert any(r["table"] == "xp_transactions" and r["column"] == "user_id" for r in refs)
