"""Native Wine component installer.

Direct-source replacements for winetricks components.
Falls back to winetricks -> protontricks for unsupported or failed components.
"""

import datetime
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from jackify.backend.handlers.native_component_downloader import ComponentDownloadMixin
from jackify.shared.paths import get_jackify_data_dir

logger = logging.getLogger(__name__)

_D3DCOMPILER_47_X86_URL = "https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47_32.dll"
_D3DCOMPILER_47_X64_URL = "https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47.dll"
_D3DCOMPILER_47_X86_SHA256 = "2ad0d4987fc4624566b190e747c9d95038443956ed816abfd1e2d389b5ec0851"
_D3DCOMPILER_47_X64_SHA256 = "4432bbd1a390874f3f0a503d45cc48d346abc3a8c0213c289f4b615bf0ee84f3"

# The holarse mirror this used to point at now returns 403 for the whole
# /mirrors/microsoft/ path. Microsoft's Download Center entry (id=8109) is the primary
# source, with the Wayback capture of the old mirror as fallback.
_DIRECTX_CAB_URLS = (
    "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe",
    "https://web.archive.org/web/20260218142109id_/https://files.holarse-linuxgaming.de/mirrors/microsoft/directx_Jun2010_redist.exe",
)
# Microsoft re-signed the package in 2024. The Download Center copy and the archived copy
# differ in the outer signature only; the inner cabinets are identical.
_DIRECTX_CAB_SHA256 = (
    "053f76dcbb28802e23341b6a787e3b0791c0fa5c8d4d011b1044172dbf89c73b",
    "8746ee1a84a083a90e37899d71d50d5c7c015e69688a466aa80447f011780c0d",
)

_VCRUN2022_X86_URL = "https://aka.ms/vs/17/release/vc_redist.x86.exe"
_VCRUN2022_X64_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

_VCRUN2022_DLLS_X86 = ["concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
                       "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
                       "vcamp140.dll", "vccorlib140.dll", "vcomp140.dll", "vcruntime140.dll"]
_VCRUN2022_DLLS_X64 = _VCRUN2022_DLLS_X86 + ["vcruntime140_1.dll"]

_VCRUN2012_X86_URL = "https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/VSU_4/vcredist_x86.exe"
_VCRUN2012_X64_URL = "https://download.microsoft.com/download/1/6/B/16B06F60-3B20-4FF2-B699-5E9B7962F9AE/VSU_4/vcredist_x64.exe"


# (x86_stage1_patterns, x64_stage1_patterns, x86_dll_filters, x64_dll_filters, regsvr32)
_DX_CFG: Dict[str, tuple] = {
    "d3dcompiler_43": (
        ["*d3dcompiler_43*x86*"], ["*d3dcompiler_43*x64*"],
        ["d3dcompiler_43.dll"], ["d3dcompiler_43.dll"], False),
    "d3dx9": (
        ["*d3dx9*x86*"], ["*d3dx9*x64*"],
        ["d3dx9_*.dll"], ["d3dx9_*.dll"], False),
    "d3dx9_43": (
        ["*d3dx9*x86*"], ["*d3dx9*x64*"],
        ["d3dx9_43.dll"], ["d3dx9_43.dll"], False),
    "d3dx11_43": (
        ["*d3dx11_43*x86*"], ["*d3dx11_43*x64*"],
        ["d3dx11_43.dll"], ["d3dx11_43.dll"], False),
    "xact": (
        ["*_xact_*x86*", "*_x3daudio_*x86*", "*_xaudio_*x86*"], [],
        ["xactengine*.dll", "xaudio*.dll", "x3daudio*.dll", "xapofx*.dll"], [], True),
    "xact_x64": (
        [], ["*_xact_*x64*", "*_x3daudio_*x64*", "*_xaudio_*x64*"],
        [], ["xactengine*.dll", "xaudio*.dll", "x3daudio*.dll", "xapofx*.dll"], True),
}

_REGISTRY_WRITE_COMPONENTS = {"fontsmooth=rgb"}
_DLL_COPY_COMPONENTS = {"d3dcompiler_47"}
_DIRECTX_CAB_COMPONENTS = set(_DX_CFG.keys())
_WINE_INSTALLER_COMPONENTS = {"vcrun2022", "vcrun2012", "dotnet6", "dotnet7", "dotnet8", "dotnetdesktop6", "dotnet9", "dotnetdesktop9", "dotnet10", "dotnetdesktop10"}

# dotnet48 is handled by the bundled winetricks verb (see winetricks_handler), not natively:
# the ndp48 in-place servicing corrupts mscorlib under Wine.
SUPPORTED_COMPONENTS = (
    _REGISTRY_WRITE_COMPONENTS
    | _DLL_COPY_COMPONENTS
    | _DIRECTX_CAB_COMPONENTS
    | _WINE_INSTALLER_COMPONENTS
)


class NativeComponentInstaller(ComponentDownloadMixin):
    """Direct-source Wine component installer. Handles Groups 1-4 from the native install spec."""

    def __init__(self, wineprefix: str, wine_binary: str, wine_env: dict, log=None):
        self.wineprefix = wineprefix
        self.wine_binary = wine_binary
        self.wine_env = wine_env
        self.logger = log or logging.getLogger(__name__)

    def _emit_status(self, msg: str) -> None:
        cb = getattr(self, '_status_callback', None)
        if cb:
            cb(msg)

    def _kill_wineserver_for_prefix(self) -> None:
        """Kill wineserver for this prefix so the vcrun2022/vcrun2012 installers start against a
        fresh wineserver instead of whatever state a prior step left behind (matches the same
        precaution winetricks_handler takes before its own wine invocations)."""
        wineserver = self.wine_env.get('WINESERVER')
        if not wineserver or not os.path.exists(wineserver):
            return
        try:
            subprocess.run(
                [wineserver, '-k'],
                env=self._wine_env_base(),
                timeout=10,
                capture_output=True,
            )
            self.logger.debug("Killed wineserver for prefix before native Wine-based installers")
        except Exception as exc:
            self.logger.debug("Wineserver -k failed (non-fatal): %s", exc)

    def _wine_env_base(self, **extra) -> dict:
        base = {**self.wine_env, 'WINEPREFIX': self.wineprefix}
        parts = []
        for src in (base, extra):
            v = src.pop('WINEDLLOVERRIDES', None)
            if v:
                parts.append(v)
        parts.append('winemenubuilder.exe=d')
        base.update(extra)
        base['WINEDLLOVERRIDES'] = ','.join(parts)
        return base

    def install_components(
        self,
        components: List[str],
        status_callback=None,
    ) -> Tuple[List[str], List[str]]:
        """Attempt native install. Returns (succeeded, remaining); remaining goes to winetricks."""
        self._status_callback = status_callback
        succeeded = []
        remaining = []

        native_candidates = [c for c in components if c in SUPPORTED_COMPONENTS]

        if any(c in ("vcrun2022", "vcrun2012") for c in native_candidates):
            self._kill_wineserver_for_prefix()

        for component in components:
            if component not in SUPPORTED_COMPONENTS:
                remaining.append(component)
                continue

            self._current_component = component
            if status_callback:
                status_callback(f"[NATIVE_INSTALL] {component}")

            try:
                ok = self._install_component(component)
            except Exception as exc:
                self.logger.error("Native install of %s raised: %s", component, exc, exc_info=True)
                ok = False

            if ok:
                self.logger.info("Native install succeeded: %s", component)
                succeeded.append(component)
                self._write_winetricks_log(component)
            else:
                self.logger.warning("Native install failed for %s, falling through to winetricks", component)
                remaining.append(component)

        if succeeded:
            self._apply_dll_overrides()

        return succeeded, remaining

    def _install_component(self, component: str) -> bool:
        if component in _REGISTRY_WRITE_COMPONENTS:
            return self._install_registry_write(component)
        if component in _DLL_COPY_COMPONENTS:
            return self._install_dll_copy(component)
        if component in _DIRECTX_CAB_COMPONENTS:
            return self._install_directx_cab(component)
        if component == "vcrun2022":
            return self._install_vcrun2022()
        if component == "vcrun2012":
            return self._install_vcrun2012()
        return self._install_dotnet_modern(component)

    def _write_winetricks_log(self, component: str) -> None:
        log_path = Path(self.wineprefix) / 'winetricks.log'
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(component + '\n')
        except Exception as exc:
            self.logger.warning("Could not write winetricks.log: %s", exc)
        self._write_jackify_component_record(component)

    def _write_jackify_component_record(self, component: str) -> None:
        record_path = Path(self.wineprefix) / 'jackify_components.json'
        try:
            record = json.loads(record_path.read_text(encoding='utf-8')) if record_path.is_file() else {}
        except Exception:
            record = {}
        record[component] = {"method": "native", "timestamp": datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')}
        try:
            record_path.write_text(json.dumps(record, indent=2), encoding='utf-8')
        except Exception as exc:
            self.logger.warning("Could not write jackify_components.json: %s", exc)

    def _apply_dll_overrides(self) -> None:
        reg_file = Path(__file__).parent.parent / 'data' / 'dll_overrides.reg'
        if not reg_file.is_file():
            self.logger.warning("dll_overrides.reg not found at %s", reg_file)
            return
        overrides: Dict[str, str] = {}
        in_target = False
        for line in reg_file.read_text(encoding='utf-8').splitlines():
            s = line.strip()
            if s.startswith('['):
                in_target = 'Wine\\DllOverrides' in s
            elif in_target and s.startswith('"'):
                try:
                    q = s.index('"', 1)
                    rest = s[q + 1:]
                    if rest.startswith('='):
                        overrides[s[1:q]] = rest[1:]
                except (ValueError, IndexError):
                    pass
        if overrides:
            self._direct_reg_write(r'Software\Wine\DllOverrides', overrides)
            self.logger.debug("DLL overrides written directly to user.reg (%d entries)", len(overrides))

    def _get_cabextract(self) -> Optional[str]:
        if os.environ.get('APPDIR'):
            candidate = os.path.join(os.environ['APPDIR'], 'opt', 'jackify', 'tools', 'cabextract')
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        dev_candidate = str(Path(__file__).parent.parent.parent / 'tools' / 'cabextract')
        if os.path.isfile(dev_candidate) and os.access(dev_candidate, os.X_OK):
            return dev_candidate
        return shutil.which('cabextract')

    def _install_registry_write(self, component: str) -> bool:
        if component != "fontsmooth=rgb":
            return False
        return self._direct_reg_write(
            r'Control Panel\Desktop',
            {
                'FontSmoothing': '"2"',
                'FontSmoothingType': 'dword:00000002',
                'FontSmoothingGamma': 'dword:00000578',
            },
        )

    def _install_dll_copy(self, component: str) -> bool:
        if component != "d3dcompiler_47":
            return False
        cache_dir = get_jackify_data_dir() / 'component_cache' / 'd3dcompiler'
        cache_dir.mkdir(parents=True, exist_ok=True)
        syswow64 = Path(self.wineprefix) / 'drive_c' / 'windows' / 'syswow64'
        system32 = Path(self.wineprefix) / 'drive_c' / 'windows' / 'system32'
        syswow64.mkdir(parents=True, exist_ok=True)
        system32.mkdir(parents=True, exist_ok=True)

        for url, sha256, dest, fname in [
            (_D3DCOMPILER_47_X86_URL, _D3DCOMPILER_47_X86_SHA256, syswow64, 'd3dcompiler_47_32.dll'),
            (_D3DCOMPILER_47_X64_URL, _D3DCOMPILER_47_X64_SHA256, system32, 'd3dcompiler_47.dll'),
        ]:
            cached = cache_dir / fname
            if not self._download_file(url, cached, sha256):
                return False
            if not self._verify_sha256(cached, sha256):
                self.logger.error("SHA256 mismatch on %s after download", fname)
                cached.unlink()
                return False
            shutil.copy2(cached, dest / 'd3dcompiler_47.dll')
        return True

    def _install_directx_cab(self, component: str) -> bool:
        cfg = _DX_CFG.get(component)
        if not cfg:
            return False
        cabextract = self._get_cabextract()
        if not cabextract:
            self.logger.warning("cabextract not available for %s", component)
            return False

        cache_dir = get_jackify_data_dir() / 'component_cache' / 'directx'
        cache_dir.mkdir(parents=True, exist_ok=True)
        redist = cache_dir / 'directx_Jun2010_redist.exe'
        if not self._download_file(_DIRECTX_CAB_URLS, redist, _DIRECTX_CAB_SHA256):
            return False
        if not self._verify_sha256(redist, _DIRECTX_CAB_SHA256):
            self.logger.error("SHA256 mismatch on DirectX redistributable")
            redist.unlink()
            return False

        x86_patterns, x64_patterns, x86_dll_filters, x64_dll_filters, needs_regsvr32 = cfg
        syswow64, system32 = self._get_system_dirs()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            for arch_tag, stage1_patterns, dll_filters, dest_dir in [
                ('x86', x86_patterns, x86_dll_filters, syswow64),
                ('x64', x64_patterns, x64_dll_filters, system32),
            ]:
                if not stage1_patterns:
                    continue
                arch_tmp = tmpdir_path / arch_tag
                arch_tmp.mkdir()

                for pattern in stage1_patterns:
                    subprocess.run(
                        [cabextract, '-d', str(arch_tmp), '-L', '-F', pattern, str(redist)],
                        capture_output=True,
                    )

                inner_cabs = list(arch_tmp.glob('*.cab'))
                if not inner_cabs:
                    self.logger.error("No inner cabs found for %s %s", component, arch_tag)
                    return False

                for dll_filter in dll_filters:
                    for inner_cab in inner_cabs:
                        subprocess.run(
                            [cabextract, '-d', str(dest_dir), '-L', '-F', dll_filter, str(inner_cab)],
                            capture_output=True,
                        )

            if needs_regsvr32:
                com_dlls = list(syswow64.glob('xactengine*.dll')) + list(syswow64.glob('xaudio*.dll'))
                com_dlls += list(system32.glob('xactengine*.dll')) + list(system32.glob('xaudio*.dll'))
                self._register_xact_com(com_dlls)
        return True

    def _install_vcrun2022(self) -> bool:
        cabextract = self._get_cabextract()
        if not cabextract:
            self.logger.warning("cabextract not available for vcrun2022")
            return False

        cache_dir = get_jackify_data_dir() / 'component_cache' / 'vcrun'
        cache_dir.mkdir(parents=True, exist_ok=True)
        x86 = cache_dir / 'vc_redist.x86.exe'
        x64 = cache_dir / 'vc_redist.x64.exe'
        if not self._download_file(_VCRUN2022_X86_URL, x86):
            return False
        if not self._download_file(_VCRUN2022_X64_URL, x64):
            return False

        syswow64, system32 = self._get_system_dirs()

        # DLL overrides must be written before the installer runs so Wine picks them up
        self._apply_dll_overrides()

        env = self._wine_env_base()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # x86: pre-extract msvcp140.dll before running the installer.
            # Wine's builtin msvcp140 reports a higher version number so the installer
            # skips it without this manual extraction (Wine bug #57518).
            win32_tmp = tmpdir_path / 'win32'
            win32_tmp.mkdir()
            subprocess.run(
                [cabextract, '-d', str(win32_tmp), '-F', 'a10', str(x86)],
                capture_output=True,
            )
            inner_x86 = win32_tmp / 'a10'
            if inner_x86.is_file():
                subprocess.run(
                    [cabextract, '-d', str(syswow64), '-F', 'msvcp140.dll', str(inner_x86)],
                    capture_output=True,
                )
            else:
                self.logger.warning("vcrun2022: x86 inner cab 'a10' not found, msvcp140.dll pre-extraction skipped")

            self.logger.info("vcrun2022: running x86 installer")
            r = subprocess.run(
                [self.wine_binary, str(x86), '/q'],
                env=env,
                capture_output=True,
                timeout=600,
            )
            # 3010 = reboot required - normal for VC redist, treat as success
            if r.returncode not in (0, 3010):
                self.logger.error("vcrun2022: x86 installer failed (rc=%d)", r.returncode)
                self.logger.error("vcrun2022 x86 stderr: %s", r.stderr.decode(errors='replace'))
                self._discard_cached_installer(x86)
                return False

            # x64: same msvcp140.dll pre-extraction workaround
            win64_tmp = tmpdir_path / 'win64'
            win64_tmp.mkdir()
            subprocess.run(
                [cabextract, '-d', str(win64_tmp), '-F', 'a12', str(x64)],
                capture_output=True,
            )
            inner_x64 = win64_tmp / 'a12'
            if inner_x64.is_file():
                subprocess.run(
                    [cabextract, '-d', str(system32), '-F', 'msvcp140.dll', str(inner_x64)],
                    capture_output=True,
                )
            else:
                self.logger.warning("vcrun2022: x64 inner cab 'a12' not found, msvcp140.dll pre-extraction skipped")

            self.logger.info("vcrun2022: running x64 installer")
            r = subprocess.run(
                [self.wine_binary, str(x64), '/q'],
                env=env,
                capture_output=True,
                timeout=600,
            )
            if r.returncode not in (0, 3010):
                self.logger.error("vcrun2022: x64 installer failed (rc=%d)", r.returncode)
                self.logger.error("vcrun2022 x64 stderr: %s", r.stderr.decode(errors='replace'))
                self._discard_cached_installer(x64)
                return False

        critical = [
            (syswow64 / 'msvcp140.dll',       'msvcp140.dll (x86)'),
            (syswow64 / 'vcruntime140.dll',    'vcruntime140.dll (x86)'),
            (system32 / 'msvcp140.dll',        'msvcp140.dll (x64)'),
            (system32 / 'vcruntime140.dll',    'vcruntime140.dll (x64)'),
            (system32 / 'vcruntime140_1.dll',  'vcruntime140_1.dll (x64)'),
        ]
        for path, label in critical:
            if not path.is_file():
                self.logger.error("vcrun2022: %s missing after install", label)
                return False

        return True

    def _install_vcrun2012(self) -> bool:
        cache_dir = get_jackify_data_dir() / 'component_cache' / 'vcrun2012'
        cache_dir.mkdir(parents=True, exist_ok=True)
        x86 = cache_dir / 'vcredist_x86.exe'
        x64 = cache_dir / 'vcredist_x64.exe'
        if not self._download_file(_VCRUN2012_X86_URL, x86):
            return False
        if not self._download_file(_VCRUN2012_X64_URL, x64):
            return False

        self._apply_dll_overrides()

        env = self._wine_env_base()
        syswow64, system32 = self._get_system_dirs()

        self.logger.info("vcrun2012: running x86 installer")
        r = subprocess.run(
            [self.wine_binary, str(x86), '/q'],
            env=env,
            capture_output=True,
            timeout=300,
        )
        if r.returncode not in (0, 3010):
            self.logger.error("vcrun2012: x86 installer failed (rc=%d)", r.returncode)
            self.logger.error("vcrun2012 x86 stderr: %s", r.stderr.decode(errors='replace'))
            self._discard_cached_installer(x86)
            return False

        self.logger.info("vcrun2012: running x64 installer")
        r = subprocess.run(
            [self.wine_binary, str(x64), '/q'],
            env=env,
            capture_output=True,
            timeout=300,
        )
        if r.returncode not in (0, 3010):
            self.logger.error("vcrun2012: x64 installer failed (rc=%d)", r.returncode)
            self.logger.error("vcrun2012 x64 stderr: %s", r.stderr.decode(errors='replace'))
            self._discard_cached_installer(x64)
            return False

        if not (syswow64 / 'msvcr110.dll').is_file():
            self.logger.error("vcrun2012: msvcr110.dll missing after install")
            return False
        return True

    def _install_dotnet_modern(self, component: str) -> bool:
        urls = self._get_dotnet_urls(component)
        if not urls:
            return False
        x86_url, x64_url = urls
        cache_dir = get_jackify_data_dir() / 'component_cache' / 'dotnet'
        cache_dir.mkdir(parents=True, exist_ok=True)
        x86_zip = cache_dir / Path(x86_url).name
        x64_zip = cache_dir / Path(x64_url).name
        if not self._download_file(x86_url, x86_zip):
            return False
        if not self._download_file(x64_url, x64_zip):
            return False
        pfx = Path(self.wineprefix) / 'drive_c'
        for zip_path, dest in [(x86_zip, pfx / 'Program Files (x86)' / 'dotnet'),
                               (x64_zip, pfx / 'Program Files' / 'dotnet')]:
            dest.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(dest)
            except Exception as exc:
                self.logger.error("%s zip extraction failed for %s: %s", component, zip_path.name, exc)
                return False
        return True

    def _get_dotnet_urls(self, component: str) -> Optional[Tuple[str, str]]:
        manifest = Path(__file__).parent.parent / 'data' / 'native_components_versions.json'
        try:
            entry = json.loads(manifest.read_text()).get(component, {})
            x86 = entry.get('x86_zip_url', '')
            x64 = entry.get('x64_zip_url', '')
            if x86 and x64:
                return x86, x64
        except Exception as exc:
            self.logger.error("Could not load dotnet URLs for %s: %s", component, exc)
        self.logger.error("No zip URLs for %s in versions manifest", component)
        return None

    def _get_system_dirs(self) -> Tuple[Path, Path]:
        s64 = Path(self.wineprefix) / 'drive_c' / 'windows' / 'syswow64'
        s32 = Path(self.wineprefix) / 'drive_c' / 'windows' / 'system32'
        s64.mkdir(parents=True, exist_ok=True)
        s32.mkdir(parents=True, exist_ok=True)
        return s64, s32

    def _register_xact_com(self, dlls: List[Path]) -> None:
        manifest = Path(__file__).parent.parent / 'data' / 'native_components_versions.json'
        try:
            clsid_map = json.loads(manifest.read_text()).get('xact_clsids', {})
        except Exception:
            clsid_map = {}
        for dll_path in dlls:
            for clsid in clsid_map.get(dll_path.name.lower(), []):
                dir_name = dll_path.parent.name.lower()
                win_path = f'"C:\\\\windows\\\\{dir_name}\\\\{dll_path.name}"'
                self._direct_reg_write(
                    f'Software\\Classes\\CLSID\\{clsid}\\InprocServer32',
                    {'@': win_path, 'ThreadingModel': '"Both"'},
                )

    def _direct_reg_write(self, key_hkcu: str, values: Dict[str, str]) -> bool:
        """Write values to user.reg without spawning Wine. Later sections take precedence, so append is correct."""
        user_reg = Path(self.wineprefix) / 'user.reg'
        if not user_reg.is_file():
            self.logger.warning("user.reg not found at %s", user_reg)
            return False
        key_fmted = key_hkcu.replace('\\', '\\\\')
        try:
            with open(user_reg, 'a', encoding='utf-8') as f:
                f.write(f'\n[{key_fmted}] {int(time.time())}\n')
                for name, val in values.items():
                    f.write(f'@={val}\n' if name == '@' else f'"{name}"={val}\n')
            return True
        except Exception as exc:
            self.logger.error("Direct registry write failed for %s: %s", key_hkcu, exc)
            return False


