from types import SimpleNamespace

from app.core import realtime_session
from app.realtime import persona_context
from app.runtime import agent_base, orchestrator


def test_persona_uses_name_only_for_a_first_natural_greeting(monkeypatch):
    monkeypatch.setattr(
        realtime_session,
        "get_settings",
        lambda: SimpleNamespace(personal_info={"name": "Amine", "defaultLocation": "Paris", "timezone": "Europe/Paris"}),
        raising=False,
    )
    from app.core import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        personal_info={"name": "Amine", "defaultLocation": "Paris", "timezone": "Europe/Paris"}
    ))
    monkeypatch.setattr(realtime_session, "_detect_integrations", lambda: {
        "google": False, "zimbra": False, "apple_calendar": False,
        "obsidian_notes": 0, "default_apple_calendar": "",
    })
    monkeypatch.setattr(realtime_session, "_fetch_memory_primer", lambda: "")

    prompt = realtime_session.get_jarvis_persona()

    assert "Do not begin ordinary replies with Amine" in prompt
    assert 'do not pair the name\n    with "sir"' in prompt
    assert 'address the user as\n"Amine" or "sir"' not in prompt


def test_context_helpers_cap_reference_text():
    text = "word " * 400

    assert len(agent_base._bounded_context(text, 120)) <= 121
    assert len(orchestrator._bounded_context(text, 120)) <= 121
    assert "Most replies should have no form of address" in persona_context.addressing_block("Amine")


def test_live_reconnect_history_has_a_bounded_budget(monkeypatch):
    monkeypatch.setattr(realtime_session, "load_all_capabilities", lambda: None)
    session = realtime_session.RealtimeSession()

    assert session._recent_history.maxlen == realtime_session.RECENT_HISTORY_ITEMS == 12
    assert realtime_session.RECENT_HISTORY_TEXT_CHARS == 900
