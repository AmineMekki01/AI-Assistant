# JARVIS documentation

These pages describe the backend as it runs today. Start here when setting up
the project or tracing a request through the system.

| Page | Use it for |
| --- | --- |
| [Getting started](getting-started.md) | Install, configure, run, and check the backend. |
| [Architecture](architecture.md) | Understand component ownership and data flow. |
| [Voice](voice.md) | Understand wake word, follow-up listening, interruption, and speaker verification. |
| [Memory](memory.md) | Run Qdrant and understand storage, duplicate handling, and retrieval. |
| [Knowledge retrieval](knowledge.md) | Understand Obsidian chunking, hybrid indexing, and search. |
| [Capabilities](capabilities.md) | Add or change tools, actions, skills, and agents safely. |
| [Operations](operations.md) | Configure ports and timeouts, inspect health, and diagnose common failures. |
| [Refactoring roadmap](refactoring-roadmap.md) | See completed boundaries and the safe order for the remaining cleanup. |

The frontend has its own build and runtime. This documentation covers the
Python backend in `jarvis_desktop/`.
