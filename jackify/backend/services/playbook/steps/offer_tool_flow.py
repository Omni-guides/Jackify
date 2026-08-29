"""
offer_tool_flow step: hand off to an existing interactive Jackify workflow.

The Begin Again case: the playbook supplies the `match`/`confirm` (this modlist needs TTW),
Jackify supplies the actual interactive flow. This module cannot run that flow itself - it has
no GUI dependency - so execute() only validates and queues the request; the runtime/GUI layer
is responsible for actually invoking the named flow after the hook finishes.
"""
from .base import StepContext, StepResult, default_completed

completed = default_completed

# Enum of flows Jackify actually implements. Kept as an explicit allow-list rather than an
# arbitrary string, since this is a handoff point into real interactive workflows.
_VALID_FLOWS = {"ttw_install"}


def execute(ctx: StepContext, step) -> StepResult:
    flow = step.fields.get("flow")
    if flow not in _VALID_FLOWS:
        return StepResult(False, f"offer_tool_flow: unknown flow {flow!r}")
    return StepResult(True, data={"offer_flow": flow})
