"""
Tool compatibility configuration service.

Applies Wine registry settings required for modding tools to work correctly
on Linux. Applied automatically during prefix setup and available as a
standalone operation for existing prefixes.

Based on research into NaK's registry configuration (external reference only).
"""

import json
import logging
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from jackify.backend.services.dotnet10_installer import (
    find_winetricks_bin,
    install_dotnet10_desktop_runtime as _install_dotnet10_desktop_runtime,
    install_dotnet_sdk as _install_dotnet_sdk,
)
from jackify.backend.services.nuget_signature_service import (
    configure_nuget_signature_policy,
    install_nuget_cert,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry content
# ---------------------------------------------------------------------------

# xEdit family executables that require WinXP compatibility mode.
# Wine's default Windows version causes xEdit to fail on certain operations.
_XEDIT_EXECUTABLES = [
    "SSEEdit.exe", "SSEEdit64.exe",
    "FO4Edit.exe", "FO4Edit64.exe",
    "TES4Edit.exe", "TES4Edit64.exe",
    "xEdit64.exe",
    "SF1Edit64.exe",
    "FNVEdit.exe", "FNVEdit64.exe",
    "xFOEdit.exe", "xFOEdit64.exe",
    "xSFEEdit.exe", "xSFEEdit64.exe",
    "xTESEdit.exe", "xTESEdit64.exe",
    "FO3Edit.exe", "FO3Edit64.exe",
]

# DLL overrides applied to the prefix globally.
# All set to native,builtin so game/tool-provided DLLs take priority.
_DLL_OVERRIDES = [
    "dwrite",
    "winmm",
    "version",
    "dxgi",
    "dbghelp",
    "d3d12",
    "wininet",
    "winhttp",
    "dinput",
    "dinput8",
]


def _build_reg_content(apply_engine_mscoree: bool = True, install_dotnet_sdk: bool = False) -> str:
    lines = ["Windows Registry Editor Version 5.00", ""]

    # xEdit WinXP compatibility
    for exe in _XEDIT_EXECUTABLES:
        lines.append(f"[HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\{exe}]")
        lines.append('"Version"="winxp"')
        lines.append("")

    # Pandora Behaviour Engine - decorated window causes UI glitches on Linux
    lines.append("[HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\Pandora Behaviour Engine+.exe\\X11 Driver]")
    lines.append('"Decorated"="N"')
    lines.append("")

    # Skyrim SE / SKSE game process needs native mscoree to load dotnet4 correctly.
    # Scoped to SkyrimSE.exe only so it does not interfere with .NET 9/10 tools
    # (Synthesis, SDK host) that run in the same prefix. Enderal SE also runs as
    # SkyrimSE.exe under the hood, so this entry must be skipped there - it would
    # apply to Enderal's own game process and crash it (apply_engine_mscoree=False).
    if apply_engine_mscoree:
        lines.append("[HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\SkyrimSE.exe\\DllOverrides]")
        lines.append('"*mscoree"="native"')
        lines.append("")

    # Prevent Wine windows from stealing keyboard focus via WM_TAKE_FOCUS.
    # Without this, each Wine subprocess launched during winetricks installs
    # briefly grabs X11 focus (via XWayland), interrupting whatever the user
    # is typing in other applications.
    lines.append("[HKEY_CURRENT_USER\\Software\\Wine\\X11 Driver]")
    lines.append('"UseTakeFocus"="N"')
    lines.append("")

    # Global DLL overrides
    lines.append("[HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides]")
    for dll in _DLL_OVERRIDES:
        lines.append(f'"{dll}"="native,builtin"')
    lines.append("")

    # Disable MSBuild/Roslyn shared compiler server. Under Wine, VBCSCompiler's
    # named pipe IPC is unreliable (mono/mono#11406), so each dotnet build falls
    # back to spawning its own dotnet.exe instead of reusing one server process.
    # Synthesis compiles one patcher per mod - without this, those pile up
    # unreaped and can consume tens of GB of RAM. Writing to HKCU\Environment is
    # the registry equivalent of setx, so every process in the prefix (including
    # Synthesis's internal dotnet build calls) inherits these automatically.
    #
    # MSBUILDDISABLENODEREUSE alone only stops node reuse - it does not cap how
    # many patcher builds Synthesis fires off at once, which on large lists
    # (Tuxborn-sized) spawned ~150 concurrent dotnet.exe processes and OOM'd the
    # host. DOTNET_PROCESSOR_COUNT makes the CLR report 8 logical processors,
    # which caps Parallel.ForEach/Task-based concurrency that defaults to
    # Environment.ProcessorCount (including Synthesis's own patcher scheduler).
    #
    # The two NUGET_* entries are needed for NuGet package signature validation
    # (Synthesis fails to compile patchers without it): offline revocation mode
    # avoids online CRL/OCSP checks that routinely fail or time out under Wine's
    # sandboxed networking, and the experimental chain-build retry policy works
    # around a known NuGet flake where the first chain build after a fresh cert
    # import races and fails (NuGet/Home#11099). Both are written here rather
    # than only passed to our own subprocess calls so Synthesis itself inherits
    # them when launched later via Steam, matching Fluorine-Manager's
    # confirmed-working NuGet signature fix.
    lines.append("[HKEY_CURRENT_USER\\Environment]")
    lines.append('"UseSharedCompilation"="false"')
    lines.append('"MSBUILDDISABLENODEREUSE"="1"')
    lines.append('"DOTNET_PROCESSOR_COUNT"="8"')
    lines.append('"NUGET_CERT_REVOCATION_MODE"="offline"')
    lines.append('"NUGET_EXPERIMENTAL_CHAIN_BUILD_RETRY_POLICY"="10,1000"')

    # The dotnet SDK/runtime are ZIP-extracted, not installed via the real EXE
    # installer, which normally adds Program Files\dotnet to the system Path.
    # Without it, anything that shells out to a bare "dotnet" command (Synthesis
    # calls `dotnet --info` on startup via Process.Start) fails with
    # Win32Exception "File not found" even though the SDK is present on disk.
    # Standard Windows system directories are kept alongside it so nothing else
    # that relies on PATH lookup regresses.
    if install_dotnet_sdk:
        lines.append(
            '"Path"="C:\\\\Program Files\\\\dotnet;C:\\\\windows\\\\system32;C:\\\\windows;'
            'C:\\\\windows\\\\System32\\\\Wbem;C:\\\\windows\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\"'
        )

    lines.append("")

    return "\r\n".join(lines)


# fxc2 build of d3dcompiler_47 - required for Community Shaders shader compilation.
# The winetricks-provided d3dcompiler_47 lacks support for certain shader models
# used by Community Shaders, causing "failed shaders" during compilation.
_FXC2_D3DCOMPILER_URL = "https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47.dll"
_FXC2_D3DCOMPILER_FILENAME = "fxc2_d3dcompiler_47.dll"


def _install_fxc2_d3dcompiler(
    prefix_path: Path,
    log: Callable[[str], None],
) -> bool:
    """
    Replace the winetricks-installed d3dcompiler_47.dll with the Mozilla fxc2
    build, which supports shader models required by Community Shaders.
    Applies to both system32 (64-bit) and syswow64 (32-bit) locations.
    """
    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_dll = cache_dir / _FXC2_D3DCOMPILER_FILENAME

        if not cached_dll.exists():
            log("Downloading fxc2 d3dcompiler_47.dll...")
            urllib.request.urlretrieve(_FXC2_D3DCOMPILER_URL, cached_dll)
            log("fxc2 d3dcompiler_47.dll downloaded")
        else:
            log("fxc2 d3dcompiler_47.dll already cached, skipping download")

        import shutil
        targets = [
            prefix_path / "drive_c" / "windows" / "system32" / "d3dcompiler_47.dll",
            prefix_path / "drive_c" / "windows" / "syswow64" / "d3dcompiler_47.dll",
        ]
        for target in targets:
            if target.parent.exists():
                shutil.copy2(cached_dll, target)
                log(f"Installed fxc2 d3dcompiler_47.dll -> {target.parent.name}")

        return True

    except Exception as e:
        log(f"Failed to install fxc2 d3dcompiler_47.dll (non-fatal): {e}")
        return False


def _set_windows_version_win11(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> None:
    """
    Set the Wine prefix Windows version to Windows 11.
    Matches Fluorine's prefix configuration; required for .NET 9/10 to run
    correctly. winetricks components may leave the prefix at a lower version.
    """
    try:
        winetricks_bin = find_winetricks_bin()
        if not winetricks_bin:
            log("Bundled winetricks not found - skipping Windows version update")
            return

        log("Setting Windows version to Windows 11...")
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        env["WINE"] = wine_bin
        env["WINEDEBUG"] = "-all"
        env["DISPLAY"] = env.get("DISPLAY", ":0")

        result = subprocess.run(
            [winetricks_bin, "-q", "win11"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            log(f"winetricks win11 exited with code {result.returncode} (non-fatal)")
        else:
            log("Windows version set to Windows 11")

    except subprocess.TimeoutExpired:
        log("winetricks win10 timed out (non-fatal)")
    except Exception as e:
        log(f"Failed to set Windows version: {e} (non-fatal)")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def apply_tool_config(
    compatdata_path: str,
    wine_bin: str,
    log: Optional[Callable[[str], None]] = None,
    install_dotnet_sdk: bool = False,
    install_fxc2_d3dcompiler: bool = False,
    preserve_global_mscoree: bool = False,
    apply_engine_mscoree: bool = True,
) -> bool:
    """
    Apply tool compatibility settings to the Wine prefix.

    install_dotnet_sdk=True downloads and installs the .NET 10 SDK and flips the
    prefix to Windows 11, which are required for Synthesis. Intentionally opt-in -
    the download is ~220MB and the win11 flip has not been verified against NSF/CSF
    prefixes (see preserve_global_mscoree).
    The NuGet Root CA certs (also required for Synthesis) are only imported when
    the SDK is present, since the trusted-root PEM bundles ship inside the SDK
    (see nuget_signature_service.install_nuget_cert).

    install_fxc2_d3dcompiler=True replaces d3dcompiler_47.dll with the Mozilla
    fxc2 build. Only appropriate for Skyrim SE/AE modlists using Community Shaders.

    apply_engine_mscoree=False skips the SkyrimSE.exe-scoped native mscoree
    AppDefaults entry while still applying everything else (xEdit, Pandora, DLL
    overrides, dotnet SDK/NuGet). Set False for Enderal SE, whose own game process
    is also SkyrimSE.exe - the entry would apply to Enderal itself and crash it.

    Returns True if registry settings applied successfully (dotnet SDK install
    failures are non-fatal since the registry settings still have value).
    """
    def _log(msg: str):
        logger.info(msg)
        if log:
            log(msg)

    prefix_path = Path(compatdata_path) / "pfx"
    if not prefix_path.exists():
        _log(f"Wine prefix not found at {prefix_path}")
        return False

    if install_fxc2_d3dcompiler:
        _install_fxc2_d3dcompiler(prefix_path, _log)

    if install_dotnet_sdk:
        _install_dotnet_sdk(prefix_path, wine_bin, _log)
        _install_dotnet10_desktop_runtime(prefix_path, wine_bin, _log)
        _set_windows_version_win11(prefix_path, wine_bin, _log)

    # Remove legacy global *mscoree=native from DllOverrides if present.
    # Old installs wrote this globally, which breaks .NET 9/10 bootstrap (Synthesis).
    # The targeted AppDefaults\SkyrimSE.exe entry written below replaces it.
    # NSF/CSF modlists are the exception: NetScriptFramework's mixed-mode runtime needs the
    # global override to host the CLR (the per-exe entry alone is insufficient), so it is kept.
    if preserve_global_mscoree:
        _log("Preserving global *mscoree=native (NSF/CSF modlist)")
    else:
        try:
            env_clean = os.environ.copy()
            env_clean["WINEPREFIX"] = str(prefix_path)
            env_clean["WINEDEBUG"] = "-all"
            env_clean["DISPLAY"] = env_clean.get("DISPLAY", ":0")
            subprocess.run(
                [wine_bin, "reg", "delete",
                 "HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides",
                 "/v", "*mscoree", "/f"],
                env=env_clean, capture_output=True, text=True, timeout=15,
            )
            _log("Removed legacy global *mscoree override (if present)")
        except Exception as e:
            _log(f"Note: could not remove legacy mscoree entry (non-fatal): {e}")

    # _build_reg_content() writes UseSharedCompilation=false and
    # MSBUILDDISABLENODEREUSE=1, which prevent the Roslyn shared compiler server
    # hang under Wine (see module docstring history). Must be in place before
    # anything invokes dotnet in the prefix - without these keys the first
    # "dotnet run" can hang on VBCSCompiler's named pipe and leave an orphaned
    # dotnet.exe/winedevice.exe spinning at high CPU indefinitely (confirmed
    # reproducible during the original cert-import ordering bug).
    reg_content = _build_reg_content(
        apply_engine_mscoree=apply_engine_mscoree,
        install_dotnet_sdk=install_dotnet_sdk,
    )
    regedit_ok = False

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".reg", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(reg_content)
            reg_file = tf.name

        _log("Applying tool compatibility registry settings...")
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        env["WINEDEBUG"] = "-all"
        env["DISPLAY"] = env.get("DISPLAY", ":0")

        result = subprocess.run(
            [wine_bin, "regedit", reg_file],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            _log(f"wine regedit exited with code {result.returncode}: {result.stderr[:200]}")
        else:
            _log(f"Tool compatibility settings applied ({len(_XEDIT_EXECUTABLES)} xEdit variants, Pandora, {len(_DLL_OVERRIDES)} DLL overrides)")
            regedit_ok = True

    except subprocess.TimeoutExpired:
        _log("wine regedit timed out after 30 seconds")
    except Exception as e:
        _log(f"Failed to apply tool config: {e}")
    finally:
        try:
            os.unlink(reg_file)
        except Exception:
            pass

    # configure_nuget_signature_policy replaces any existing NuGet.Config that
    # lacks our trust policy (e.g. an SDK-generated stub from a restore that
    # ran before this step, possibly under an older Jackify version).
    configure_nuget_signature_policy(prefix_path, _log)

    # NuGet cert import requires the .NET SDK already present (the trusted-root
    # PEM bundles ship inside the SDK). On NSF/CSF prefixes
    # (install_dotnet_sdk=False) the SDK is not installed, so this is skipped
    # there - those modlists don't run Synthesis in the same prefix.
    install_nuget_cert(prefix_path, wine_bin, _log)

    return regedit_ok


def setup_nemesis_compatibility(
    modlist_dir: str,
    stock_game_path: Optional[str],
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """
    Prepare Nemesis Unlimited Behavior Engine to run correctly on Linux.

    Two issues affect Nemesis under Wine/MO2 on Linux:
    1. Nemesis resolves a relative `mods` path against the filesystem root,
       causing a "cannot access /mods" error. Symlinking Nemesis_Engine from
       the mod directory into the real Data directory fixes this.
    2. A non-blank "Start In" (workingDirectory) in ModOrganizer.ini causes
       Nemesis to hang. Blank it out for the Nemesis executable entry.

    Non-fatal - logs failures but does not raise.
    """
    def _log(msg: str):
        logger.info(msg)
        if log:
            log(msg)

    modlist_path = Path(modlist_dir)
    mods_dir = modlist_path / "mods"

    if not mods_dir.is_dir():
        _log("Nemesis setup: mods directory not found, skipping")
        return

    # Find the Nemesis_Engine directory inside the mods tree
    nemesis_engine_src: Optional[Path] = None
    try:
        for mod_dir in mods_dir.iterdir():
            candidate = mod_dir / "Nemesis_Engine"
            if candidate.is_dir():
                nemesis_engine_src = candidate
                break
    except Exception as e:
        _log(f"Nemesis setup: error scanning mods directory: {e}")
        return

    if nemesis_engine_src is None:
        _log("Nemesis setup: Nemesis_Engine not found in mods - modlist may not include Nemesis")
        if stock_game_path:
            stale_symlink = Path(stock_game_path) / "Data" / "Nemesis_Engine"
            if stale_symlink.is_symlink():
                try:
                    stale_symlink.unlink()
                    _log(f"Nemesis setup: removed stale symlink at {stale_symlink} (source mod no longer present)")
                except Exception as e:
                    _log(f"Nemesis setup: failed to remove stale symlink at {stale_symlink}: {e}")
        return

    # Create symlink in Data/ so Nemesis can find its engine at a predictable path
    if stock_game_path:
        data_dir = Path(stock_game_path) / "Data"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            symlink_path = data_dir / "Nemesis_Engine"
            if symlink_path.is_symlink():
                existing_target = symlink_path.resolve()
                if existing_target == nemesis_engine_src.resolve():
                    _log("Nemesis setup: symlink already correct, skipping")
                else:
                    symlink_path.unlink()
                    symlink_path.symlink_to(nemesis_engine_src)
                    _log(f"Nemesis setup: updated symlink at {symlink_path}")
            elif symlink_path.exists():
                _log(f"Nemesis setup: {symlink_path} exists and is not a symlink - leaving it alone")
            else:
                symlink_path.symlink_to(nemesis_engine_src)
                _log(f"Nemesis setup: created symlink {symlink_path} -> {nemesis_engine_src}")
        except Exception as e:
            _log(f"Nemesis setup: failed to create symlink: {e}")
    else:
        _log("Nemesis setup: no stock game path available - skipping symlink")

    # Blank workingDirectory for the Nemesis executable in ModOrganizer.ini
    mo2_ini = modlist_path / "ModOrganizer.ini"
    if not mo2_ini.is_file():
        _log("Nemesis setup: ModOrganizer.ini not found, skipping workingDirectory fix")
        return

    try:
        content = mo2_ini.read_text(encoding="utf-8")
    except Exception as e:
        _log(f"Nemesis setup: could not read ModOrganizer.ini: {e}")
        return

    import re

    # Find all executable indices whose binary points to Nemesis
    nemesis_indices = re.findall(
        r'^(\d+)\\binary=.*Nemesis Unlimited Behavior Engine\.exe',
        content,
        re.MULTILINE | re.IGNORECASE,
    )

    if not nemesis_indices:
        _log("Nemesis setup: no Nemesis executable entry found in ModOrganizer.ini")
        return

    modified = content
    changed = 0
    for idx in nemesis_indices:
        # Replace non-blank workingDirectory for this index
        pattern = rf'^({re.escape(idx)}\\workingDirectory=).+$'
        replacement = rf'\g<1>'
        new_content, n = re.subn(pattern, replacement, modified, flags=re.MULTILINE)
        if n:
            modified = new_content
            changed += n

    if changed:
        try:
            mo2_ini.write_text(modified, encoding="utf-8")
            _log(f"Nemesis setup: blanked workingDirectory for {len(nemesis_indices)} Nemesis executable entry(s) in ModOrganizer.ini")
        except Exception as e:
            _log(f"Nemesis setup: failed to write ModOrganizer.ini: {e}")
    else:
        _log("Nemesis setup: workingDirectory already blank for all Nemesis entries")


def apply_tool_config_for_appid(
    appid: str,
    log: Optional[Callable[[str], None]] = None,
    install_dotnet_sdk: bool = True,
) -> bool:
    """
    Resolve compatdata path and wine binary from an AppID, then apply tool config.
    Convenience wrapper for the standalone Additional Tasks flow.
    """
    def _log(msg: str):
        logger.info(msg)
        if log:
            log(msg)

    apply_engine_mscoree = True
    modlist_dir: Optional[str] = None
    try:
        from jackify.backend.handlers.modlist_handler import ModlistHandler
        handler = ModlistHandler()
        for shortcut in handler.discover_executable_shortcuts("ModOrganizer.exe"):
            if str(shortcut.get("appid", "")) == str(appid):
                modlist_dir = shortcut.get("path") or None
                if handler.detect_special_game_type(shortcut.get("path", "")) == "enderal":
                    apply_engine_mscoree = False
                break
    except Exception as e:
        _log(f"Could not determine game type for AppID {appid}, applying default tool config: {e}")

    try:
        from jackify.backend.handlers.wine_utils_proton import WineUtilsProtonMixin
        compatdata_path, _, wine_bin = WineUtilsProtonMixin.get_proton_paths(appid)
    except Exception as e:
        _log(f"Could not resolve Proton paths for AppID {appid}: {e}")
        return False

    if not compatdata_path or not wine_bin:
        _log(f"Could not resolve Wine prefix for AppID {appid}. Is this modlist configured in Steam?")
        return False

    result = apply_tool_config(
        compatdata_path, wine_bin, log,
        install_dotnet_sdk=install_dotnet_sdk,
        install_fxc2_d3dcompiler=True,
        apply_engine_mscoree=apply_engine_mscoree,
    )

    if modlist_dir:
        from jackify.backend.services.synthesis_updater import update_synthesis
        update_synthesis(modlist_dir, log=log)

    return result
