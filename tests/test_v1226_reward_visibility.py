"""Regression checks for the v1.22.6 reward-history/XP-spend hotfix."""

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _decoder_without_runtime_deps():
    """Exercise the real decoder even in environments without SQLAlchemy."""
    tree = ast.parse(source("app/reward_history.py"))
    names = {"REWARD_EVENT_ACTIONS", "REWARD_EVENT_LABELS"}
    nodes = [
        node for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
        ) or (isinstance(node, ast.FunctionDef) and node.name == "decode_reward_event")
    ]
    namespace = {"json": json, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<reward_decoder>", "exec"), namespace)
    return namespace["decode_reward_event"]


def test_decode_structured_purchase_and_refund():
    decoder = _decoder_without_runtime_deps()
    now = datetime(2026, 11, 17, 14, 0)
    for action, delta, balance in (
        ("reward_spent", -150, 120),
        ("reward_refunded", 150, 270),
        ("reward_fulfilled", 0, 120),
    ):
        row = SimpleNamespace(
            action=action, details=json.dumps({
                "reward_id": 7, "reward_title": "Футболка АМП",
                "claim_id": 11, "xp_delta": delta, "wallet_after": balance,
            }), created_at=now, id=42, actor_user_id=9,
        )
        decoded = decoder(row)
        assert decoded["delta"] == delta
        assert decoded["balance_after"] == balance
        assert decoded["reward_title"] == "Футболка АМП"
        assert decoded["claim_id"] == 11


def test_decode_legacy_streak_spending():
    decoder = _decoder_without_runtime_deps()
    row = SimpleNamespace(
        action="telegram_streak_restore_reward",
        details="Відновлено суперсерію; списано 80 XP; серія=4",
        created_at=datetime(2026, 10, 20), id=9, actor_user_id=2, entity_id=4,
    )
    assert decoder(row)["delta"] == -80
    row.details = "Неправильний формат"
    assert decoder(row) is None


def test_reward_claims_and_disbursements_visible_in_admin():
    routes = source("app/web/routes/gamification.py")
    html = source("app/web/templates/rewards.html")
    assert "history_rows=history_rows" in routes
    assert "recent_reward_events=recent_reward_events" in routes
    assert "select(RewardClaim, User, Reward)" in routes
    assert 'id="rewardHistory"' in html
    assert 'id="rewardOperations"' in html
    assert "{{ user.full_name }}" in html
    assert "claim.fulfilled_at" in html
    assert 'name="history_status"' in html


def test_expenses_in_telegram_and_user_360_timeline():
    home = source("app/handlers/participant_home.py")
    users = source("app/web/routes/users.py")
    template = source("app/web/templates/user_detail.html")
    helper = source("app/reward_history.py")
    assert "reward_operations_for_user(session, user.id" in home
    assert "reward_operations_for_user(session, user.id)" in users
    assert "Витрачено" in users
    assert 'data-panel="rewards"' in template
    assert "xp_operations" in template
    assert "RewardClaim.requested_at" in helper
    assert "reward_refunded" in helper


def test_reward_spending_does_not_change_lifetime_xp():
    home = source("app/handlers/participant_home.py")
    admin_bot = source("app/handlers/admin_quests_rewards.py")
    admin_web = source("app/web/routes/gamification.py")
    assert 'record_reward_event(\n            session, "reward_spent"' in home
    assert '"reward_streak_restored"' in home
    assert '"reward_refunded"' in admin_bot
    assert '"reward_refunded"' in admin_web
    assert "XPTransaction(" not in source("app/reward_history.py")
    assert "preserve_legacy_claim_before_reuse" in home
