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
import zipfile
from pathlib import Path
from typing import Callable, Optional

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


def _build_reg_content() -> str:
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
    # (Synthesis, SDK host) that run in the same prefix.
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

    return "\r\n".join(lines)


# .NET 9 SDK - ZIP distribution, extracted directly to avoid running an EXE under Wine.
# Synthesis requires the SDK (not just runtime) for patcher compilation.
# Versions match Fluorine's confirmed-working prefix configuration.
_DOTNET9_SDK_URL = "https://builds.dotnet.microsoft.com/dotnet/Sdk/9.0.310/dotnet-sdk-9.0.310-win-x64.zip"
_DOTNET9_SDK_FILENAME = "dotnet-sdk-9.0.310-win-x64.zip"

# .NET Desktop Runtime 10 - provides NETCore.App + WindowsDesktop.App 10.0.2.
# Covers Synthesis patchers targeting .NET 10 runtime.
_DOTNET10_DESKTOP_URL = "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/10.0.2/windowsdesktop-runtime-10.0.2-win-x64.exe"
_DOTNET10_DESKTOP_FILENAME = "windowsdesktop-runtime-10.0.2-win-x64.exe"

# DigiCert Universal Root CA - required for NuGet package signature validation.
# Without this, dotnet fails to verify NuGet package signatures when Synthesis
# compiles patchers. Imported into the Wine prefix Windows cert store so no
# system-level changes are needed.
_DIGICERT_CERT_URL = "https://cacerts.digicert.com/DigiCertTrustedRootG4.crt.pem"
_DIGICERT_CERT_FILENAME = "DigiCertTrustedRootG4.crt.pem"

# fxc2 build of d3dcompiler_47 - required for Community Shaders shader compilation.
# The winetricks-provided d3dcompiler_47 lacks support for certain shader models
# used by Community Shaders, causing "failed shaders" during compilation.
_FXC2_D3DCOMPILER_URL = "https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47.dll"
_FXC2_D3DCOMPILER_FILENAME = "fxc2_d3dcompiler_47.dll"


def _install_dotnet9_sdk(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> bool:
    """
    Download and extract the .NET 9 SDK ZIP into the Wine prefix.
    Uses the standalone ZIP distribution to avoid running an EXE under Wine.
    Synthesis requires the full SDK (Roslyn compiler) for patcher compilation.
    """
    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        sdk_zip = cache_dir / _DOTNET9_SDK_FILENAME

        if not sdk_zip.exists():
            log(f"Downloading .NET 9 SDK ({_DOTNET9_SDK_FILENAME})...")
            urllib.request.urlretrieve(_DOTNET9_SDK_URL, sdk_zip)
            log(".NET 9 SDK downloaded")
        else:
            log(".NET 9 SDK already cached, skipping download")

        dest = prefix_path / "drive_c" / "Program Files" / "dotnet"
        dest.mkdir(parents=True, exist_ok=True)
        log("Extracting .NET 9 SDK...")
        with zipfile.ZipFile(sdk_zip) as zf:
            zf.extractall(dest)
        log(".NET 9 SDK extracted successfully")
        return True

    except Exception as e:
        log(f"Failed to install .NET 9 SDK: {e}")
        return False



def _install_dotnet10_desktop_runtime(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> bool:
    """
    Download and install the .NET Desktop Runtime 10 into the Wine prefix.
    Provides NETCore.App and WindowsDesktop.App 10.x for patchers targeting .NET 10.
    """
    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        installer = cache_dir / _DOTNET10_DESKTOP_FILENAME

        if not installer.exists():
            log(f"Downloading .NET Desktop Runtime 10 ({_DOTNET10_DESKTOP_FILENAME})...")
            urllib.request.urlretrieve(_DOTNET10_DESKTOP_URL, installer)
            log(".NET Desktop Runtime 10 downloaded")
        else:
            log(".NET Desktop Runtime 10 already cached, skipping download")

        log("Installing .NET Desktop Runtime 10...")
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        env["WINEDEBUG"] = "-all"
        env["WINEDLLOVERRIDES"] = "mshtml=d;winemenubuilder.exe=d"
        env["DISPLAY"] = env.get("DISPLAY", ":0")

        result = subprocess.run(
            [wine_bin, str(installer), "/install", "/quiet", "/norestart"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode not in (0, 3010):
            log(f".NET Desktop Runtime 10 installer exited with code {result.returncode}")
            return False

        log(".NET Desktop Runtime 10 installed successfully")
        return True

    except Exception as e:
        log(f"Failed to install .NET Desktop Runtime 10: {e}")
        return False


def _install_nuget_cert(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> bool:
    """
    Import the DigiCert Trusted Root G4 CA into the Wine prefix Windows cert
    store. Required for NuGet package signature validation when Synthesis
    compiles patchers. Uses wine certutil so no system-level changes are needed.
    """
    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cert_file = cache_dir / _DIGICERT_CERT_FILENAME

        if not cert_file.exists():
            log(f"Downloading DigiCert Trusted Root G4 certificate...")
            urllib.request.urlretrieve(_DIGICERT_CERT_URL, cert_file)
            log("Certificate downloaded")
        else:
            log("DigiCert certificate already cached, skipping download")

        log("Importing certificate into Wine prefix cert store...")
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        env["WINEDEBUG"] = "-all"
        env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
        env["DISPLAY"] = env.get("DISPLAY", ":0")

        result = subprocess.run(
            [wine_bin, "certutil", "-addstore", "Root", str(cert_file)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            log(f"certutil exited with code {result.returncode} (may already be installed)")
        else:
            log("DigiCert certificate imported into Wine cert store")
        return True

    except Exception as e:
        log(f"Failed to install NuGet certificate: {e}")
        return False



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
        from pathlib import Path as _Path
        module_dir = _Path(__file__).parent.parent.parent
        winetricks_bin = str(module_dir / "tools" / "winetricks")
        if not os.path.exists(winetricks_bin):
            appdir = os.environ.get("APPDIR", "")
            if appdir:
                winetricks_bin = os.path.join(appdir, "opt", "jackify", "tools", "winetricks")
        if not os.path.exists(winetricks_bin):
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
    install_dotnet9_sdk: bool = False,
    install_fxc2_d3dcompiler: bool = False,
    preserve_global_mscoree: bool = False,
) -> bool:
    """
    Apply tool compatibility settings to the Wine prefix.

    install_dotnet9_sdk=True downloads and installs the .NET 9/10 SDK and flips the
    prefix to Windows 11, which are required for Synthesis. Intentionally opt-in -
    the download is ~220MB and the win11 flip has not been verified against NSF/CSF
    prefixes (see preserve_global_mscoree).
    The NuGet Root CA cert (also required for Synthesis) is applied regardless of
    this flag, since it has no interaction with mscoree hosting or Windows version.

    install_fxc2_d3dcompiler=True replaces d3dcompiler_47.dll with the Mozilla
    fxc2 build. Only appropriate for Skyrim SE/AE modlists using Community Shaders.

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

    if install_dotnet9_sdk:
        _install_dotnet9_sdk(prefix_path, wine_bin, _log)
        _install_dotnet10_desktop_runtime(prefix_path, wine_bin, _log)
        _set_windows_version_win11(prefix_path, wine_bin, _log)

    # NuGet cert import is independent of the SDK/win11 install above - it only adds a
    # Root CA entry and has no interaction with mscoree hosting, so it must not be
    # skipped for NSF/CSF modlists (which pass install_dotnet9_sdk=False to avoid the
    # win11 flip). Synthesis still needs this cert even on an NSF/CSF prefix.
    _install_nuget_cert(prefix_path, wine_bin, _log)

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

    reg_content = _build_reg_content()

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
            return False

        _log(f"Tool compatibility settings applied ({len(_XEDIT_EXECUTABLES)} xEdit variants, Pandora, {len(_DLL_OVERRIDES)} DLL overrides)")
        return True

    except subprocess.TimeoutExpired:
        _log("wine regedit timed out after 30 seconds")
        return False
    except Exception as e:
        _log(f"Failed to apply tool config: {e}")
        return False
    finally:
        try:
            os.unlink(reg_file)
        except Exception:
            pass


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
    install_dotnet9_sdk: bool = True,
) -> bool:
    """
    Resolve compatdata path and wine binary from an AppID, then apply tool config.
    Convenience wrapper for the standalone Additional Tasks flow.
    """
    def _log(msg: str):
        logger.info(msg)
        if log:
            log(msg)

    try:
        from jackify.backend.handlers.wine_utils_proton import WineUtilsProtonMixin
        compatdata_path, _, wine_bin = WineUtilsProtonMixin.get_proton_paths(appid)
    except Exception as e:
        _log(f"Could not resolve Proton paths for AppID {appid}: {e}")
        return False

    if not compatdata_path or not wine_bin:
        _log(f"Could not resolve Wine prefix for AppID {appid}. Is this modlist configured in Steam?")
        return False

    return apply_tool_config(compatdata_path, wine_bin, log, install_dotnet9_sdk=install_dotnet9_sdk, install_fxc2_d3dcompiler=True)
