"""Email template system - reusable named email drafts with variable substitution.

Templates are stored in ~/.jarvis/settings.json under the "templates" key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..runtime import tool
from ..runtime.registry import REGISTRY


_SETTINGS_PATH = Path.home() / ".jarvis" / "settings.json"


def _load_templates() -> Dict[str, Dict[str, str]]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(_SETTINGS_PATH.read_text()) or {}
        templates = data.get("templates", {})
        return templates if isinstance(templates, dict) else {}
    except Exception:
        return {}


def _save_templates(templates: Dict[str, Dict[str, str]]) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text()) or {}
        except Exception:
            pass
    data["templates"] = templates
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2))


def _apply_replacements(text: str, replacements: Dict[str, str]) -> str:
    result = text
    for key, value in replacements.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


@tool(
    name="mail_template_list",
    description="List saved email templates with their names.",
    parameters={"type": "object", "properties": {}},
)
async def mail_template_list() -> str:
    templates = _load_templates()
    if not templates:
        return "No email templates saved yet."
    lines = ["Saved email templates:"]
    for name, t in templates.items():
        subject = t.get("subject", "")
        lines.append(f"- {name}: {subject}")
    return "\n".join(lines)


@tool(
    name="mail_send_template",
    description=(
        "Send an email using a saved template. ALWAYS call first with confirmed=false "
        "to get a preview; read the preview to the user, ask for confirmation, then call "
        "again with confirmed=true to actually send."
    ),
    parameters={
        "type": "object",
        "properties": {
            "template_name": {"type": "string", "description": "Name of the saved template"},
            "to": {"type": "string", "description": "Recipient email address"},
            "replacements": {
                "type": "object",
                "description": "Variable replacements, e.g. {'name': 'Marie'}. Keys match {{placeholders}} in the template.",
            },
            "account": {
                "type": "string",
                "enum": ["gmail", "zimbra"],
                "description": "Which account to send from. Defaults to gmail.",
            },
            "confirmed": {
                "type": "boolean",
                "description": "Set true ONLY after the user has verbally confirmed the draft.",
            },
        },
        "required": ["template_name", "to"],
    },
)
async def mail_send_template(
    template_name: str,
    to: str,
    replacements: Dict[str, str] | None = None,
    account: str = "gmail",
    confirmed: bool = False,
) -> str:
    templates = _load_templates()
    name = (template_name or "").strip()
    if not name:
        return "Error: template_name is required."
    if name not in templates:
        available = ", ".join(templates.keys()) or "none"
        return f"Error: template '{name}' not found. Available: {available}"

    tmpl = templates[name]
    subject = _apply_replacements(tmpl.get("subject", ""), replacements or {})
    body = _apply_replacements(tmpl.get("body", ""), replacements or {})

    if not subject or not body:
        return f"Error: template '{name}' is missing subject or body."

    # Delegate to the existing mail_send action via the registry
    result = await REGISTRY.call(
        "mail_send",
        {
            "to": (to or "").strip(),
            "subject": subject,
            "body": body,
            "account": (account or "gmail").lower(),
            "confirmed": bool(confirmed),
        },
    )
    if result.get("ok"):
        return str(result.get("result") or "")
    return f"Error: {result.get('error', 'unknown error')}"


@tool(
    name="mail_template_save",
    description="Save a new email template or overwrite an existing one.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Template name"},
            "subject": {"type": "string", "description": "Email subject with optional {{placeholders}}"},
            "body": {"type": "string", "description": "Email body with optional {{placeholders}}"},
        },
        "required": ["name", "subject", "body"],
    },
)
async def mail_template_save(name: str, subject: str, body: str) -> str:
    if not name or not name.strip():
        return "Error: name is required."
    if not subject or not subject.strip():
        return "Error: subject is required."
    if not body or not body.strip():
        return "Error: body is required."

    templates = _load_templates()
    templates[name.strip()] = {"subject": subject.strip(), "body": body.strip()}
    _save_templates(templates)
    return f"Template '{name.strip()}' saved."


@tool(
    name="mail_template_delete",
    description="Delete a saved email template by name.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Template name to delete"},
        },
        "required": ["name"],
    },
)
async def mail_template_delete(name: str) -> str:
    templates = _load_templates()
    name = (name or "").strip()
    if name not in templates:
        return f"Error: template '{name}' not found."
    del templates[name]
    _save_templates(templates)
    return f"Template '{name}' deleted."
