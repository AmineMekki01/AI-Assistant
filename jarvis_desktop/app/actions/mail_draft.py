"""Shared representation and parser for the mail preview-then-confirm flow."""
from __future__ import annotations

import re
import textwrap
from typing import Any


_DRAFT_HEADER = "DRAFT (not sent yet - ask the user to confirm):"
_DRAFT_PATTERN = re.compile(
    r"^DRAFT \(not sent yet - ask the user to confirm\):\n"
    r"\s+Account:\s*(?P<account>gmail|zimbra)\n"
    r"\s+To:\s*(?P<to>.+)\n"
    r"\s+Subject:\s*(?P<subject>.+)\n"
    r"\s+Body:\n"
    r"(?P<body>[\s\S]*?)(?:\n\nRead this draft back|\Z)",
    re.IGNORECASE,
)


def parse_mail_draft_preview(output: str) -> dict[str, Any] | None:
    """Return the UI draft payload encoded in a successful ``mail_send`` result."""
    if not output.startswith(_DRAFT_HEADER):
        return None
    match = _DRAFT_PATTERN.match(output)
    if not match:
        return None
    return {
        "account": match.group("account").lower(),
        "to": match.group("to").strip(),
        "subject": match.group("subject").strip(),
        "body": textwrap.dedent(match.group("body")).rstrip(),
        "rawText": output,
    }
