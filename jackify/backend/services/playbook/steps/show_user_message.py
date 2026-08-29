"""
show_user_message step: validate and queue a message for the runtime to show at the end of
the hook (never modally mid-install). This module never displays anything itself - backend
code stays UI-agnostic; the runtime/GUI layer renders `StepResult.data` once the hook finishes.
"""
from ..url_policy import UrlPolicyError, validate_https_allowlisted_url
from .base import StepContext, StepResult

_TITLE_MAX = 80
_BODY_MAX = 600


def completed(ctx: StepContext, step) -> bool:
    # Showing a message has no persistent effect to check for - it always "runs" (i.e. queues)
    # exactly once per hook, same as every other pass-through step with no completed_when.
    return False


def execute(ctx: StepContext, step) -> StepResult:
    fields = step.fields
    title = fields.get("title", "")
    body = fields.get("body", "")
    severity = fields.get("severity", "info")

    if not title or not body:
        return StepResult(False, "show_user_message: title and body are both required")
    if len(title) > _TITLE_MAX:
        return StepResult(False, f"show_user_message: title exceeds {_TITLE_MAX} chars")
    if len(body) > _BODY_MAX:
        return StepResult(False, f"show_user_message: body exceeds {_BODY_MAX} chars")

    url = fields.get("url")
    if url is not None:
        try:
            validate_https_allowlisted_url(url, "show_user_message.url")
        except UrlPolicyError as e:
            return StepResult(False, f"show_user_message: {e}")

    return StepResult(True, data={"severity": severity, "title": title, "body": body, "url": url})
