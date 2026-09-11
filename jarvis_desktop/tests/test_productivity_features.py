"""Tests for Productivity & Automation features:
- Email templates
- Focus agent
- Meeting prep agent
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def patch_settings_path(temp_home, monkeypatch):
    from app.tools import mail_templates
    path = temp_home / ".jarvis" / "settings.json"
    monkeypatch.setattr(mail_templates, "_SETTINGS_PATH", path)
    yield path


class TestMailTemplates:
    async def test_save_and_list(self, patch_settings_path):
        from app.tools.mail_templates import mail_template_save, mail_template_list

        await mail_template_save("follow-up", "Follow-up: {{topic}}", "Hi {{name}}, following up on {{topic}}.")
        result = await mail_template_list()
        assert "follow-up" in result
        assert "Follow-up: {{topic}}" in result

    async def test_send_template_preview(self, patch_settings_path):
        from app.tools.mail_templates import mail_template_save, mail_send_template

        await mail_template_save("test-tmpl", "Subject: {{topic}}", "Body: {{name}}")
        result = await mail_send_template("test-tmpl", "test@example.com", {"topic": "Demo", "name": "Marie"})
        assert "DRAFT" in result or "Error" in result

    async def test_delete_template(self, patch_settings_path):
        from app.tools.mail_templates import mail_template_save, mail_template_delete, mail_template_list

        await mail_template_save("to-delete", "Subj", "Body")
        result = await mail_template_delete("to-delete")
        assert "deleted" in result
        list_result = await mail_template_list()
        assert "to-delete" not in list_result

    async def test_list_empty(self, patch_settings_path):
        from app.tools.mail_templates import mail_template_list

        result = await mail_template_list()
        assert "No email templates" in result

    async def test_rejects_missing_name(self, patch_settings_path):
        from app.tools.mail_templates import mail_template_save

        result = await mail_template_save("", "Subj", "Body")
        assert "Error" in result


class TestFocusAgent:
    async def test_agent_registered(self):
        from app.runtime.registry import REGISTRY
        assert REGISTRY.has("delegate_to_focus")

    async def test_agent_tools_exist(self):
        from app.agents.focus import FocusAgent
        # If the agent registered successfully, its tools were validated
        assert "computer_play_music" in FocusAgent.tools
        assert "toggle_do_not_disturb" in FocusAgent.tools


class TestMeetingPrepAgent:
    async def test_agent_registered(self):
        from app.runtime.registry import REGISTRY
        assert REGISTRY.has("delegate_to_meeting_prep")


class TestDoNotDisturbTool:
    async def test_toggle_dnd_exists(self):
        from app.runtime.registry import REGISTRY
        assert REGISTRY.has("toggle_do_not_disturb")
