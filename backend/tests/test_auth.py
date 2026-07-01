"""Telegram access-control (fail-closed allowlist)."""

from types import SimpleNamespace


def _update(user_id: int | None):
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(effective_user=user)


def test_allowlist_fail_closed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "")
    from app.config import get_settings

    get_settings.cache_clear()
    from app import telegram_bot as tb

    # Empty allowlist denies everyone (and is "setup mode").
    assert tb._setup_mode() is True
    assert tb._allowed(_update(123)) is False
    assert tb._allowed(_update(None)) is False


def test_allowlist_permits_only_listed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111, 222")
    from app.config import get_settings

    get_settings.cache_clear()
    from app import telegram_bot as tb

    assert tb._setup_mode() is False
    assert tb._allowed(_update(111)) is True
    assert tb._allowed(_update(999)) is False


def teardown_module(_module):
    # Reset the settings cache so other tests aren't affected.
    from app.config import get_settings

    get_settings.cache_clear()
