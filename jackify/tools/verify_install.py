#!/usr/bin/env python3
"""
Jackify Install Verifier: standalone diagnostic tool.

Run with no arguments to auto-discover installed modlists from Steam shortcuts.
Or point directly at a prefix and modlist directory.

Usage:
    python3 verify_install.py                                  # interactive selection
    python3 verify_install.py <prefix_path> <modlist_dir>      # direct
    python3 verify_install.py <prefix_path> <modlist_dir> -g falloutnv

No external dependencies required. vdf is bundled in tools/vdf/.
"""

import argparse
import base64
import configparser
import hashlib
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
try:
    import vdf
    HAS_VDF = True
except ImportError:
    HAS_VDF = False


def _vdf_extract_library_paths(content: str) -> list:
    """Extract 'path' values from text-format libraryfolders.vdf."""
    return re.findall(r'"path"\s+"([^"]+)"', content)


def _vdf_extract_compat_tool(content: str, appid: str) -> Optional[str]:
    """Extract the CompatToolMapping name for a given AppID from text config.vdf."""
    pattern = (
        r'"CompatToolMapping"\s*\{.*?"' + re.escape(appid) + r'"\s*\{.*?"name"\s+"([^"]+)"'
    )
    m = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def _vdf_parse_binary_shortcuts(data: bytes) -> dict:
    """Minimal binary VDF parser sufficient for shortcuts.vdf."""
    pos = [0]

    def read_str():
        end = data.index(b'\x00', pos[0])
        s = data[pos[0]:end].decode('utf-8', errors='replace')
        pos[0] = end + 1
        return s

    def read_i32():
        v = struct.unpack_from('<i', data, pos[0])[0]
        pos[0] += 4
        return v

    def read_map():
        result = {}
        while pos[0] < len(data):
            t = data[pos[0]]
            pos[0] += 1
            if t == 0x08:
                break
            key = read_str()
            if t == 0x00:
                result[key] = read_map()
            elif t == 0x01:
                result[key] = read_str()
            elif t == 0x02:
                result[key] = read_i32()
            elif t == 0x03:
                pos[0] += 4   # float32 - skip
            elif t == 0x07:
                pos[0] += 8   # int64 - skip
        return result

    try:
        if not data or data[0] != 0x00:
            return {}
        pos[0] = 1
        root_key = read_str()
        return {root_key: read_map()}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Game type definitions
# ---------------------------------------------------------------------------

GAME_KEYWORDS = {
    "oblivion_remastered": ["oblivion remastered", "oblivionremastered"],
    "skyrimvr": ["skyrim vr", "skyrimvr"],
    "fallout4vr": ["fallout 4 vr", "fallout4vr", "fo4vr"],
    "cp2077": ["cyberpunk", "cp2077", "cyberpunk 2077"],
    "bg3": ["baldur's gate 3", "baldursgate3", "bg3"],
    "skyrim": ["skyrim", "sse", "skse", "dragonborn"],
    "fallout4": ["fallout 4", "fo4", "f4se", "commonwealth"],
    "falloutnv": ["fallout new vegas", "fonv", "fnv", "new vegas", "nvse", "ttw", "tale of two wastelands"],
    "fallout3": ["fallout 3", "fo3", "fallout3", "fose"],
    "oblivion": ["oblivion", "obse", "shivering isles"],
    "enderal": ["enderal"],
    "starfield": ["starfield"],
}

# My Games directory name per game type
MY_GAMES_DIR = {
    "skyrim": "Skyrim Special Edition",
    "skyrimvr": "Skyrim VR",
    "fallout4": "Fallout4",
    "fallout4vr": "Fallout4VR",
    "falloutnv": "FalloutNV",
    "fallout3": "Fallout3",
    "oblivion": "Oblivion",
    "oblivion_remastered": "Oblivion Remastered",
    "enderal": "Enderal Special Edition",
    "starfield": "Starfield",
}

# AppData/Local directory names (USVFS anchors or vendor paths)
APPDATA_LOCAL_DIRS = {
    "skyrim": ["Skyrim Special Edition"],
    "fallout4": ["Fallout4"],
    "cp2077": ["CD Projekt Red/Cyberpunk 2077"],
    "bg3": ["Larian Studios/Baldur's Gate 3"],
}

# Registry injection targets: game_type -> (reg section, key name, reg file)
# reg file is "user" (user.reg / HKCU) or "system" (system.reg / HKLM)
GAME_REGISTRY = {
    "falloutnv": (r"Software\\Wow6432Node\\bethesda softworks\\falloutnv", "Installed Path", "system"),
    "fallout3": (r"Software\\Wow6432Node\\bethesda softworks\\fallout3", "Installed Path", "system"),
    "enderal": (r"Software\\Wow6432Node\\SureAI\\Enderal SE", "installed path", "system"),
    "cp2077": (r"Software\\CD Projekt Red\\Cyberpunk 2077", "InstallFolder", "system"),
    # bg3 deliberately excluded: this check (and the matching games_config entry in
    # automated_prefix_registry.py) was added in an "Untested checkpoint" commit,
    # copy-pasted from the FNV/FO3/Enderal pattern with no confirmed BG3-specific need -
    # unlike those games' xSE loaders, nothing in BG3's modding stack is known to read this
    # registry key. Re-add only once that's actually confirmed.
}

# winetricks components Jackify installs per game type (modlist_wine_ops.py)
_WT_DEFAULT = ["fontsmooth=rgb", "xact", "xact_x64", "vcrun2022"]
_WT_MODERN = _WT_DEFAULT + ["d3dcompiler_47", "d3dx11_43", "d3dcompiler_43", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6"]
_WT_LEGACY = _WT_DEFAULT + ["d3dx9_43", "d3dx9"]

GAME_WINETRICKS = {
    "skyrim": _WT_MODERN, "skyrimvr": _WT_MODERN, "fallout4": _WT_MODERN,
    "fallout4vr": _WT_MODERN, "starfield": _WT_MODERN, "oblivion_remastered": _WT_MODERN,
    "enderal": _WT_MODERN, "cp2077": _WT_MODERN, "bg3": _WT_MODERN,
    "falloutnv": _WT_LEGACY, "fallout3": _WT_LEGACY, "oblivion": _WT_LEGACY,
}

# Seeded files: game_type -> list of (relative_path, description, optional_content_check)
SEEDED_FILES = {
    "skyrim": [
        ("users/steamuser/AppData/Local/Skyrim Special Edition/Plugins.txt",
         "USVFS anchor (empty file)", None),
        ("users/steamuser/Documents/My Games/Skyrim Special Edition/SkyrimPrefs.ini",
         "CC popup suppression stub", "bDownloadCC"),
    ],
    "fallout4": [
        ("users/steamuser/AppData/Local/Fallout4/Plugins.txt",
         "USVFS anchor (empty file)", None),
    ],
    "skyrimvr": [
        ("users/steamuser/AppData/Local/Skyrim VR/Plugins.txt",
         "USVFS anchor (empty file)", None),
        ("users/steamuser/Documents/My Games/Skyrim VR/SkyrimPrefs.ini",
         "VR first-launch stub", "bLoadVRPlayroom"),
    ],
    "fallout4vr": [
        ("users/steamuser/AppData/Local/Fallout4VR/Plugins.txt",
         "USVFS anchor (empty file)", None),
    ],
}


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

class Results:
    def __init__(self):
        self.passes = []
        self.warnings = []
        self.failures = []
        # List of {"name": str, "method": "native"|"winetricks"|"unknown"} dicts
        self.installed_components = []

    def ok(self, msg):
        self.passes.append(msg)
        print(f"  [PASS] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  [WARN] {msg}")

    def fail(self, msg):
        self.failures.append(msg)
        print(f"  [FAIL] {msg}")

    def summary(self):
        total = len(self.passes) + len(self.warnings) + len(self.failures)
        print(f"\n{'='*60}")
        print(f"Results: {len(self.passes)} passed, {len(self.warnings)} warnings, {len(self.failures)} failures (of {total} checks)")
        if self.failures:
            print(f"\nFailures:")
            for f in self.failures:
                print(f"  - {f}")
        if self.warnings:
            print(f"\nWarnings:")
            for w in self.warnings:
                print(f"  - {w}")
        return len(self.failures) == 0


# ---------------------------------------------------------------------------
# Steam discovery
# ---------------------------------------------------------------------------

STEAM_ROOTS = [
    Path.home() / ".steam" / "steam",
    Path.home() / ".local" / "share" / "Steam",
    Path.home() / ".steam" / "root",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
    Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
]


def _find_steam_roots() -> List[Path]:
    seen = set()
    results = []
    for r in STEAM_ROOTS:
        if not r.is_dir():
            continue
        resolved = r.resolve()
        if resolved not in seen:
            seen.add(resolved)
            results.append(r)
    return results


def _find_steam_library_paths() -> List[Path]:
    """Parse libraryfolders.vdf from all known Steam roots."""
    libraries = set()
    for root in _find_steam_roots():
        libraries.add(root)
        vdf_path = root / "config" / "libraryfolders.vdf"
        if not vdf_path.is_file():
            continue
        try:
            content = vdf_path.read_text(encoding="utf-8", errors="replace")
            if HAS_VDF:
                data = vdf.loads(content)
                for _, lib_data in data.get("libraryfolders", {}).items():
                    if isinstance(lib_data, dict) and "path" in lib_data:
                        p = Path(lib_data["path"])
                        if p.is_dir():
                            libraries.add(p)
            else:
                for path_str in _vdf_extract_library_paths(content):
                    p = Path(path_str)
                    if p.is_dir():
                        libraries.add(p)
        except Exception:
            pass
    return list(libraries)


def _find_compat_data(appid: str) -> Optional[Path]:
    """Resolve a Steam AppID to its compatdata directory."""
    for lib in _find_steam_library_paths():
        p = lib / "steamapps" / "compatdata" / appid
        if p.is_dir():
            return p
    return None


def _find_shortcuts_vdf_paths() -> List[Path]:
    """Find all shortcuts.vdf files across Steam userdata directories."""
    paths = []
    for root in _find_steam_roots():
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for user_dir in userdata.iterdir():
            if not user_dir.is_dir():
                continue
            s = user_dir / "config" / "shortcuts.vdf"
            if s.is_file():
                paths.append(s)
    return paths


def _parse_shortcuts_vdf(path: Path) -> List[Dict]:
    """Return list of shortcut dicts from a binary shortcuts.vdf."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
        if HAS_VDF:
            import io
            data = vdf.binary_load(io.BytesIO(raw))
        else:
            data = _vdf_parse_binary_shortcuts(raw)
        return list(data.get("shortcuts", {}).values())
    except Exception:
        return []


def _signed_to_unsigned(appid: int) -> int:
    if appid < 0:
        return appid + (2 ** 32)
    return appid


def discover_installed_modlists() -> List[Dict]:
    """
    Scan Steam shortcuts.vdf for non-Steam shortcuts pointing at ModOrganizer.exe.
    Returns list of dicts: {name, appid (str), modlist_dir, pfx, game_type}
    """
    results = []
    seen_appids = set()

    for vdf_path in _find_shortcuts_vdf_paths():
        for shortcut in _parse_shortcuts_vdf(vdf_path):
            exe = shortcut.get("Exe", shortcut.get("exe", "")).strip('"')
            if "ModOrganizer.exe" not in os.path.basename(exe):
                continue

            name = shortcut.get("AppName", shortcut.get("appname", "Unknown"))
            start_dir = shortcut.get("StartDir", shortcut.get("startdir", "")).strip('"')
            raw_appid = shortcut.get("appid", shortcut.get("AppID", shortcut.get("appId")))

            if raw_appid is None or not start_dir:
                continue

            unsigned_appid = str(_signed_to_unsigned(int(raw_appid)))
            if unsigned_appid in seen_appids:
                continue
            seen_appids.add(unsigned_appid)

            modlist_dir = Path(start_dir)
            # MO2 is sometimes in a files/ subdir
            if not (modlist_dir / "ModOrganizer.ini").exists():
                alt = modlist_dir / "files"
                if (alt / "ModOrganizer.ini").exists():
                    modlist_dir = alt

            compat_data = _find_compat_data(unsigned_appid)
            pfx = (compat_data / "pfx") if compat_data else None

            game_type = detect_game_type(modlist_dir) if modlist_dir.is_dir() else "unknown"

            results.append({
                "name": name,
                "appid": unsigned_appid,
                "modlist_dir": modlist_dir,
                "pfx": pfx,
                "game_type": game_type,
            })

    return results


def select_modlist_interactive() -> Optional[Dict]:
    """Prompt user to pick from discovered modlists. Returns selected entry or None."""
    print("Scanning Steam shortcuts for installed modlists...")
    modlists = discover_installed_modlists()

    if not modlists:
        print("No modlists found. Ensure Steam shortcuts exist for ModOrganizer.exe.")
        return None

    print(f"\nFound {len(modlists)} modlist(s):\n")
    for i, m in enumerate(modlists, 1):
        pfx_status = "pfx found" if (m["pfx"] and m["pfx"].is_dir()) else "pfx NOT found"
        print(f"  {i}. {m['name']}")
        print(f"     Game:    {m['game_type']}")
        print(f"     Dir:     {m['modlist_dir']}")
        print(f"     AppID:   {m['appid']}  ({pfx_status})")
        print()

    while True:
        try:
            choice = input(f"Select modlist [1-{len(modlists)}] or q to quit: ").strip()
            if choice.lower() == "q":
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(modlists):
                return modlists[idx]
        except (ValueError, EOFError):
            pass
        print(f"Enter a number between 1 and {len(modlists)}.")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_game_type(modlist_dir: Path) -> str:
    """Detect game type from the gameName key in ModOrganizer.ini [General]."""
    mo_ini = modlist_dir / "ModOrganizer.ini"
    if not mo_ini.exists():
        mo_ini = modlist_dir / "files" / "ModOrganizer.ini"

    if mo_ini.exists():
        try:
            for line in mo_ini.read_text(errors="replace").splitlines():
                stripped = line.strip().lower()
                if stripped.startswith("gamename"):
                    parts = stripped.split("=", 1)
                    if len(parts) != 2:
                        continue
                    game_name = parts[1].strip()
                    for game_type, keywords in GAME_KEYWORDS.items():
                        for kw in keywords:
                            if kw in game_name:
                                return game_type
        except Exception:
            pass

    # Fallback: match against the directory name only
    dir_name = modlist_dir.name.lower()
    for game_type, keywords in GAME_KEYWORDS.items():
        for kw in keywords:
            if kw in dir_name:
                return game_type

    return "unknown"


def _pe_machine_type(path: Path) -> Optional[str]:
    """Return 'x86'/'x64' from a PE file's COFF header machine field, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            data = f.read(0x40)
            if len(data) < 0x40 or data[0:2] != b"MZ":
                return None
            pe_offset = int.from_bytes(data[0x3C:0x40], "little")
            f.seek(pe_offset)
            pe_header = f.read(6)
        if pe_header[0:4] != b"PE\x00\x00":
            return None
        machine = int.from_bytes(pe_header[4:6], "little")
        return {0x014C: "x86", 0x8664: "x64"}.get(machine)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_prefix_structure(pfx: Path, r: Results):
    """Verify basic prefix directory structure."""
    print("\n--- Prefix Structure ---")
    drive_c = pfx / "drive_c"
    if drive_c.is_dir():
        r.ok("drive_c exists")
    else:
        r.fail("drive_c missing")
        return

    for subdir in ["windows/system32", "windows/syswow64", "users/steamuser"]:
        p = drive_c / subdir
        if p.is_dir():
            r.ok(f"{subdir} exists")
        else:
            r.fail(f"{subdir} missing")


def check_registry_base(pfx: Path, r: Results):
    """Check universal registry entries."""
    print("\n--- Base Registry Entries ---")
    user_reg = pfx / "user.reg"
    system_reg = pfx / "system.reg"

    if not user_reg.exists():
        r.fail("user.reg missing")
        return
    r.ok("user.reg exists")

    if not system_reg.exists():
        r.fail("system.reg missing")
        return
    r.ok("system.reg exists")

    user_content = user_reg.read_text(errors="replace")
    system_content = system_reg.read_text(errors="replace")

    # FontSmoothingType
    if "FontSmoothingType" in user_content:
        r.ok("FontSmoothingType set")
    else:
        r.warn("FontSmoothingType not found")

    # ShowDotFiles
    if "ShowDotFiles" in user_content:
        r.ok("ShowDotFiles set")
    else:
        r.warn("ShowDotFiles not found")



def check_game_registry(pfx: Path, game_type: str, r: Results):
    """Check game-specific registry entries."""
    if game_type not in GAME_REGISTRY:
        return

    print(f"\n--- Game Registry ({game_type}) ---")
    section_pattern, key_name, reg_file = GAME_REGISTRY[game_type]
    reg_path = pfx / ("system.reg" if reg_file == "system" else "user.reg")
    if not reg_path.exists():
        r.fail(f"{reg_path.name} missing, cannot check game registry")
        return

    content = reg_path.read_text(errors="replace")
    section_search = section_pattern.lower().replace("\\\\", "\\")
    content_lower = content.lower().replace("\\\\", "\\")

    if section_search in content_lower:
        r.ok(f"Game registry section found: {section_pattern}")
        if key_name.lower() in content_lower:
            r.ok(f"Registry key '{key_name}' present")
        else:
            r.fail(f"Registry key '{key_name}' not found in game section")
    else:
        r.fail(f"Game registry section missing: {section_pattern}")


def check_user_directories(pfx: Path, game_type: str, r: Results):
    """Check My Games and AppData directories."""
    print(f"\n--- User Directories ({game_type}) ---")
    drive_c = pfx / "drive_c"

    # My Games
    if game_type in MY_GAMES_DIR:
        my_games = drive_c / "users/steamuser/Documents/My Games" / MY_GAMES_DIR[game_type]
        if my_games.is_dir():
            r.ok(f"My Games/{MY_GAMES_DIR[game_type]} exists")
        else:
            r.warn(f"My Games/{MY_GAMES_DIR[game_type]} missing")

    # AppData/Local
    if game_type in APPDATA_LOCAL_DIRS:
        for subdir in APPDATA_LOCAL_DIRS[game_type]:
            appdata = drive_c / "users/steamuser/AppData/Local" / subdir
            if appdata.is_dir():
                r.ok(f"AppData/Local/{subdir} exists")
            else:
                r.fail(f"AppData/Local/{subdir} missing")


def check_seeded_files(pfx: Path, game_type: str, r: Results):
    """Check first-launch seeded files."""
    if game_type not in SEEDED_FILES:
        return

    print(f"\n--- First-Launch Seeded Files ({game_type}) ---")
    drive_c = pfx / "drive_c"

    for rel_path, description, content_check in SEEDED_FILES[game_type]:
        full_path = drive_c / rel_path
        if full_path.exists():
            r.ok(f"{description}: {rel_path}")
            if content_check:
                content = full_path.read_text(errors="replace")
                if content_check in content:
                    r.ok(f"  contains expected '{content_check}'")
                else:
                    r.warn(f"  missing expected content '{content_check}'")
        else:
            r.fail(f"{description} missing: {rel_path}")


def _find_protontricks() -> Optional[str]:
    for candidate in ["protontricks", "flatpak run com.github.Matoking.protontricks"]:
        try:
            result = subprocess.run(
                candidate.split() + ["--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return candidate
        except Exception:
            pass
    return None


def check_winetricks_components(pfx: Path, appid: str, game_type: str, r: Results):
    """Verify winetricks components.

    Primary: reads pfx/winetricks.log (winetricks writes this itself during install, fast).
    Fallback: protontricks list-installed (slow Flatpak cold-start, 120s timeout).
    """
    print(f"\n--- Winetricks Components ({game_type}) ---")
    expected = GAME_WINETRICKS.get(game_type, _WT_DEFAULT)

    installed_output = ""
    source = ""

    # Fast path: winetricks.log is written by protontricks/winetricks after each install
    log_path = pfx / "winetricks.log"
    if log_path.exists():
        try:
            installed_output = log_path.read_text(errors="replace").lower()
            source = "winetricks.log"
        except Exception as e:
            r.warn(f"Could not read winetricks.log: {e}")

    # Slow fallback: protontricks list-installed
    if not installed_output:
        pt = _find_protontricks()
        if not pt:
            r.warn("winetricks.log missing and protontricks not found -- cannot verify components")
            return
        try:
            result = subprocess.run(
                pt.split() + ["--no-bwrap", appid, "list-installed"],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                r.warn(f"protontricks list-installed failed (rc={result.returncode}): {result.stderr.strip()[:120]}")
                return
            installed_output = result.stdout.lower()
            source = "protontricks list-installed"
        except Exception as e:
            r.warn(f"protontricks list-installed error: {e}")
            return

    missing = []
    for component in expected:
        base = component.split("=")[0].lower()
        if base in installed_output or component.lower() in installed_output:
            r.ok(f"{component}")
        else:
            missing.append(component)
            r.fail(f"{component} not found (source: {source})")

    if not missing:
        r.ok(f"All {len(expected)} expected components verified ({source})")

    # Report notable extras installed beyond the baseline (e.g. dotnet48 added for .NET Script Framework)
    _extras = ["dotnet48", "dotnet9", "dotnet10", "dotnetdesktop9", "dotnetdesktop10"]
    for extra in _extras:
        if extra not in expected and extra in installed_output:
            r.ok(f"{extra} (extra, installed for this modlist)")

    # Build the installed_components inventory for GUI display.
    # Read jackify_components.json for native-installed components (has method + timestamp).
    native_record = {}
    jc_path = pfx / "jackify_components.json"
    if jc_path.exists():
        try:
            import json as _json
            native_record = _json.loads(jc_path.read_text(errors="replace"))
        except Exception:
            pass

    # Parse winetricks.log (one component per line) for winetricks-installed components.
    wt_components = set()
    if source == "winetricks.log":
        for line in installed_output.splitlines():
            name = line.strip()
            if name:
                wt_components.add(name)

    # Merge: native_record takes precedence (has richer metadata).
    seen = set()
    for name, meta in native_record.items():
        seen.add(name.lower())
        r.installed_components.append({"name": name, "method": meta.get("method", "native")})
    for name in sorted(wt_components):
        if name not in seen:
            seen.add(name)
            r.installed_components.append({"name": name, "method": "winetricks"})


_LEGACY_GAME_TYPES = {"falloutnv", "fallout3", "oblivion"}


def _is_nsf_prefix(pfx: Path) -> bool:
    """Return True if this prefix has global mscoree=native in Wine DllOverrides.

    All Skyrim prefixes get a per-exe AppDefaults\\SkyrimSE.exe mscoree override -
    that does not qualify. NSF/CSF prefixes additionally have it in the global
    DllOverrides section, which is what this checks.
    """
    import re
    user_reg = pfx / 'user.reg'
    if not user_reg.is_file():
        return False
    try:
        c = user_reg.read_text(errors='replace').lower()
        return bool(re.search(
            r'\[hkey_current_user\\software\\wine\\dlloverrides\][^\[]*"?\*mscoree"?\s*=\s*"native"',
            c, re.DOTALL
        ))
    except Exception:
        return False


def check_native_dotnet(pfx: Path, r: Results, game_type: str = ""):
    """Check native dotnet40/48 installation - only meaningful for NSF/CSF prefixes.

    Non-NSF prefixes always have phantom NDP keys written by Wine Mono; checking
    them produces false positives. Skip entirely unless global mscoree=native is set.
    """
    if game_type in _LEGACY_GAME_TYPES:
        return
    if not _is_nsf_prefix(pfx):
        return

    marker40 = pfx / 'drive_c' / 'windows' / 'dotnet40.installed.workaround'
    sys_reg = pfx / 'system.reg'
    ndp40_ok = False
    if sys_reg.is_file():
        try:
            c = sys_reg.read_text(errors='replace').lower()
            ndp40_ok = 'net framework setup\\\\ndp\\\\v4\\\\full' in c and '"install"=dword:00000001' in c
        except Exception:
            pass
    if marker40.is_file() or ndp40_ok:
        source = "marker+NDP" if (marker40.is_file() and ndp40_ok) else ("marker" if marker40.is_file() else "NDP registry")
        r.ok(f"dotnet40 (NDP seeded, verified via {source})")
    else:
        r.fail("dotnet40 not detected: workaround marker and NDP registry keys both absent")

    marker = pfx / 'drive_c' / 'windows' / 'dotnet48.installed.workaround'
    ndp_ok = False
    if sys_reg.is_file():
        try:
            c = sys_reg.read_text(errors='replace').lower()
            ndp_ok = 'net framework setup\\\\ndp\\\\v4\\\\full' in c and '"release"' in c
        except Exception:
            pass
    if marker.is_file() or ndp_ok:
        source = "marker+NDP" if (marker.is_file() and ndp_ok) else ("marker" if marker.is_file() else "NDP registry")
        r.ok(f"dotnet48 (native, verified via {source})")
    else:
        r.warn("dotnet48 not detected (expected if modlist uses dotnet40-only stack)")


def check_game_symlink(pfx: Path, modlist_dir: Path, game_type: str, r: Results):
    """Check the game symlink directory inside the Wine prefix."""
    print(f"\n--- Game Symlink ---")
    common_dir = pfx / "drive_c/Program Files (x86)/Steam/steamapps/common"
    if not common_dir.exists():
        r.warn("Game symlink directory not found in Wine prefix (may be normal for some game types)")
        return

    links = [p for p in common_dir.iterdir() if p.is_symlink() or p.is_dir()]
    if not links:
        r.warn("No game directories found in fake Steam common path")
        return

    r.ok(f"Game symlinks present: {len(links)} entr{'y' if len(links) == 1 else 'ies'}")


def check_modlist_dir(modlist_dir: Path, r: Results):
    """Basic modlist directory checks."""
    print(f"\n--- Modlist Directory ---")
    if not modlist_dir.is_dir():
        r.fail(f"Modlist directory does not exist: {modlist_dir}")
        return

    mo_exe = None
    for candidate in ["ModOrganizer.exe", "modorganizer.exe"]:
        p = modlist_dir / candidate
        if not p.exists():
            p = modlist_dir / "files" / candidate
        if p.exists():
            mo_exe = p
            break

    if mo_exe:
        r.ok(f"ModOrganizer.exe found: {mo_exe.relative_to(modlist_dir)}")
    else:
        r.warn("ModOrganizer.exe not found in modlist directory")

    mo_ini = modlist_dir / "ModOrganizer.ini"
    if not mo_ini.exists():
        mo_ini = modlist_dir / "files" / "ModOrganizer.ini"
    if mo_ini.exists():
        r.ok(f"ModOrganizer.ini found")
    else:
        r.warn("ModOrganizer.ini not found")

    _check_usvfs_patch(modlist_dir, r)


def _check_usvfs_patch(modlist_dir: Path, r: Results):
    """USVFS Linux fix is a performance optimisation. A genuine failure to apply it is a
    WARN; deliberately skipping it (disabled, or this MO2 build can't take it) is expected,
    correct behaviour and must read as OK, not as something the player needs to review."""
    try:
        from jackify.backend.services.usvfs_patch_service import (
            USVFS_DLL_NAME,
            build_unsupported_build_report,
            find_usvfs_dll,
            is_already_patched,
            is_enabled,
            is_supported_game_type,
            is_unsupported_build,
        )
    except Exception as e:
        r.warn(f"Could not check USVFS Linux fix: {e}")
        return

    if not is_supported_game_type(detect_game_type(modlist_dir)):
        r.ok("USVFS Linux fix not applicable for this game type")
        return

    dll = find_usvfs_dll(modlist_dir)
    if dll is None:
        r.warn(f"{USVFS_DLL_NAME} not found in modlist directory")
        return

    if is_already_patched(dll):
        r.ok("USVFS Linux fix applied")
    elif not is_enabled():
        r.ok("USVFS Linux fix not applied (disabled in Settings)")
    elif is_unsupported_build(dll):
        r.warn(build_unsupported_build_report(modlist_dir, dll))
    else:
        r.warn("USVFS Linux fix not applied - MO2 will load more slowly under Wine")


def _resolve_wine_path(gp: str, pfx: Optional[Path] = None) -> Optional[Path]:
    """
    Convert a Wine drive path (Z:\\... or D:\\...) to a real filesystem path.
    Z: always maps to filesystem root.
    D: is resolved via the dosdevices symlink in the prefix when available,
    otherwise falls back to scanning /run/media/ for SD card mounts.
    """
    unix = gp.replace("\\\\", "/").replace("\\", "/")
    drive = unix[:2].lower()
    rest = unix[2:].lstrip("/")

    if drive == "z:":
        return Path("/" + rest)

    if drive == "d:":
        # Prefer reading the dosdevices symlink - it is the definitive mapping
        if pfx:
            dosdev = pfx / "dosdevices" / "d:"
            if dosdev.is_symlink():
                try:
                    sd_root = Path(os.readlink(dosdev))
                    if not sd_root.is_absolute():
                        sd_root = (dosdev.parent / sd_root).resolve()
                    return sd_root / rest
                except Exception:
                    pass

        # Fallback: scan /run/media/ for mounted volumes containing the path
        for media_root in [Path("/run/media/deck"), Path("/run/media")]:
            if not media_root.is_dir():
                continue
            try:
                for mount in media_root.iterdir():
                    if not mount.is_dir():
                        continue
                    candidate = mount / rest
                    if candidate.exists():
                        return candidate
                    # One level deeper (e.g. /run/media/deck/CardName/...)
                    for submount in mount.iterdir():
                        if submount.is_dir():
                            candidate = submount / rest
                            if candidate.exists():
                                return candidate
            except Exception:
                continue

    return None


def check_modorganizer_ini(modlist_dir: Path, r: Results, pfx: Optional[Path] = None):
    """Check ModOrganizer.ini for gamePath set by Jackify during configuration."""
    print("\n--- ModOrganizer.ini ---")
    mo_ini = modlist_dir / "ModOrganizer.ini"
    if not mo_ini.exists():
        mo_ini = modlist_dir / "files" / "ModOrganizer.ini"
    if not mo_ini.exists():
        r.warn("ModOrganizer.ini not found")
        return

    game_path_raw = None
    for line in mo_ini.read_text(errors="replace").splitlines():
        if line.strip().lower().startswith("gamepath"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                game_path_raw = parts[1].strip()
                break

    if not game_path_raw:
        r.fail("gamePath not set in ModOrganizer.ini (configuration may not have run)")
        return

    gp = game_path_raw
    if gp.startswith("@ByteArray(") and gp.endswith(")"):
        gp = gp[len("@ByteArray("):-1]

    p = _resolve_wine_path(gp, pfx)
    if p is None:
        r.warn(f"gamePath uses unrecognised drive letter: {gp}")
        return

    if p.is_dir():
        r.ok(f"gamePath set and exists: {p}")
    else:
        drive = gp[:2].upper()
        if drive == "D:":
            r.fail(f"gamePath set but directory missing (SD card path - card may not be mounted): {p}")
        else:
            r.fail(f"gamePath set but directory missing: {p}")


def check_download_directory(modlist_dir: Path, r: Results, pfx: Optional[Path] = None):
    """Check download_directory in ModOrganizer.ini is a valid Wine path, not a raw Linux path."""
    print("\n--- download_directory ---")
    mo_ini = modlist_dir / "ModOrganizer.ini"
    if not mo_ini.exists():
        mo_ini = modlist_dir / "files" / "ModOrganizer.ini"
    if not mo_ini.exists():
        r.warn("ModOrganizer.ini not found, cannot check download_directory")
        return

    raw_value = None
    for line in mo_ini.read_text(errors="replace").splitlines():
        if line.strip().lower().startswith("download_directory"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                raw_value = parts[1].strip()
                # Take the last occurrence - MO2 reads the last one in duplicate-section installs
    if raw_value is None:
        r.warn("download_directory not set in ModOrganizer.ini")
        return

    # Raw Linux path means Bug 3 fix didn't run or engine wrote an un-normalised value
    if raw_value.startswith("/"):
        r.fail(f"download_directory is a raw Linux path (not normalised to Wine format): {raw_value}")
        return

    drive = raw_value[:2].upper()
    if drive not in ("Z:", "D:"):
        r.fail(f"download_directory has unexpected format: {raw_value}")
        return

    p = _resolve_wine_path(raw_value, pfx)
    if p is None:
        r.warn(f"download_directory drive could not be resolved: {raw_value}")
        return

    if p.is_dir():
        r.ok(f"download_directory set and exists: {p}")
    elif drive == "D:":
        r.fail(f"download_directory missing (SD card path - card may not be mounted): {p}")
    else:
        r.fail(f"download_directory set but directory does not exist: {p}")


def check_proton_version(appid: str, r: Results):
    """Check the Proton compatibility tool set for this AppID in config.vdf."""
    print("\n--- Proton Version ---")
    if not appid:
        r.warn("AppID unknown, cannot check Proton version")
        return
    steam_roots = _find_steam_roots()
    config_vdf = next((root / "config" / "config.vdf" for root in steam_roots if (root / "config" / "config.vdf").exists()), None)
    if not config_vdf:
        r.warn("config.vdf not found")
        return

    try:
        content = config_vdf.read_text(encoding="utf-8", errors="replace")
        if HAS_VDF:
            data = vdf.loads(content)
            ctm = data["InstallConfigStore"]["Software"]["Valve"]["Steam"].get("CompatToolMapping", {})
            entry = ctm.get(appid)
            name = entry.get("name", "") if entry else None
        else:
            name = _vdf_extract_compat_tool(content, appid)
        if name:
            r.ok(f"Proton version: {name}")
        elif name is not None:
            r.warn("Proton entry exists but tool name is empty")
        else:
            r.fail(f"No Proton version set for AppID {appid}")
    except Exception as e:
        r.warn(f"Could not read config.vdf: {e}")


def check_shortcut_launch_options(appid: str, game_type: str, r: Results):
    """Read shortcuts.vdf and verify launch options for this AppID."""
    print("\n--- Launch Options ---")
    if not appid:
        r.warn("Cannot check launch options (AppID unknown)")
        return

    for root in _find_steam_roots():
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for user_dir in userdata.iterdir():
            s = user_dir / "config" / "shortcuts.vdf"
            if not s.is_file():
                continue
            try:
                with open(s, "rb") as f:
                    data = vdf.binary_load(f)
                for _, sc in data.get("shortcuts", {}).items():
                    raw_id = sc.get("appid", sc.get("AppID"))
                    if raw_id is None:
                        continue
                    unsigned = str(int(raw_id) + (2 ** 32) if int(raw_id) < 0 else int(raw_id))
                    if unsigned != appid:
                        continue
                    opts = sc.get("LaunchOptions", sc.get("launchoptions", ""))
                    if opts:
                        r.ok(f"Launch options: {opts}")
                    else:
                        r.warn("Launch options empty")
                    if game_type == "cp2077":
                        if "WINEDLLOVERRIDES" in opts:
                            r.ok("CP2077 WINEDLLOVERRIDES present")
                        else:
                            r.fail("CP2077 missing required WINEDLLOVERRIDES in launch options")
                    return
            except Exception:
                continue

    r.warn(f"AppID {appid} not found in any shortcuts.vdf")


def check_nemesis_compat(modlist_dir: Path, r: Results, game_type: str = None):
    """Check Nemesis symlink and workingDirectory fix were applied."""
    mods_dir = modlist_dir / "mods"
    if not mods_dir.is_dir():
        return

    nemesis_engine_src = next(
        (d / "Nemesis_Engine" for d in mods_dir.iterdir()
         if (d / "Nemesis_Engine").is_dir()),
        None
    )
    if nemesis_engine_src is None:
        return  # modlist has no Nemesis, skip silently

    print("\n--- Nemesis Compatibility ---")

    stock_game_dir = next(
        (modlist_dir / name for name in ("Stock Game", "StockGame", "Game Root", "Stock Folder")
         if (modlist_dir / name).is_dir()),
        None
    )
    if stock_game_dir:
        symlink = stock_game_dir / "Data" / "Nemesis_Engine"
        if symlink.is_symlink():
            target = Path(os.readlink(symlink))
            if not target.is_absolute():
                target = (symlink.parent / target).resolve()
            expected = nemesis_engine_src.resolve()
            if target == expected:
                r.ok(f"Nemesis_Engine symlink correct: {symlink}")
            else:
                r.warn(f"Nemesis_Engine symlink points to wrong target: {target} (expected {expected})")
        elif symlink.exists():
            r.ok(f"Nemesis_Engine present at {symlink} (shipped by modlist, not a symlink)")
        else:
            # Nemesis is known broken on Linux (v0.6) regardless of symlink state.
            # Downgraded to WARN - symlink missing indicates Step 16 bug but has no user-visible impact yet.
            r.warn(f"Nemesis_Engine symlink missing at {symlink} (Nemesis known broken in v0.6 - track as post-release bug)")
    else:
        pass  # no StockGame dir is a valid modlist structure; nothing to check

    mo_ini = modlist_dir / "ModOrganizer.ini"
    if not mo_ini.is_file():
        return
    content = mo_ini.read_text(errors="replace")
    nemesis_indices = re.findall(
        r'^(\d+)\\binary=.*Nemesis Unlimited Behavior Engine\.exe',
        content, re.MULTILINE | re.IGNORECASE
    )
    if nemesis_indices:
        for idx in nemesis_indices:
            wd_match = re.search(rf'^{re.escape(idx)}\\workingDirectory=(.*)$', content, re.MULTILINE)
            if wd_match and wd_match.group(1).strip():
                r.fail(f"Nemesis workingDirectory not blank (entry {idx}): '{wd_match.group(1).strip()}'")
            else:
                r.ok(f"Nemesis workingDirectory blank (entry {idx})")


def check_nxmhandler_ini(modlist_dir: Path, r: Results):
    """Check nxmhandler.ini has noregister=true to suppress MO2 NXM registration popup."""
    print("\n--- NXM Handler ---")
    nxm_ini = modlist_dir / "nxmhandler.ini"
    if not nxm_ini.exists():
        # MO2 creates it on first launch; pre-creation is done by Jackify during configure
        r.warn("nxmhandler.ini not found (Jackify creates it during configure; may not exist before first configure run)")
        return

    content = nxm_ini.read_text(errors="replace")
    if re.search(r'(?im)^\s*noregister\s*=\s*true\s*$', content):
        r.ok("nxmhandler.ini: noregister=true")
    else:
        r.fail("nxmhandler.ini exists but noregister=true not set (NXM popup will appear on MO2 launch)")


def check_ttw_installation(modlist_dir: Path, game_type: str, r: Results, modlist_name: str = ""):
    """For TTW-compatible FNV modlists, check whether TaleOfTwoWastelands.esm is present."""
    if game_type != "falloutnv":
        return

    try:
        from jackify.backend.services.playbook.hook_wiring import modlist_offers_tool_flow
        if not modlist_offers_tool_flow(str(modlist_dir), modlist_name, "ttw_install"):
            return
    except Exception:
        pass

    print("\n--- TTW Installation ---")

    mods_dir = modlist_dir / "mods"
    if mods_dir.is_dir():
        for esm in mods_dir.rglob("TaleOfTwoWastelands.esm"):
            r.ok(f"TTW ESM found: {esm.relative_to(modlist_dir)}")
            return

    r.warn("TTW ESM not found - TTW may not have been installed")


def check_tool_compat_config(pfx: Path, game_type: str, r: Results):
    """Check whether Tool Compatibility Config has been applied to this prefix."""
    # Tool compat is not applied for these game types - nothing to check.
    # Enderal SE shares the Skyrim SE engine/plugin format and gets the same
    # xEdit/Pandora/DLL-overrides/Synthesis fixes (see modlist_configuration.py
    # Step 15) - only the SkyrimSE.exe-scoped mscoree entry is skipped for it,
    # handled below.
    _no_tool_compat = ("falloutnv", "fallout3", "cp2077", "bg3", "skyrimvr", "fallout4vr")
    if game_type in _no_tool_compat:
        return

    print("\n--- Tool Compatibility Config ---")
    user_reg = pfx / "user.reg"
    system_reg = pfx / "system.reg"
    if not user_reg.exists():
        r.warn("user.reg missing, cannot check tool compat config")
        return

    content = user_reg.read_text(errors="replace")

    if "AppDefaults\\\\SSEEdit.exe" in content and "winxp" in content:
        r.ok("xEdit WinXP compatibility applied")
    else:
        r.warn("xEdit WinXP compatibility not found (Tool Compat Config may not have been run)")

    if "Pandora Behaviour Engine" in content:
        r.ok("Pandora window decoration fix applied")
    else:
        r.warn("Pandora fix not found")

    if "dwrite" in content and "native,builtin" in content:
        r.ok("Global DLL overrides applied")
    else:
        r.warn("Global DLL overrides not found")

    if game_type in ("skyrim", "enderal"):
        syswow64_dll = pfx / "drive_c" / "windows" / "syswow64" / "d3dcompiler_47.dll"
        system32_dll = pfx / "drive_c" / "windows" / "system32" / "d3dcompiler_47.dll"
        if syswow64_dll.exists() and system32_dll.exists():
            syswow64_arch = _pe_machine_type(syswow64_dll)
            system32_arch = _pe_machine_type(system32_dll)
            if syswow64_arch == "x86" and system32_arch == "x64":
                r.ok("d3dcompiler_47.dll architecture correct (syswow64=x86, system32=x64)")
            else:
                r.warn(
                    f"d3dcompiler_47.dll architecture mismatch "
                    f"(syswow64={syswow64_arch or 'unknown'}, system32={system32_arch or 'unknown'})"
                )

    # Synthesis/dotnet checks apply to both Skyrim and Enderal SE (same engine and
    # plugin format). The mscoree AppDefaults entry itself is Skyrim-only: it is
    # scoped to SkyrimSE.exe, which is also Enderal's own game process, so
    # Step 15 deliberately skips writing it there - don't flag it missing.
    if game_type in ("skyrim", "enderal"):
        if game_type == "skyrim":
            if "AppDefaults\\\\SkyrimSE.exe\\\\DllOverrides" in content and "mscoree" in content:
                r.ok("Synthesis mscoree fix applied (SkyrimSE.exe AppDefaults)")
            else:
                r.warn("Synthesis mscoree AppDefaults entry not found")

        # OnlyUseLatestCLR is written to HKLM during the same Synthesis compat pass
        sys_content = system_reg.read_text(errors="replace") if system_reg.exists() else ""
        if ".NETFramework" in sys_content and "OnlyUseLatestCLR" in sys_content:
            r.ok("OnlyUseLatestCLR set in HKLM")
        else:
            r.warn("OnlyUseLatestCLR not found in system.reg")

        # .NET 10 SDK is installed natively (not via winetricks) for Synthesis.
        # NSF/CSF prefixes use global *mscoree=native and deliberately skip the SDK install (win11
        # flip breaks NSF), so suppress the check when that override is present. Must check the
        # global [Software\Wine\DllOverrides] section specifically, not just any occurrence of
        # the string - every Skyrim modlist (NSF or not) also gets a scoped
        # AppDefaults\SkyrimSE.exe\DllOverrides entry with the same value, which a plain
        # substring search can't tell apart from the global one.
        _global_overrides_match = re.search(r"\[Software\\\\Wine\\\\DllOverrides\][^\[]*", content)
        _nsf_prefix = bool(_global_overrides_match and '"*mscoree"="native"' in _global_overrides_match.group(0))
        sdk_base = pfx / "drive_c" / "Program Files" / "dotnet" / "sdk"
        if _nsf_prefix:
            r.ok(".NET 10 SDK check skipped (NSF/CSF prefix - global mscoree=native detected)")
        elif sdk_base.is_dir():
            net10_dirs = [d for d in sdk_base.iterdir() if d.is_dir() and d.name.startswith("10.")]
            if net10_dirs:
                r.ok(f".NET 10 SDK present: {net10_dirs[0].name}")
            else:
                installed = [d.name for d in sdk_base.iterdir() if d.is_dir()]
                r.warn(f".NET 10 SDK not found under drive_c/Program Files/dotnet/sdk/ (found: {installed or 'none'})")
        else:
            r.warn(".NET 10 SDK not found (drive_c/Program Files/dotnet/sdk/ missing; run Configure Tool Compatibility)")

        if not _nsf_prefix:
            sys_content = system_reg.read_text(errors="replace") if system_reg.exists() else ""
            _check_nuget_signature_config(pfx, content, sys_content, r)


_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", re.DOTALL
)


def _sdk_trusted_root_thumbprints(pfx: Path) -> Optional[set]:
    """
    Compute the expected set of trusted-root cert thumbprints from the newest
    installed .NET SDK's bundled PEM files - the same source
    nuget_signature_service.install_nuget_cert reads from and imports.
    """
    sdk_root = pfx / "drive_c" / "Program Files" / "dotnet" / "sdk"
    if not sdk_root.is_dir():
        return None

    for version_dir in sorted(sdk_root.iterdir(), reverse=True):
        trustedroots = version_dir / "trustedroots"
        codesign = trustedroots / "codesignctl.pem"
        timestamp = trustedroots / "timestampctl.pem"
        if not (codesign.exists() and timestamp.exists()):
            continue
        thumbprints = set()
        for bundle in (codesign, timestamp):
            text = bundle.read_text(encoding="utf-8", errors="replace")
            for match in _PEM_CERT_RE.finditer(text):
                der = base64.b64decode("".join(match.group(1).split()))
                thumbprints.add(hashlib.sha1(der).hexdigest().upper())
        return thumbprints

    return None


def _check_nuget_signature_config(pfx: Path, user_reg_content: str, system_reg_content: str, r: Results):
    """
    Check NuGet package signature validation is configured for Synthesis.
    Three independent pieces, all required (see nuget_signature_service.py):
    the trust-pin NuGet.Config, the SDK's own trusted-root certs imported into
    Wine's cert store, and the offline-revocation/retry-policy env vars.
    """
    config_path = pfx / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / "NuGet" / "NuGet.Config"
    if not config_path.exists():
        r.warn("NuGet.Config not found (Synthesis package restore will likely fail)")
    else:
        config_content = config_path.read_text(errors="replace")
        if "allowUntrustedRoot" in config_content and "trustedSigners" in config_content:
            r.ok("NuGet signature trust policy configured")
        else:
            r.warn(
                "NuGet.Config exists but lacks the trust policy - likely the SDK's "
                "auto-generated stub (dotnet wrote it before Jackify could); delete "
                "it and re-run Configure Tool Compatibility"
            )

    # X509Store(StoreName.Root, StoreLocation.CurrentUser) lands in user.reg
    # (HKCU) on some Wine versions and system.reg (HKLM) on others - confirmed
    # via a real CachyOS repro (wine-11.0) where the import genuinely succeeded
    # but landed in system.reg while an older Wine build on another machine put
    # it in user.reg. Check both rather than assume one.
    #
    # A raw "any entries present" check is not enough: wine regedit has been
    # observed to exit 0 while silently dropping a single cert out of a ~400
    # entry batch import - the exact root cause of a long-standing Synthesis
    # NU3028 failure. Compare against the SDK's own PEM bundles to catch a
    # partial import, not just an empty one.
    thumb_re = re.compile(r"SystemCertificates\\\\Root\\\\Certificates\\\\([0-9A-Fa-f]+)")
    present = set(thumb_re.findall(user_reg_content)) | set(thumb_re.findall(system_reg_content))
    expected = _sdk_trusted_root_thumbprints(pfx)

    if expected is None:
        if present:
            r.ok(f".NET SDK trusted-root certs imported into Wine cert store ({len(present)} entries)")
        else:
            r.warn(".NET SDK trusted-root certs not found in Wine cert store")
    else:
        missing = expected - present
        if not missing:
            r.ok(f".NET SDK trusted-root certs fully imported into Wine cert store ({len(expected)} entries)")
        else:
            r.warn(
                f".NET SDK trusted-root certs incomplete in Wine cert store - "
                f"{len(missing)} of {len(expected)} missing (Synthesis restore may fail "
                f"with NU3028/NU3037; re-run Configure Tool Compatibility)"
            )

    if "NUGET_CERT_REVOCATION_MODE" in user_reg_content and "NUGET_EXPERIMENTAL_CHAIN_BUILD_RETRY_POLICY" in user_reg_content:
        r.ok("NuGet offline-revocation/retry-policy env vars set")
    else:
        r.warn("NuGet offline-revocation/retry-policy env vars not found in HKCU\\Environment")


def check_steam_artwork(appid: str, r: Results):
    """Check whether Steam grid artwork was applied for this AppID."""
    print("\n--- Steam Artwork ---")
    if not appid:
        r.warn("AppID unknown, cannot check artwork")
        return

    expected = [
        (f"{appid}p.png", "portrait"),
        (f"{appid}.png", "landscape"),
        (f"{appid}_hero.png", "hero"),
        (f"{appid}_logo.png", "logo"),
        (f"{appid}_tenfoot.png", "tenfoot"),
    ]

    found_any = False
    for root in _find_steam_roots():
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for user_dir in userdata.iterdir():
            grid_dir = user_dir / "config" / "grid"
            if not grid_dir.is_dir():
                continue
            present = [label for fn, label in expected if (grid_dir / fn).is_file()]
            if present:
                found_any = True
                r.ok(f"Artwork present ({user_dir.name}): {', '.join(present)}")

    if not found_any:
        r.warn("No Steam grid artwork found for this AppID")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_verification(pfx: Path, modlist_dir: Path, game_type: str, appid: str = "", modlist_name: str = "") -> Results:
    """Callable API for programmatic use. Returns Results; no stdout output."""
    import io
    r = Results()
    _orig = sys.stdout
    sys.stdout = io.StringIO()
    try:
        check_prefix_structure(pfx, r)
        check_registry_base(pfx, r)
        check_game_registry(pfx, game_type, r)
        check_user_directories(pfx, game_type, r)
        check_seeded_files(pfx, game_type, r)
        check_winetricks_components(pfx, appid, game_type, r)
        check_native_dotnet(pfx, r, game_type)
        check_game_symlink(pfx, modlist_dir, game_type, r)
        check_modlist_dir(modlist_dir, r)
        check_modorganizer_ini(modlist_dir, r, pfx=pfx)
        check_download_directory(modlist_dir, r, pfx=pfx)
        check_nxmhandler_ini(modlist_dir, r)
        check_ttw_installation(modlist_dir, game_type, r, modlist_name)
        check_nemesis_compat(modlist_dir, r, game_type)
        check_proton_version(appid, r)
        check_shortcut_launch_options(appid, game_type, r)
        check_steam_artwork(appid, r)
        check_tool_compat_config(pfx, game_type, r)
    finally:
        sys.stdout = _orig
    return r


def _run_verification(pfx: Path, modlist_dir: Path, game_type: str, appid: str = ""):
    print(f"\nJackify Install Verifier")
    print(f"{'='*60}")
    print(f"Prefix:       {pfx}")
    print(f"Modlist dir:  {modlist_dir}")
    print(f"Game type:    {game_type}")
    if appid:
        print(f"AppID:        {appid}")

    if game_type == "unknown":
        print("\nWARNING: Could not detect game type. Use --game-type to specify.")
        print("Continuing with generic checks only.\n")

    r = Results()

    check_prefix_structure(pfx, r)
    check_registry_base(pfx, r)
    check_game_registry(pfx, game_type, r)
    check_user_directories(pfx, game_type, r)
    check_seeded_files(pfx, game_type, r)
    check_winetricks_components(pfx, appid, game_type, r)
    check_native_dotnet(pfx, r)
    check_game_symlink(pfx, modlist_dir, game_type, r)
    check_modlist_dir(modlist_dir, r)
    check_modorganizer_ini(modlist_dir, r, pfx=pfx)
    check_download_directory(modlist_dir, r, pfx=pfx)
    check_nxmhandler_ini(modlist_dir, r)
    check_ttw_installation(modlist_dir, game_type, r)
    check_nemesis_compat(modlist_dir, r, game_type)
    check_proton_version(appid, r)
    check_shortcut_launch_options(appid, game_type, r)
    check_steam_artwork(appid, r)
    check_tool_compat_config(pfx, game_type, r)

    return r.summary()


def main():
    parser = argparse.ArgumentParser(
        description="Verify a Jackify modlist installation is correctly configured.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                     # auto-discover from Steam shortcuts
  %(prog)s /path/to/compatdata/12345/pfx /path/to/modlist
  %(prog)s /path/to/pfx /path/to/modlist -g falloutnv
        """,
    )
    parser.add_argument("prefix", nargs="?", help="Path to the Proton prefix (pfx/ directory). Omit for interactive selection.")
    parser.add_argument("modlist_dir", nargs="?", help="Path to the modlist installation directory.")
    parser.add_argument("--game-type", "-g", help="Override auto-detected game type")
    args = parser.parse_args()

    if args.prefix is None:
        # Interactive mode: discover from Steam shortcuts
        selected = select_modlist_interactive()
        if selected is None:
            sys.exit(1)

        modlist_dir = selected["modlist_dir"]
        pfx = selected["pfx"]
        appid = selected["appid"]
        game_type = args.game_type.lower() if args.game_type else selected["game_type"]

        if pfx is None or not pfx.is_dir():
            print(f"\nError: prefix not found for AppID {appid}.")
            print("The modlist may not have been launched yet (prefix created on first run).")
            sys.exit(1)
    else:
        pfx = Path(args.prefix).expanduser().resolve()
        modlist_dir = Path(args.modlist_dir).expanduser().resolve() if args.modlist_dir else None

        if not pfx.is_dir():
            print(f"Error: prefix path does not exist: {pfx}")
            sys.exit(1)
        if modlist_dir is None or not modlist_dir.is_dir():
            print(f"Error: modlist directory does not exist: {modlist_dir}")
            sys.exit(1)

        game_type = args.game_type.lower() if args.game_type else detect_game_type(modlist_dir)
        # Infer appid from the compatdata path if possible (e.g. .../compatdata/12345/pfx)
        appid = pfx.parent.name if pfx.parent.name.isdigit() else ""

    passed = _run_verification(pfx, modlist_dir, game_type, appid)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
