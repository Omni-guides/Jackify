"""Detection of GPU compute drivers, which the Wabbajack Linux Beta needs for fast texture encoding.

Its texture code runs on CUDA or OpenCL and falls back to the CPU when neither has a device.
The CPU path is many times slower on texture-heavy modlists. SteamOS ships the OpenCL loader
but no OpenCL driver, so a Steam Deck always lands on the CPU path.
"""
import ctypes.util
import glob
import os
from typing import Iterable, List

_ICD_DIRS = (
    "/etc/OpenCL/vendors",
    "/usr/share/OpenCL/vendors",
    "/usr/local/etc/OpenCL/vendors",
    "/usr/local/share/OpenCL/vendors",
)


def _icd_dirs() -> List[str]:
    dirs: List[str] = []
    for var in ("OCL_ICD_VENDORS", "OPENCL_VENDOR_PATH"):
        value = os.environ.get(var)
        if value:
            dirs.append(value)
    return dirs + list(_ICD_DIRS)


def _has_icd(dirs: Iterable[str]) -> bool:
    for entry in dirs:
        if os.path.isfile(entry) and entry.endswith(".icd"):
            return True
        if glob.glob(os.path.join(entry, "*.icd")):
            return True
    return False


def has_cuda() -> bool:
    return ctypes.util.find_library("cuda") is not None


def has_opencl() -> bool:
    return ctypes.util.find_library("OpenCL") is not None and _has_icd(_icd_dirs())


def gpu_texture_encoding_available() -> bool:
    """True when CUDA or an OpenCL driver is installed. Says nothing about the driver working."""
    return has_cuda() or has_opencl()
