from __future__ import annotations

import importlib

from app.runtime import load_all_capabilities


def _load_startup_briefing_module():
    load_all_capabilities()
    return importlib.import_module("app.agents.startup_briefing")


def test_startup_briefing_prompt_is_short_and_spoken():
    startup_briefing = _load_startup_briefing_module()
    system_prompt = startup_briefing._SYSTEM_PROMPT

    assert "startup briefing sub-agent" in system_prompt
    assert "2-3 short sentences" in system_prompt
    assert "no headings" in system_prompt
    assert "Do not end with a question" in system_prompt
    assert "activation trigger" in system_prompt
    assert "calendar_list" in system_prompt
    assert "mail_list" in system_prompt
    assert "memory_recall or knowledge_search" in system_prompt


def test_startup_briefing_agent_uses_same_core_briefing_tools():
    startup_briefing = _load_startup_briefing_module()
    StartupBriefingAgent = startup_briefing.StartupBriefingAgent

    assert StartupBriefingAgent.name == "startup_briefing"
    assert StartupBriefingAgent.max_iterations == 2
    assert "calendar_list" in StartupBriefingAgent.tools
    assert "mail_list" in StartupBriefingAgent.tools
    assert "memory_recall" not in StartupBriefingAgent.tools
    assert "knowledge_search" not in StartupBriefingAgent.tools
    assert "knowledge_ask" not in StartupBriefingAgent.tools
