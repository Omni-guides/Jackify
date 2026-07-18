"""
Synthesis patcher version bump for modlists that bundle it.

Bundled Synthesis builds as old as 0.29.2 and as recent as 0.35.3 crash listing
patchers whenever the live Mutagen-Modding/Synthesis.Registry listing contains a
GameRelease enum member the bundled Mutagen.Bethesda assembly doesn't recognize
(confirmed 2026-07-17: the registry added "EnderalSEGog" on 2026-07-14, breaking
every Synthesis build up to and including 0.35.3, on Linux and Windows alike).
0.36.5 ships the mutagen bump that fixes the parser. Since Synthesis isn't
installed by Jackify at all - it comes entirely from whatever the modlist's own
MO2 download bundled - the fix is to overwrite it in place with a known-good
release, only for modlists that actually include it.
"""

import json
import logging
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_TARGET_VERSION = "0.36.5"
_SYNTHESIS_ZIP_URL = (
    f"https://github.com/Mutagen-Modding/Synthesis/releases/download/{_TARGET_VERSION}/Synthesis.zip"
)
_VERSION_MARKER_FILENAME = ".jackify_synthesis_version"
_GUI_SETTINGS_FILENAME = "GuiSettings.json"
_PIPELINE_SETTINGS_FILENAME = "PipelineSettings.json"


def _resolve_mo2_binary_path(raw_value: str) -> Optional[Path]:
    """Convert a ModOrganizer.ini `\\binary` value (e.g. `Z:/home/deck/.../Synthesis.exe`
    or `D:\\\\home\\\\deck\\\\...\\\\Synthesis.exe`) into a real Linux Path."""
    m = re.match(r"(?i)^[a-z]:[\\/](.+)$", raw_value.strip())
    if not m:
        return None
    linux_path = m.group(1).replace("\\\\", "/").replace("\\", "/")
    return Path("/" + linux_path)


def find_synthesis_dir(modlist_dir: str) -> Optional[Path]:
    """
    Find Synthesis's install directory for a modlist by reading its
    `[customExecutables]` entry in ModOrganizer.ini, the same way
    setup_nemesis_compatibility locates Nemesis. Returns None if the
    modlist doesn't include Synthesis.
    """
    mo2_ini = Path(modlist_dir) / "ModOrganizer.ini"
    if not mo2_ini.is_file():
        return None

    try:
        content = mo2_ini.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Synthesis detection: could not read ModOrganizer.ini: %s", e)
        return None

    # jackify-engine's fresh Wabbajack extraction pads "key = value"; MO2's own
    # resave (after the user opens it once) tightens it to "key=value" - both
    # forms occur in the wild, so whitespace around '=' must be tolerated.
    match = re.search(
        r'^\d+\\binary\s*=\s*(.*Synthesis\.exe)\s*$',
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if not match:
        return None

    binary_path = _resolve_mo2_binary_path(match.group(1))
    if binary_path is None or not binary_path.is_file():
        return None

    return binary_path.parent


def _resolve_game_data_path(modlist_dir: str) -> Optional[str]:
    """
    Read MO2's own `gamePath` out of ModOrganizer.ini and return it as a
    Windows-style `<gamePath>\\Data` string, for use as Synthesis's
    DataPathOverride. gamePath is whatever Jackify/CLF3 already resolved as
    this modlist's managed game directory (StockGame, Game Root, a vanilla
    Steam/GOG/Epic install, etc.) - no separate detection needed here.
    """
    mo2_ini = Path(modlist_dir) / "ModOrganizer.ini"
    if not mo2_ini.is_file():
        return None

    try:
        content = mo2_ini.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Synthesis DataPathOverride: could not read ModOrganizer.ini: %s", e)
        return None

    match = re.search(
        r'^gamePath\s*=\s*@ByteArray\((.*)\)\s*$',
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if not match:
        return None

    # MO2 doubles every backslash (Qt escaping); some writers double that
    # again. Collapse any run of backslashes down to one, then append Data.
    game_path = re.sub(r"\\+", r"\\", match.group(1).strip())
    if not game_path:
        return None
    return f"{game_path}\\Data"


def _set_data_path_override(synthesis_dir: Path, modlist_dir: str, log: Callable[[str], None]) -> None:
    """
    Merge-patch each profile's DataPathOverride to point at this modlist's
    actual game data folder, if it isn't already correct. Bundled Synthesis
    installs often ship with this null, which leaves the field blank in
    Synthesis's own UI until the user fills it in manually.
    """
    expected = _resolve_game_data_path(modlist_dir)
    if not expected:
        return

    pipeline_settings_path = synthesis_dir / _PIPELINE_SETTINGS_FILENAME
    try:
        pipeline_settings = json.loads(pipeline_settings_path.read_text(encoding="utf-8")) if pipeline_settings_path.is_file() else {"Version": 2, "Profiles": []}
        changed = False
        for profile in pipeline_settings.get("Profiles", []):
            if profile.get("DataPathOverride") != expected:
                profile["DataPathOverride"] = expected
                changed = True
        if changed:
            pipeline_settings_path.write_text(json.dumps(pipeline_settings, indent=4), encoding="utf-8")
            log(f"Synthesis update: set DataPathOverride to {expected}")
    except Exception as e:
        log(f"Synthesis update: could not set DataPathOverride (non-fatal): {e}")


def get_installed_version(synthesis_dir: Path) -> Optional[str]:
    """Read the version Jackify last wrote to this Synthesis install, if any."""
    marker = synthesis_dir / _VERSION_MARKER_FILENAME
    if not marker.is_file():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _disable_mo2_mode(synthesis_dir: Path, log: Callable[[str], None]) -> None:
    """
    Merge-patch Synthesis's own settings files to default MO2 Mode off and
    suppress its first-run prompt, without disturbing anything else - these
    files ship pre-populated inside the Wabbajack archive with the modlist
    author's own curated patcher list, which must survive untouched.

    MO2 Mode blocks patcher building while running inside MO2's VFS (which
    can't reliably handle multithreaded dotnet build I/O), requiring a
    build-then-run two-phase workflow with no equivalent to Windows'
    "run outside MO2 once" on Linux/Proton. Confirmed via a side-by-side
    diff of two real installs (2026-07-17): the only fields that differ
    between an MO2-Mode-enabled and MO2-Mode-disabled install are
    BlockBuildingWithinMo2 (PipelineSettings.json) and HasSeenMo2Prompt
    (GuiSettings.json, which only suppresses the dialog and is set to true
    either way once a user has seen it once).
    """
    gui_settings_path = synthesis_dir / _GUI_SETTINGS_FILENAME
    try:
        gui_settings = json.loads(gui_settings_path.read_text(encoding="utf-8")) if gui_settings_path.is_file() else {"Version": 2}
        gui_settings["HasSeenMo2Prompt"] = True
        gui_settings_path.write_text(json.dumps(gui_settings, indent=4), encoding="utf-8")
    except Exception as e:
        log(f"Synthesis update: could not set HasSeenMo2Prompt (non-fatal): {e}")

    pipeline_settings_path = synthesis_dir / _PIPELINE_SETTINGS_FILENAME
    try:
        pipeline_settings = json.loads(pipeline_settings_path.read_text(encoding="utf-8")) if pipeline_settings_path.is_file() else {"Version": 2, "Profiles": []}
        pipeline_settings["BlockBuildingWithinMo2"] = False
        pipeline_settings_path.write_text(json.dumps(pipeline_settings, indent=4), encoding="utf-8")
    except Exception as e:
        log(f"Synthesis update: could not set BlockBuildingWithinMo2 (non-fatal): {e}")

    log("Synthesis update: MO2 Mode defaulted off (no Linux equivalent to launching outside MO2)")


def update_synthesis(
    modlist_dir: str,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Overwrite a modlist's bundled Synthesis with the target version if it's
    older, or if Jackify hasn't touched it before. Non-fatal - logs failures
    but does not raise.
    """
    def _log(msg: str):
        logger.info(msg)
        if log:
            log(msg)

    synthesis_dir = find_synthesis_dir(modlist_dir)
    if synthesis_dir is None:
        _log("Synthesis update: no Synthesis executable entry found, skipping")
        return False

    _set_data_path_override(synthesis_dir, modlist_dir, _log)

    if get_installed_version(synthesis_dir) == _TARGET_VERSION:
        _log(f"Synthesis update: already at {_TARGET_VERSION}, skipping")
        return True

    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path = cache_dir / f"Synthesis-{_TARGET_VERSION}.zip"

        if not zip_path.exists():
            _log(f"Downloading Synthesis {_TARGET_VERSION}...")
            urllib.request.urlretrieve(_SYNTHESIS_ZIP_URL, zip_path)
            _log("Synthesis downloaded")
        else:
            _log("Synthesis already cached, skipping download")

        _log(f"Updating Synthesis to {_TARGET_VERSION} in {synthesis_dir}...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(synthesis_dir)

        _disable_mo2_mode(synthesis_dir, _log)

        (synthesis_dir / _VERSION_MARKER_FILENAME).write_text(_TARGET_VERSION, encoding="utf-8")
        _log(f"Synthesis updated to {_TARGET_VERSION}")
        return True

    except Exception as e:
        _log(f"Synthesis update failed (non-fatal): {e}")
        return False
