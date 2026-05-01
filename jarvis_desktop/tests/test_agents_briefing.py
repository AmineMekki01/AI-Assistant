from __future__ import annotations

import importlib

from app.runtime import load_all_capabilities


def _load_briefing_module():
    load_all_capabilities()
    return importlib.import_module("app.agents.briefing")


def test_briefing_prompt_is_structured_and_conversational():
    briefing = _load_briefing_module()
    _SYSTEM_PROMPT = briefing._SYSTEM_PROMPT

    assert "Here is your briefing" not in _SYSTEM_PROMPT
    assert "That’s your briefing" not in _SYSTEM_PROMPT
    assert "single coherent update" in _SYSTEM_PROMPT
    assert "Do not use labels" in _SYSTEM_PROMPT
    assert "Do not end with a question" in _SYSTEM_PROMPT


def test_briefing_agent_metadata_matches_the_daily_briefing_use_case():
    briefing = _load_briefing_module()
    BriefingAgent = briefing.BriefingAgent

    assert BriefingAgent.name == "briefing"
    assert BriefingAgent.max_iterations == 4
    assert "calendar_list" in BriefingAgent.tools
    assert "mail_list" in BriefingAgent.tools
    assert "action items" in BriefingAgent.description
