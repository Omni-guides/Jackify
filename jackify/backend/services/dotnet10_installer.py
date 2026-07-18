"""
.NET 10 SDK and Desktop Runtime installation for Synthesis patcher compilation.

Split out of tool_config_service.py to keep that file under the project's
line-count guardrail.
"""

import logging
import os
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# .NET 10 SDK - ZIP distribution, extracted directly to avoid running an EXE under Wine.
# Synthesis requires the SDK (not just runtime) for patcher compilation. A newer SDK can
# still build projects targeting older TFMs (net6/7/8/9) as long as the matching runtime is
# present - which the native/winetricks component pipeline already installs separately - but
# an older SDK cannot target a newer TFM it doesn't recognize. Some Synthesis patchers target
# net10.0, so the SDK itself must be 10, matching Fluorine's confirmed-working configuration.
# ZIP distribution: Microsoft's officially supported xcopy-deployable install method, no
# installer-side effects the CLI depends on. Confirmed sufficient for net10.0 patcher builds
# by Styyx (2026-07-14).
_DOTNET_SDK_URL = "https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.301/dotnet-sdk-10.0.301-win-x64.zip"
_DOTNET_SDK_FILENAME = "dotnet-sdk-10.0.301-win-x64.zip"

# .NET Desktop Runtime 10 - provides NETCore.App + WindowsDesktop.App 10.0.2.
# Covers Synthesis patchers targeting .NET 10 runtime. ZIP distribution, same rationale
# as the SDK above - avoids running an EXE installer under Wine.
_DOTNET10_DESKTOP_URL = "https://builds.dotnet.microsoft.com/dotnet/WindowsDesktop/10.0.2/windowsdesktop-runtime-10.0.2-win-x64.zip"
_DOTNET10_DESKTOP_FILENAME = "windowsdesktop-runtime-10.0.2-win-x64.zip"


def install_dotnet_sdk(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> bool:
    """
    Download and extract the .NET 10 SDK ZIP into the Wine prefix.
    Uses the standalone ZIP distribution to avoid running an EXE under Wine.
    Synthesis requires the full SDK (Roslyn compiler) for patcher compilation.
    """
    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        sdk_zip = cache_dir / _DOTNET_SDK_FILENAME

        if not sdk_zip.exists():
            log(f"Downloading .NET 10 SDK ({_DOTNET_SDK_FILENAME})...")
            urllib.request.urlretrieve(_DOTNET_SDK_URL, sdk_zip)
            log(".NET 10 SDK downloaded")
        else:
            log(".NET 10 SDK already cached, skipping download")

        dest = prefix_path / "drive_c" / "Program Files" / "dotnet"
        dest.mkdir(parents=True, exist_ok=True)
        log("Extracting .NET 10 SDK...")
        with zipfile.ZipFile(sdk_zip) as zf:
            zf.extractall(dest)
        log(".NET 10 SDK extracted successfully")
        return True

    except Exception as e:
        log(f"Failed to install .NET 10 SDK: {e}")
        return False


def find_winetricks_bin() -> Optional[str]:
    """Locate the bundled winetricks binary, checking APPDIR for the AppImage case."""
    module_dir = Path(__file__).parent.parent.parent
    winetricks_bin = str(module_dir / "tools" / "winetricks")
    if not os.path.exists(winetricks_bin):
        appdir = os.environ.get("APPDIR", "")
        if appdir:
            winetricks_bin = os.path.join(appdir, "opt", "jackify", "tools", "winetricks")
    return winetricks_bin if os.path.exists(winetricks_bin) else None


def install_dotnet10_desktop_runtime(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> bool:
    """
    Download and extract the .NET Desktop Runtime 10 ZIP into the Wine prefix.
    Provides NETCore.App and WindowsDesktop.App 10.x for patchers targeting .NET 10.
    Falls back to the bundled winetricks dotnetdesktop10 verb if the ZIP install fails.
    """
    try:
        from jackify.shared.paths import get_jackify_data_dir
        cache_dir = get_jackify_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        runtime_zip = cache_dir / _DOTNET10_DESKTOP_FILENAME

        if not runtime_zip.exists():
            log(f"Downloading .NET Desktop Runtime 10 ({_DOTNET10_DESKTOP_FILENAME})...")
            urllib.request.urlretrieve(_DOTNET10_DESKTOP_URL, runtime_zip)
            log(".NET Desktop Runtime 10 downloaded")
        else:
            log(".NET Desktop Runtime 10 already cached, skipping download")

        dest = prefix_path / "drive_c" / "Program Files" / "dotnet"
        dest.mkdir(parents=True, exist_ok=True)
        log("Extracting .NET Desktop Runtime 10...")
        with zipfile.ZipFile(runtime_zip) as zf:
            zf.extractall(dest)
        log(".NET Desktop Runtime 10 extracted successfully")
        return True

    except Exception as e:
        log(f"Failed to install .NET Desktop Runtime 10 via ZIP: {e}")
        return _install_dotnet10_desktop_runtime_winetricks(prefix_path, wine_bin, log)


def _install_dotnet10_desktop_runtime_winetricks(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
) -> bool:
    """Fallback: install the .NET Desktop Runtime 10 via the bundled winetricks verb."""
    winetricks_bin = find_winetricks_bin()
    if not winetricks_bin:
        log("Bundled winetricks not found - cannot fall back for .NET Desktop Runtime 10")
        return False

    try:
        log("Falling back to winetricks dotnetdesktop10...")
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_path)
        env["WINE"] = wine_bin
        env["WINEDEBUG"] = "-all"
        env["DISPLAY"] = env.get("DISPLAY", ":0")

        result = subprocess.run(
            [winetricks_bin, "-q", "dotnetdesktop10"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            log(f"winetricks dotnetdesktop10 exited with code {result.returncode}")
            return False

        log(".NET Desktop Runtime 10 installed via winetricks fallback")
        return True

    except subprocess.TimeoutExpired:
        log("winetricks dotnetdesktop10 timed out")
        return False
    except Exception as e:
        log(f"winetricks dotnetdesktop10 fallback failed: {e}")
        return False
