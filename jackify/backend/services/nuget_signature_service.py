"""
NuGet package signature trust configuration for Wine prefixes.

Synthesis compiles C# patchers under Wine using an installed .NET SDK, which
requires NuGet package signature validation to succeed. Split out of
tool_config_service.py to keep that file under the project's size guardrail.

Old (2018-2021 era) Microsoft BCL packages carry timestamp signatures chaining
to legacy VeriSign/Symantec roots that modern distros have removed from their
trust stores. Wine seeds its Root store from the host bundle, so those roots
are missing in the prefix and NuGet fails restore with NU3028 ("timestamping
certificate is not trusted"). NuGet treats an untrusted root on the TIMESTAMP
chain as a hard error unconditionally (see Timestamp.Verify in NuGet.Client -
UntrustedRoot is logged as Error regardless of signatureValidationMode,
allowUntrustedRoot, or any env var), so the only fix is making the roots
actually trusted in the prefix's cert store.
"""

import base64
import hashlib
import logging
import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

# Every NuGet.Config we write pins nuget.org's repository signing certs by
# fingerprint with allowUntrustedRoot, so the SIGNING chain does not depend on
# the CA root chain being trusted. The TIMESTAMP chain is not covered by this
# (see module docstring) - that requires the root cert import below.
# Fingerprints are nuget.org's own signing certs (public, stable across signing
# key rotations) - see SulfurNitride/Fluorine-Manager commit d453ed91b6dc332fd45987c642e9d230efe870c8.
_NUGET_CONFIG_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <config>
    <add key="signatureValidationMode" value="accept" />
  </config>
  <packageSources>
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" protocolVersion="3" />
  </packageSources>
  <trustedSigners>
    <repository name="nuget.org" serviceIndex="https://api.nuget.org/v3/index.json">
      <certificate fingerprint="0E5F38F57DC1BCC806D8494F4F90FBCEDD988B46760709CBEEC6F4219AA6157D" hashAlgorithm="SHA256" allowUntrustedRoot="true" />
      <certificate fingerprint="5A2901D6ADA3D18260B9C6DFE2133C95D74B9EEF6AE0E5DC334C8454D1477DF4" hashAlgorithm="SHA256" allowUntrustedRoot="true" />
      <certificate fingerprint="1F4B311D9ACC115C8DC8018B5A49E00FCE6DA8E2855F9F014CA6F34570BC482D" hashAlgorithm="SHA256" allowUntrustedRoot="true" />
    </repository>
  </trustedSigners>
</configuration>
"""

_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", re.DOTALL
)

# Registry path Wine's crypt32 reads trusted roots from - the same location it
# seeds with the host CA bundle at prefix init.
_ROOT_STORE_KEY = "HKEY_LOCAL_MACHINE\\Software\\Microsoft\\SystemCertificates\\Root\\Certificates"

CERT_CERT_PROP_ID = 32


def _find_sdk_trusted_roots(prefix_path: Path) -> Optional[Tuple[Path, Path]]:
    """
    Locate the newest installed .NET SDK's bundled trustedroots PEM files.
    Returns (codesignctl.pem, timestampctl.pem) or None if not found.
    """
    sdk_root = prefix_path / "drive_c" / "Program Files" / "dotnet" / "sdk"
    if not sdk_root.is_dir():
        return None

    for version_dir in sorted(sdk_root.iterdir(), reverse=True):
        trustedroots = version_dir / "trustedroots"
        codesign = trustedroots / "codesignctl.pem"
        timestamp = trustedroots / "timestampctl.pem"
        if codesign.exists() and timestamp.exists():
            return codesign, timestamp

    return None


def _read_pem_bundle(bundle_path: Path) -> Iterator[bytes]:
    """Yield DER-encoded certificates from a concatenated PEM bundle."""
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    for match in _PEM_CERT_RE.finditer(text):
        yield base64.b64decode("".join(match.group(1).split()))


def _cert_registry_blob(der: bytes) -> bytes:
    """
    Serialize a certificate the way crypt32 stores it in the registry: a
    property record of DWORD propid, DWORD reserved (1), DWORD length, then
    the raw DER. A blob containing only the CERT_CERT_PROP_ID record is valid.
    """
    return struct.pack("<III", CERT_CERT_PROP_ID, 1, len(der)) + der


def _hex_reg_value(name: str, data: bytes) -> str:
    """Format a REG_BINARY value as regedit .reg hex syntax with line wrapping."""
    hex_bytes = [f"{b:02x}" for b in data]
    lines = []
    line = f'"{name}"=hex:'
    for hb in hex_bytes:
        if len(line) + len(hb) + 2 > 76:
            lines.append(line + "\\")
            line = "  "
        line += hb + ","
    lines.append(line.rstrip(","))
    return "\n".join(lines)


def _build_certs_reg_content(bundles: Tuple[Path, ...]) -> Tuple[str, frozenset]:
    """
    Build a .reg file adding every cert in the given PEM bundles to the Wine
    prefix's Root store. Returns (reg_content, unique_thumbprints). Re-importing
    is idempotent - regedit overwrites identical keys in place.
    """
    seen = set()
    parts = ["Windows Registry Editor Version 5.00"]
    for bundle in bundles:
        for der in _read_pem_bundle(bundle):
            thumbprint = hashlib.sha1(der).hexdigest().upper()
            if thumbprint in seen:
                continue
            seen.add(thumbprint)
            parts.append("")
            parts.append(f"[{_ROOT_STORE_KEY}\\{thumbprint}]")
            parts.append(_hex_reg_value("Blob", _cert_registry_blob(der)))
    parts.append("")
    return "\n".join(parts), frozenset(seen)


def _missing_thumbprints(prefix_path: Path, thumbprints: frozenset) -> frozenset:
    """
    Check which of the given thumbprints are actually present in the prefix's
    on-disk system.reg. regedit's exit code alone is not reliable here - large
    batch imports (~400+ keys) have been observed to silently drop individual
    entries while exiting 0, with no indication in stdout/stderr.

    system.reg stores hive-relative paths (no HKEY_LOCAL_MACHINE prefix) with
    each backslash doubled, unlike the .reg file syntax used to write them.
    """
    system_reg = prefix_path / "system.reg"
    if not system_reg.exists():
        return thumbprints

    text = system_reg.read_text(encoding="utf-8", errors="replace")
    key_path = _ROOT_STORE_KEY.split("\\", 1)[1]
    file_literal = key_path.replace("\\", "\\\\")
    pattern = re.compile(rf"\[{re.escape(file_literal)}\\\\([0-9A-Fa-f]+)\]")
    present = set(pattern.findall(text))
    return thumbprints - present


def install_nuget_cert(
    prefix_path: Path,
    wine_bin: str,
    log: Callable[[str], None],
    max_attempts: int = 3,
) -> bool:
    """
    Import the .NET SDK's bundled code-signing and timestamp trusted-root
    certificates into the Wine prefix's Root cert store, by writing serialized
    cert blobs directly into the registry via regedit.

    Regedit is the only mechanism that actually persists here: certutil.exe
    and rundll32 cryptext.dll are unimplemented stubs in Wine, and crypt32
    cert store writes (X509Store.Add / CertAddCertificateContextToStore) under
    GE-Proton report success but never reach wineserver's registry - the added
    certs are visible only inside the importing process and are gone once it
    exits (confirmed on CachyOS + GE-Proton10-14: store reported the add,
    cross-process reg query and the on-disk .reg files never saw it).

    regedit's own exit code is also not trustworthy on a batch this size
    (~400 keys): it has been observed to exit 0 while silently dropping a
    single entry, with no trace in stdout/stderr. Confirmed root cause of a
    long-standing, hard-to-reproduce Synthesis NuGet failure - the one dropped
    cert was the VeriSign Universal Root, the exact timestamp-chain root
    NU3028 checks for. So every import is verified against the on-disk
    registry afterward and retried on a partial result.

    Requires the .NET SDK already installed in the prefix - the PEM bundles
    ship inside the SDK and are the exact trust anchors NuGet itself uses for
    package and timestamp signature validation on Linux.
    """
    trusted_roots = _find_sdk_trusted_roots(prefix_path)
    if trusted_roots is None:
        log(".NET SDK trusted root bundles not found - skipping NuGet certificate import")
        return False

    reg_content, thumbprints = _build_certs_reg_content(trusted_roots)
    cert_count = len(thumbprints)

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix_path)
    env["WINEDEBUG"] = "-all"
    env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
    env["DISPLAY"] = env.get("DISPLAY", ":0")
    wineserver_bin = os.path.join(os.path.dirname(wine_bin), "wineserver")

    reg_file = None
    missing = thumbprints
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".reg", delete=False, encoding="utf-8"
        ) as tf:
            tf.write(reg_content)
            reg_file = tf.name

        for attempt in range(1, max_attempts + 1):
            log(
                f"Importing {cert_count} code-signing and timestamp roots into "
                f"Wine cert store (attempt {attempt}/{max_attempts})..."
            )
            result = subprocess.run(
                [wine_bin, "regedit", reg_file],
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                log(f"Certificate registry import exited with code {result.returncode}")
                log(f"stderr: {result.stderr[:500]}")
                continue

            # wineserver batches registry writes in memory and flushes to the
            # on-disk .reg files lazily. "wineserver -w" blocks until wineserver
            # exits, forcing the flush - same pattern used elsewhere for registry
            # writes (see modlist_wine_ops.py).
            if os.path.exists(wineserver_bin):
                try:
                    subprocess.run(
                        [wineserver_bin, "-w"], env=env, timeout=60, capture_output=True,
                    )
                except Exception as e:
                    log(f"wineserver flush failed (non-fatal): {e}")
            else:
                log(f"wineserver not found at {wineserver_bin}; registry flush may not persist")

            missing = _missing_thumbprints(prefix_path, thumbprints)
            if not missing:
                log(f"Imported {cert_count} certificates into Wine cert store")
                return True

            log(f"{len(missing)} of {cert_count} certificates did not persist - retrying import")

        log(
            f"Certificate import incomplete after {max_attempts} attempts - "
            f"{len(missing)} of {cert_count} certificates still missing"
        )
        return False

    except Exception as e:
        log(f"Failed to install NuGet certificates: {e}")
        return False
    finally:
        if reg_file:
            try:
                os.unlink(reg_file)
            except Exception:
                pass


def configure_nuget_signature_policy(
    prefix_path: Path,
    log: Callable[[str], None],
) -> bool:
    """
    Write a NuGet.Config that pins nuget.org's signing certificates by
    fingerprint with allowUntrustedRoot, so signing-chain validation does not
    depend on the CA root chain. Timestamp-chain trust is handled separately
    by install_nuget_cert (see module docstring).

    Steam/Proton prefixes always use "steamuser" as the Windows user.

    Ideally runs before the first dotnet invocation in the prefix, since the
    SDK auto-generates a bare-bones NuGet.Config (no trust policy) as a side
    effect of any restore if none exists yet. That stub can also predate this
    fix (an older Jackify version, or a manual restore run in the prefix
    before configuration), so an existing file is only left alone if it
    already carries our trust policy - otherwise it's replaced.
    """
    config_dir = prefix_path / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / "NuGet"
    config_path = config_dir / "NuGet.Config"

    if config_path.exists():
        try:
            existing = config_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log(f"Failed to read existing NuGet.Config: {e}")
            existing = ""
        if "trustedSigners" in existing:
            log("NuGet.Config already has a trust policy - leaving it unchanged")
            return True
        log("NuGet.Config exists without a trust policy (SDK-generated stub) - replacing it")

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_NUGET_CONFIG_TEMPLATE, encoding="utf-8")
        log("NuGet signature policy configured (nuget.org signers trusted by fingerprint)")
        return True
    except Exception as e:
        log(f"Failed to write NuGet.Config: {e}")
        return False
