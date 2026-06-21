"""Structured error types for Jackify.

All user-facing failures should raise a JackifyError subclass so callers
can display a consistent, plain-English error dialog with actionable advice
and a numbered list of things to try.
"""
import re
from typing import Optional, List


class JackifyError(Exception):
    """Base class for all user-facing Jackify errors."""

    def __init__(self, title: str, message: str,
                 suggestion: Optional[str] = None,
                 solutions: Optional[List[str]] = None,
                 technical: Optional[str] = None):
        self.title = title
        self.message = message
        self.suggestion = suggestion
        self.solutions = solutions or []
        self.technical = technical
        super().__init__(message)


class SteamError(JackifyError):
    pass


class PrefixCreationError(JackifyError):
    pass


class ProtonNotFoundError(JackifyError):
    pass


class ModlistError(JackifyError):
    pass


class ConfigError(JackifyError):
    pass


class InstallError(JackifyError):
    pass


class TTWError(JackifyError):
    pass


class OAuthError(JackifyError):
    pass


_SENSITIVE_KEYWORDS = (
    "token",
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "oauth",
    "bearer",
    "password",
)


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(word in lowered for word in _SENSITIVE_KEYWORDS)


def _scrub_sensitive_text(text: str) -> str:
    """Best-effort redaction for key=value style sensitive fragments."""
    scrubbed = text
    # Authorization header forms: "authorization: Bearer <token>"
    scrubbed = re.sub(
        r"(?i)\bauthorization\b\s*[:=]\s*bearer\s+[A-Za-z0-9\-._~+/]+=*",
        "authorization=[REDACTED]",
        scrubbed,
    )
    # Standalone bearer form: "Bearer <token>"
    scrubbed = re.sub(
        r"(?i)\b(bearer)\s+[A-Za-z0-9\-._~+/]+=*",
        r"\1=[REDACTED]",
        scrubbed,
    )
    # Generic sensitive key/value forms.
    scrubbed = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|authorization|password|secret)\b\s*[:=]\s*([^\s,;]+)",
        r"\1=[REDACTED]",
        scrubbed,
    )
    return scrubbed


def format_technical_context(detail: Optional[str] = None, context: Optional[dict] = None) -> Optional[str]:
    """Format technical context into a readable block with secret redaction."""
    lines: List[str] = []

    if detail:
        safe_detail = _scrub_sensitive_text(str(detail).strip())
        if safe_detail:
            lines.append("Detail:")
            lines.append(safe_detail)

    if context:
        ctx_lines: List[str] = []
        for key, value in context.items():
            if _looks_sensitive_key(str(key)):
                safe_value = "[REDACTED]"
            else:
                safe_value = _scrub_sensitive_text(str(value))
            ctx_lines.append(f"- {key}: {safe_value}")
        if ctx_lines:
            if lines:
                lines.append("")
            lines.append("Context:")
            lines.extend(ctx_lines)

    if not lines:
        return None
    return "\n".join(lines)


def _logs_dir_display() -> str:
    """Return the active Jackify logs directory for user-facing guidance."""
    try:
        from jackify.shared.paths import get_jackify_logs_dir
        return str(get_jackify_logs_dir())
    except Exception:
        return "~/Jackify/logs"


# ---------------------------------------------------------------------------
# Factory functions for known failure modes.
# No GUI imports allowed here - backend code raises these directly.
# ---------------------------------------------------------------------------

def steam_still_running() -> SteamError:
    return SteamError(
        title="Steam Could Not Be Shut Down",
        message="Jackify attempted to close Steam automatically but it did not respond in time.",
        suggestion="Close Steam fully, then continue from the correct Jackify workflow.",
        solutions=[
            "Exit Steam from the Steam UI or system tray icon.",
            "Wait 10-15 seconds before continuing.",
            "If the install phase completed successfully and there is a shortcut in Steam for your modlist after restarting Steam, run 'Configure Existing Modlist' in Jackify.",
            "If the Steam shortcut is not present after restarting Steam, run 'Configure New Modlist' in Jackify.",
            f"Check Jackify logs ({_logs_dir_display()}) for the specific shutdown failure.",
            "If this repeats, open a GitHub issue and include your Jackify logs.",
        ],
    )


def proton_not_found() -> ProtonNotFoundError:
    return ProtonNotFoundError(
        title="No Proton Version Found",
        message="Jackify could not find a Proton installation to create the game prefix.",
        suggestion="Make sure Steam has registered at least one Proton version, then select it in Jackify.",
        solutions=[
            "In Steam, open Settings > Compatibility and enable Steam Play for supported/all titles.",
            "Launch any Windows game once in Steam to let Steam finish Proton setup and registration.",
            "In Jackify Settings, select your installed Proton under 'Proton Version'.",
            "If you want GE-Proton, install it with ProtonPlus or ProtonUp-Qt.",
            f"If detection still fails, check Jackify logs ({_logs_dir_display()}) and open a GitHub issue.",
        ],
    )


def shortcut_write_failed(detail: str) -> SteamError:
    return SteamError(
        title="Steam Shortcut Could Not Be Created",
        message="Jackify was unable to write the Steam shortcut for this modlist.",
        suggestion="Close Steam fully, verify userdata permissions, then continue with the correct configure flow.",
        solutions=[
            "Close Steam completely (check system tray) and retry.",
            "Check that your home directory has write permissions: ls -la ~/.steam/steam/userdata/",
            "If running Steam as Flatpak, confirm Jackify has access to the Flatpak data directory.",
            "Check available disk space: df -h ~",
            "If modlist install files are already complete, relaunch Steam manually and use 'Configure New Modlist' in Jackify.",
            f"Check Jackify logs ({_logs_dir_display()}) for the specific write error.",
            "If this keeps failing, open a GitHub issue and include your Jackify logs.",
        ],
        technical=format_technical_context(detail=detail),
    )


def prefix_creation_failed(detail: str) -> PrefixCreationError:
    return PrefixCreationError(
        title="Proton Prefix Creation Failed",
        message="Jackify could not create the Proton compatibility prefix for this modlist.",
        suggestion="Check Proton is installed and the modlist directory is accessible.",
        solutions=[
            "Confirm Steam Play is enabled in Steam > Settings > Compatibility.",
            "Launch a Windows game once in Steam so Proton is fully initialized.",
            "Confirm a Proton version is selected in Jackify Settings.",
            "Check available disk space on the modlist drive: df -h",
            "Ensure the modlist directory exists and is readable.",
            "Try closing all other Steam/Proton processes before retrying.",
            f"Check Jackify logs ({_logs_dir_display()}) for the specific failure point.",
            "If this fails consistently, open a GitHub issue and include your Jackify logs.",
        ],
        technical=format_technical_context(detail=detail),
    )


def steam_restart_failed(detail: str) -> SteamError:
    return SteamError(
        title="Steam Did Not Restart",
        message="Jackify could not confirm Steam came back after the install/configuration step.",
        suggestion="Start Steam manually, then continue with the appropriate Jackify configure flow.",
        solutions=[
            "Launch Steam manually and wait until the library is fully loaded.",
            "If Steam is showing an update prompt, complete or cancel it first.",
            "If the modlist shortcut is visible in Steam, use 'Configure Existing Modlist' in Jackify.",
            "If the shortcut is missing but install files are present, use 'Configure New Modlist' in Jackify.",
            "Do not rerun the full download/install unless you are missing modlist files.",
            f"If recovery still fails, check Jackify logs ({_logs_dir_display()}) and open a GitHub issue.",
        ],
        technical=format_technical_context(detail=detail),
    )


def modlist_not_found(path: str) -> ModlistError:
    return ModlistError(
        title="Modlist Directory Not Found",
        message=f"The modlist directory does not exist: {path}",
        suggestion="Check the path is correct and the drive is mounted.",
        solutions=[
            "Verify the path is correct and has not been moved or deleted.",
            "If the modlist is on an external drive or SD card, ensure it is mounted.",
            "On Steam Deck, SD card paths are typically under /run/media/",
            "Re-select the modlist directory in Jackify.",
        ],
    )


def game_not_found_for_modlist(game_name: str, detail: Optional[str] = None) -> InstallError:
    game = (game_name or "Unknown game").strip()
    return InstallError(
        title="Required Game Not Found",
        message=f"Jackify could not find the required base game: {game}",
        suggestion="Install the base game in Steam, launch it once, then retry.",
        solutions=[
            "Confirm the game is installed in Steam and fully updated.",
            "Launch the vanilla game once from Steam to complete first-run setup.",
            "If you have multiple Steam installs, ensure Jackify is pointed at the install that contains this game.",
            "Restart Steam and retry the install workflow.",
            f"If detection still fails, check Jackify logs ({_logs_dir_display()}) for game-detection details.",
        ],
        technical=format_technical_context(detail=detail, context={"required_game": game}),
    )


def configuration_failed(detail: str, context: Optional[dict] = None) -> ConfigError:
    return ConfigError(
        title="Post-Install Configuration Failed",
        message="Jackify could not complete the post-installation configuration for this modlist.",
        suggestion=f"Check Jackify logs ({_logs_dir_display()}) for the specific step that failed.",
        solutions=[
            "Confirm Steam is running and fully loaded before retrying.",
            "Check that the modlist AppID appears in your Steam library (look for the shortcut).",
            "Try 'Configure Existing Modlist' from the main menu to re-run configuration.",
            "Verify Proton is set correctly in Jackify Settings.",
            "If the error mentions registry or prefix, ensure sufficient disk space.",
            f"If this still fails, check Jackify logs ({_logs_dir_display()}) and open a GitHub issue with modlist name.",
        ],
        technical=format_technical_context(detail=detail, context=context),
    )


def ttw_install_failed(detail: str) -> TTWError:
    return TTWError(
        title="TTW Installation Failed",
        message="Tale of Two Wastelands could not be installed.",
        suggestion="Check that your vanilla Fallout 3 and Fallout New Vegas installs are clean and accessible.",
        solutions=[
            "Confirm vanilla Fallout 3 and Fallout New Vegas are both installed and launch correctly.",
            "If either game was previously modded, restore a clean vanilla install before retrying TTW.",
            "Ensure TTW_Linux_Installer is installed - use 'Install TTW Installer' in Additional Tasks.",
            "Check available disk space - TTW requires ~15GB free.",
            "Verify the TTW .mpi file is not corrupted (try re-downloading it).",
            f"Check Jackify logs ({_logs_dir_display()}) and TTW_Install_workflow.log for the specific failure.",
            f"If this still fails, open a GitHub issue and include logs from {_logs_dir_display()}.",
        ],
        technical=format_technical_context(detail=detail),
    )


def wabbajack_install_failed(detail: str, context: Optional[dict] = None) -> InstallError:
    return InstallError(
        title="Wabbajack Installation Failed",
        message="The modlist installation did not complete successfully.",
        suggestion=f"Check the console output and Jackify logs ({_logs_dir_display()}) for the failure reason.",
        solutions=[
            "Ensure you are logged in to Nexus Mods - check Settings > OAuth.",
            "Confirm your Nexus account has Premium access for automated downloads.",
            "Check available disk space on both the install and download drives.",
            "Re-run the install - Wabbajack resumes from where it stopped.",
            "If a specific file failed repeatedly, try downloading it manually from Nexus.",
            "Check Modlist_Install_workflow.log for the specific file that failed.",
            "If the same failure repeats with no clear workaround, open a GitHub issue with logs.",
        ],
        technical=format_technical_context(detail=detail, context=context),
    )


def oauth_expired() -> OAuthError:
    return OAuthError(
        title="Nexus Authentication Expired",
        message="Your Nexus Mods authorisation has expired or is no longer valid.",
        suggestion="In Settings, revoke the current Nexus authorisation first, then authorise again.",
        solutions=[
            "Open Jackify Settings and click 'Revoke Nexus Authorisation' first.",
            "Then click 'Authorise with Nexus Mods'.",
            "Complete the browser authorisation flow and return to Jackify.",
            "If the browser does not open automatically, copy the URL from the console and open it manually.",
            "After re-authorising, retry the failed operation.",
            f"If this keeps failing, check Jackify logs ({_logs_dir_display()}) and open a GitHub issue.",
        ],
    )


def install_dir_create_failed(path: str, detail: str) -> InstallError:
    return InstallError(
        title="Could Not Create Install Directory",
        message=f"Jackify could not create the installation directory: {path}",
        suggestion="Check you have write permission to the target drive.",
        solutions=[
            "Confirm the target drive is mounted and writable.",
            "Check available disk space: df -h",
            "Try creating the folder manually first, then retry.",
            "On Steam Deck, avoid paths under /usr or /var - use /home/deck or an SD card.",
        ],
        technical=format_technical_context(detail=detail, context={"path": path}),
    )


def manual_steps_incomplete() -> ConfigError:
    return ConfigError(
        title="Unexpected Internal Setup State",
        message="Jackify reached a setup state that should not occur in normal workflows.",
        suggestion="Restart Steam and retry once. If this appears again, treat it as a Jackify bug and report it.",
        solutions=[
            "Restart Steam and verify your modlist shortcut is visible.",
            "Retry your last Jackify action once after Steam restarts.",
            "Do not perform manual Steam shortcut or prefix setup steps.",
            f"If this state appears again, check Jackify logs ({_logs_dir_display()}) and open a GitHub issue.",
        ],
    )


def cc_content_missing(filename: str = "") -> InstallError:
    detail = f"Missing file: {filename}" if filename else ""
    is_curios = "curios" in filename.lower()

    if is_curios:
        suggestion = (
            "You likely have the Steam-delivered version of Rare Curios, which has a different file hash "
            "to the in-game version. The modlist requires the in-game version."
        )
        solutions = [
            f"Delete both Curios files ({filename.rsplit('.', 1)[0]}.bsa and .esl) from your Skyrim/Data folder.",
            "Launch Skyrim SE from Steam and go to Creations from the main menu.",
            "Select Category, then Creation Club. Find 'Rare Curios' and download it.",
            "Do NOT alt-tab while downloading - the download will stop if the game loses focus.",
            "Do NOT run Steam 'Verify Integrity' after - it will replace the file with the wrong version again.",
            "Rerun the Jackify installation.",
        ]
    else:
        suggestion = (
            "Even if the file exists on disk, it may be the Steam-delivered version with a different hash. "
            "Modlists require the in-game Creations version."
        )
        solutions = [
            "Launch Skyrim SE/AE, go to Creations from the main menu, and select 'Download All'. "
            "Wait for all downloads to complete, then retry the install.",
            "Do not use 'Verify files' in Steam - it delivers a different version of the files that will fail the same check.",
            "If a specific file is still flagged, find it in the Creations menu by name and re-download it individually.",
            "Skyrim AE via Steam Family Sharing does not transfer DLC content - you must own AE directly.",
        ]

    return InstallError(
        title="Anniversary Edition Content Missing",
        message=(
            "One or more Skyrim Anniversary Edition Creation Club files were not found "
            "in your game installation."
            + (f" ({filename})" if filename else "")
        ),
        suggestion=suggestion,
        solutions=solutions,
        technical=format_technical_context(detail=detail) if detail else None,
    )


def creation_kit_missing(game_type: str = None) -> InstallError:
    if game_type and "fallout4" in game_type.lower():
        ck_name = "Fallout 4 Creation Kit"
        steam_search = "Fallout 4: Creation Kit"
        scripts_note = []
    else:
        ck_name = "Skyrim Special Edition Creation Kit"
        steam_search = "Skyrim Special Edition: Creation Kit"
        scripts_note = [
            "When asked whether to unzip Scripts.zip, select NO - unzipping will cause the CK to crash.",
        ]
    return InstallError(
        title="Creation Kit Files Missing",
        message=(
            f"This modlist requires the {ck_name}, "
            "but its files were not found in your game installation."
        ),
        suggestion="Install the Creation Kit from Steam and open it once to register its files.",
        solutions=[
            f"In Steam, search for '{steam_search}' and install it.",
            "Right-click it in Steam > Properties > Compatibility and set a Proton version.",
            "Click Play to launch the Creation Kit.",
            *scripts_note,
            "Once the Creation Kit opens successfully, close it.",
            "Re-run the modlist install in Jackify - the required files will now be in place.",
        ],
    )


def mo2_setup_failed(detail: str) -> InstallError:
    return InstallError(
        title="Mod Organizer 2 Setup Failed",
        message="Jackify could not complete the Mod Organizer 2 setup.",
        suggestion=f"Check Jackify logs ({_logs_dir_display()}) for the specific failure.",
        solutions=[
            "Ensure you have an active internet connection - MO2 is downloaded from GitHub.",
            "Check available disk space in the install directory.",
            "Try selecting a different install directory with full write permissions.",
            "If the download failed, check GitHub is accessible (try opening it in a browser).",
        ],
        technical=format_technical_context(detail=detail),
    )


# ---------------------------------------------------------------------------
# Exception classifier.
# Maps known error substrings to specific JackifyError factory functions.
# Called by callers that catch a bare Exception and want to produce a
# structured error rather than wrapping with prefix_creation_failed().
# ---------------------------------------------------------------------------

_PATTERNS: List[tuple] = [
    # Steam / prefix / Proton
    ("no space left on device",             lambda d: InstallError("Disk Full", "There is no space left on the target drive.", suggestion="Free up disk space and retry.", solutions=["Run: df -h to see available space.", "Delete old modlist downloads or backups.", "Move the install to a larger drive."], technical=format_technical_context(detail=d))),
    ("permission denied",                   lambda d: SteamError("Permission Denied", "Jackify was refused access to a required file or directory.", suggestion="Check file permissions on the target path.", solutions=["Run: ls -la <path> to inspect permissions.", "Ensure Steam and Jackify are run as the same user.", "Avoid install paths under /usr, /var or /opt."], technical=format_technical_context(detail=d))),
    ("steamwebhelper",                      lambda d: steam_still_running()),
    ("no such file or directory.*compatdata", lambda d: proton_not_found()),
    ("proton.*not found|no proton",         lambda d: proton_not_found()),
    ("vdf.*error|binary_vdf|invalid vdf",   lambda d: SteamError("Steam VDF File Error", "A Steam configuration file (VDF) could not be read or written.", suggestion="Ensure Steam is closed and try again.", solutions=["Close Steam completely before retrying.", "Restart Steam and retry the same action.", f"Check Jackify logs ({_logs_dir_display()}) for the specific VDF path.", f"If this still fails, open a GitHub issue and include logs from {_logs_dir_display()}."], technical=format_technical_context(detail=d))),
    ("connection.*refused|connection.*timed out|network.*unreachable", lambda d: InstallError("Network Error", "Jackify could not reach a required network resource.", suggestion="Check your internet connection and retry.", solutions=["Verify your internet connection is active.", "Check if Nexus Mods is reachable at nexusmods.com.", "Disable VPN or proxy if active.", "Retry - transient network errors often resolve on the second attempt."], technical=format_technical_context(detail=d))),
    ("401|unauthorized|forbidden.*nexus",   lambda d: oauth_expired()),
    ("7z.*error|bad archive|cannot open.*archive", lambda d: InstallError("Archive Error", "A downloaded archive file is corrupted or unreadable.", suggestion="Delete the corrupted file and re-run the install to re-download it.", solutions=["Re-run the install - Wabbajack will re-download files that fail verification.", "Check available disk space (partial downloads look corrupt).", "Check Modlist_Install_workflow.log for the specific file name."], technical=format_technical_context(detail=d))),
    ("timeout",                             lambda d: SteamError("Operation Timed Out", "An operation took longer than expected and was stopped.", suggestion="Retry - timeouts are often transient.", solutions=["Retry the operation.", "If Steam is slow to start, give it more time before retrying.", "Check system load: close other applications.", f"Check Jackify logs ({_logs_dir_display()}) for which step timed out."], technical=format_technical_context(detail=d))),
]


def classify_exception(exc_str: str, fallback_factory=None) -> JackifyError:
    """Return a structured JackifyError for a raw exception string.

    Checks known error patterns in order. Returns the first match.
    Falls back to fallback_factory(exc_str) if provided, otherwise
    returns a generic prefix_creation_failed error.
    """
    import re
    lowered = exc_str.lower()
    for pattern, factory in _PATTERNS:
        if re.search(pattern, lowered):
            result = factory(exc_str)
            if not result.technical:
                result.technical = exc_str
            return result

    if fallback_factory is not None:
        return fallback_factory(exc_str)
    return prefix_creation_failed(exc_str)
