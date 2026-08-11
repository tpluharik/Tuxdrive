"""Desktop-independent helpers for Nautilus availability actions."""

from __future__ import annotations


def command_line_path(arguments: list[str], name: str) -> str:
    """Read both ``--name PATH`` and ``--name=PATH`` fallback forms."""
    option_name = f"--{name}"
    for index, argument in enumerate(arguments):
        if argument == option_name and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(option_name + "="):
            return argument.split("=", 1)[1]
    return ""


def availability_route(*, mounted: bool, runtime_ready: bool, enabled: bool) -> str:
    """Choose immediate hydration, mount startup, or a cold-start queue."""
    if mounted:
        return "dispatch"
    if runtime_ready and enabled:
        return "start-mount"
    return "queue"


def verified_rules_after(
    verified: set[str],
    configured: list[str],
    relative: str,
    available: bool,
) -> set[str]:
    """Return only offline rules whose latest hydration has completed."""
    result = set(verified)
    if available and relative in configured:
        if relative == ".":
            result.clear()
        else:
            result = {
                item for item in result
                if not item.startswith(relative.rstrip("/") + "/")
            }
        result.add(relative)
    elif not available:
        result.intersection_update(configured)
    return result
