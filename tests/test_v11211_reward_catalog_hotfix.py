from app.domain_services.gamification import DEFAULT_SPACE_REWARDS


def test_default_space_reward_catalog_survives_domain_refactor():
    assert len(DEFAULT_SPACE_REWARDS) == 9
    assert sorted(item[2] for item in DEFAULT_SPACE_REWARDS) == [5, 15, 45, 50, 50, 75, 100, 100, 150]
    assert len({item[0] for item in DEFAULT_SPACE_REWARDS}) == 9
