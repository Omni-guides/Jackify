import json
import re
from typing import Optional
from jackify.shared.errors import (
    JackifyError, InstallError, OAuthError,
    oauth_expired, wabbajack_install_failed, format_technical_context,
    game_not_found_for_modlist,
)

_HTTP_TIMEOUT_RE = re.compile(
    r"httpclient\.timeout|request was canceled.*timeout|timed?\s*out.*elaps",
    re.IGNORECASE,
)

_NEXUS_DOWNLOAD_RE = re.compile(
    r"Game:\s*([A-Za-z0-9]+),\s*ModID:\s*(\d+)",
    re.IGNORECASE,
)

_NEXUS_GAME_SLUGS = {
    "skyrimspecialedition": "skyrimspecialedition",
    "skyrim": "skyrim",
    "skyrimvr": "skyrimvr",
    "fallout4": "fallout4",
    "fallout4vr": "fallout4vr",
    "falloutneeds": "newvegas",
    "falloutnewvegas": "newvegas",
    "fallout3": "fallout3",
    "oblivion": "oblivion",
    "oblivionremastered": "oblivionremastered",
    "starfield": "starfield",
    "baldursgate3": "baldursgate3",
}


def nexus_url_from_error_line(line: str) -> Optional[str]:
    """Extract a Nexus mod page URL from an engine download-failure line, or return None."""
    m = _NEXUS_DOWNLOAD_RE.search(line)
    if not m:
        return None
    game_raw = m.group(1).lower()
    mod_id = m.group(2)
    slug = _NEXUS_GAME_SLUGS.get(game_raw, game_raw)
    return f"https://www.nexusmods.com/{slug}/mods/{mod_id}"


def _ctx_detail(ctx: dict) -> Optional[str]:
    if not ctx:
        return None
    return format_technical_context(context=ctx)


def _download_timeout_error(detail: str, ctx: dict) -> InstallError:
    return InstallError(
        "Download Timed Out",
        "A download request timed out before completing.",
        suggestion="Retry the install - Wabbajack will resume from where it stopped.",
        solutions=[
            "Re-run the install - Wabbajack resumes and will reattempt timed-out downloads.",
            "Check your internet connection is stable.",
            "Disable VPN or proxy if active.",
            "Check if Nexus Mods is reachable at nexusmods.com.",
            "If timeouts persist, try installing during off-peak hours or from a faster connection.",
        ],
        technical=_ctx_detail(ctx) or detail,
    )


def _engine_error(msg: str, ctx: dict) -> InstallError:
    """Map generic engine_error payloads to user-visible, actionable InstallError variants."""
    text = (msg or "").strip()
    if _HTTP_TIMEOUT_RE.search(text):
        return _download_timeout_error(text, ctx)

    match = re.search(r"can't find game\s+([A-Za-z0-9_:-]+)", text, flags=re.IGNORECASE)
    if match:
        game_name = match.group(1)
        return game_not_found_for_modlist(game_name, detail=text)

    return InstallError(
        "Install Engine Error",
        text or "An install engine error occurred.",
        suggestion="Review the error message and retry after correcting the reported issue.",
        solutions=[
            "Check the exact error message shown above and fix the prerequisite it mentions.",
            "Retry the install after restarting Steam.",
            "If this persists, check Modlist_Install_workflow.log for the same error text.",
        ],
        technical=_ctx_detail(ctx),
    )


_TYPE_MAP = {
    "engine_error": _engine_error,
    "auth_failed": lambda msg, ctx: oauth_expired(),
    "premium_required": lambda msg, ctx: InstallError(
        "Nexus Premium Required",
        msg,
        suggestion="Jackify requires a Nexus Premium account for automated installs.",
        solutions=[
            "Log in to Nexus Mods with a Premium account.",
            "Non-premium support is planned for a future release.",
        ],
    ),
    "network_error": lambda msg, ctx: InstallError(
        "Network or Download Failure",
        msg,
        suggestion="Check your internet connection and retry.",
        solutions=[
            "Verify your internet connection.",
            "Re-run the install - Wabbajack resumes from where it stopped.",
            "Check if Nexus Mods is reachable at nexusmods.com.",
            "Disable VPN or proxy if active.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "disk_full": lambda msg, ctx: InstallError(
        "Disk Full",
        msg,
        suggestion="Free space on the target drive and retry.",
        solutions=[
            "Run: df -h to see available space.",
            "Delete old modlist downloads or backups.",
            "Move the install to a larger drive.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "permission_denied": lambda msg, ctx: InstallError(
        "Permission Denied",
        msg,
        suggestion="Check write permissions on the target path.",
        solutions=[
            "Ensure Jackify and Steam are run as the same user.",
            "Avoid install paths under /usr, /var, or /opt.",
            f"Check permissions: ls -la {ctx.get('path', '<path>')}",
        ],
        technical=_ctx_detail(ctx),
    ),
    "archive_corrupt": lambda msg, ctx: InstallError(
        "Corrupted Archive",
        msg,
        suggestion="Re-run the install - Wabbajack will re-download and re-verify the file.",
        solutions=[
            "Re-run the install.",
            "Check available disk space (partial downloads appear corrupt).",
            "Check Modlist_Install_workflow.log for the specific filename.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "file_not_found": lambda msg, ctx: InstallError(
        "File Not Found",
        msg,
        suggestion="Check the modlist URL and your game installation paths.",
        solutions=[
            "Verify the modlist name is correct.",
            "Ensure the target game is installed.",
            "Re-run - the modlist index may have been temporarily unavailable.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "validation_failed": lambda msg, ctx: InstallError(
        "Validation Failed",
        msg,
        suggestion="Re-run the install to re-download any failed files.",
        solutions=[
            "Re-run the install - Wabbajack resumes and re-validates.",
            "Check available disk space.",
            "Check Modlist_Install_workflow.log for specific failures.",
        ],
        technical=_ctx_detail(ctx),
    ),
    "download_stalled": lambda msg, ctx: InstallError(
        "Downloads Stalled",
        msg,
        suggestion="Check your connection and OAuth status, then retry.",
        solutions=[
            "Check your internet connection.",
            "In Settings, confirm Nexus OAuth is active.",
            "Re-run the install.",
        ],
    ),
}


def _exit_code_6_error(detail: str, context: dict) -> JackifyError:
    if detail and _HTTP_TIMEOUT_RE.search(detail):
        return _download_timeout_error(detail, context)
    return wabbajack_install_failed(format_technical_context(detail=detail, context=context) or detail)


_EXIT_CODE_MAP = {
    2: lambda d, c: _TYPE_MAP["auth_failed"](d, c or {}),
    3: lambda d, c: _TYPE_MAP["network_error"](d, c or {}),
    4: lambda d, c: _TYPE_MAP["disk_full"](d, c or {}),
    5: lambda d, c: _TYPE_MAP["validation_failed"](d, c or {}),
    6: _exit_code_6_error,
}


def parse_engine_error_line(line: str) -> Optional[JackifyError]:
    """Parse one stderr line. Returns JackifyError or None."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if obj.get("je") != "1":
        return None
    if obj.get("level") == "warning":
        return None
    error_type = obj.get("type", "engine_error")
    message = obj.get("message", "An unknown engine error occurred.")
    context = obj.get("context") or {}
    factory = _TYPE_MAP.get(error_type)
    if factory:
        return factory(message, context)
    return wabbajack_install_failed(f"[{error_type}] {message}")


def error_from_exit_code(exit_code: int, detail: str = "", context: Optional[dict] = None) -> Optional[JackifyError]:
    """Return a JackifyError based on exit code alone (fallback when no stderr line received)."""
    factory = _EXIT_CODE_MAP.get(exit_code)
    if factory:
        detail_message = detail or f"Engine exited with code {exit_code}."
        return factory(detail_message, context or {})
    return None
