"""
replace_mod_file step: swap one file inside an existing mod for a catalog asset.

The Lorerim JContainers case: a fixed DLL exists on GitHub but never reached Nexus. `asset`
resolves through the catalog (never a raw URL in the playbook itself), `dest` is the file being
replaced. `backup` (default true) renames the original aside rather than overwriting it blind.
"""
import shutil

from ..acquire import AcquisitionError, acquire_asset
from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed


def execute(ctx: StepContext, step) -> StepResult:
    fields = step.fields
    asset_id = fields.get("asset")
    if not asset_id:
        return StepResult(False, "replace_mod_file: asset is required")

    catalog = ctx.catalog
    asset = catalog.assets.get(asset_id) if catalog else None
    if asset is None:
        return StepResult(False, f"replace_mod_file: unknown catalog asset {asset_id!r}")

    try:
        dest = ctx.resolve(fields["dest"])
    except (KeyError, PlaybookPathError) as e:
        return StepResult(False, f"replace_mod_file: invalid dest: {e}")

    try:
        acquired = acquire_asset(asset)
    except AcquisitionError as e:
        return StepResult(False, f"replace_mod_file: {e}")

    if fields.get("backup", True) and dest.exists():
        try:
            shutil.copy2(dest, dest.with_name(dest.name + ".bak"))
        except OSError as e:
            ctx.log(f"replace_mod_file: backup failed for {dest}: {e}")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(acquired, dest)
    except OSError as e:
        return StepResult(False, f"replace_mod_file: copy failed: {e}")

    return StepResult(True)
