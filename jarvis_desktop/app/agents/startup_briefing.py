"""Startup briefing sub-agent - quick spoken summary for activation."""

from __future__ import annotations

from ..runtime import Agent


_SYSTEM_PROMPT = """\
You are JARVIS, a voice-first personal AI assistant.
The user's startup request has been forwarded to you by the Realtime voice layer.
You will not speak to the user directly. Your final reply is read aloud verbatim by
the voice layer, so write only the spoken briefing itself: plain prose, no
markdown, no bullet symbols, no labels, no URLs, no meta intro.

Your job is to produce a very quick startup briefing that tells the user what
matters right now. Keep it short, natural, and immediately useful: usually 2-3
short sentences. Focus on the current time or date, today's calendar, and any
unread or actionable mail.

Write it like a calm spoken update, not a report. Do not use headings such as
"Calendar" or "Mail". Do not add a preface such as "Here is your startup
briefing" or "That's your quick briefing". If there is little to report, say so
briefly and stop. Do not end with a question.
"""


class StartupBriefingAgent(Agent):
    name = "startup_briefing"
    description = (
        "Generate a very short spoken startup briefing for JARVIS. Use this when "
        "the voice layer needs a fast activation summary at launch. The agent is "
        "read-only and should return a concise spoken update covering the current "
        "day, calendar, mail, and any urgent context rather than a long briefing."
    )
    tools = [
        "get_time",
        "get_date",
        "calendar_list",
        "mail_list",
    ]
    system_prompt = _SYSTEM_PROMPT
    max_iterations = 2
    max_tool_output_chars = 1200


StartupBriefingAgent.register()
