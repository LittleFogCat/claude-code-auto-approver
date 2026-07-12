"""Tool-use schema for the classifier.

We force Claude to choose one of three actions:
- ``allow`` -> tool call proceeds
- ``deny``  -> tool call blocked
- ``ask``   -> prompt the human (medium-risk)
"""

from __future__ import annotations

CLASSIFY_TOOL: dict = {
    "name": "classify_tool_call",
    "description": (
        "Decide whether the proposed Claude Code tool invocation should be "
        "allowed, denied, or escalated to a human."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["allow", "deny", "ask"],
                "description": "Final decision for this tool invocation.",
            },
            "reason": {
                "type": "string",
                "description": "One short sentence explaining the decision.",
            },
            "risk_level": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
            },
        },
        "required": ["decision", "reason", "risk_level"],
    },
}