"""
replace_mod step: replace a whole mod directory with a catalog asset.

`mod` is the mod directory name under `{modlist_dir}/mods/` (the standard MO2 layout).
`asset` must resolve through the catalog to an archive; the existing directory is renamed
aside when `backup` is true (default), then the asset is extracted in its place. Idempotency
is via the step's own `completed_when` (typically a `file_sha256` check on a known file inside
the replacement), per section 6 - not handled specially here.
"""
import shutil

from ..acquire import AcquisitionError, acquire_asset, extract_archive
from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed


def execute(ctx: StepContext, step) -> StepResult:
    fields = step.fields
    asset_id = fields.get("asset")
    mod_name = fields.get("mod")
    if not asset_id or not mod_name:
        return StepResult(False, "replace_mod: asset and mod are both required")

    catalog = ctx.catalog
    asset = catalog.assets.get(asset_id) if catalog else None
    if asset is None:
        return StepResult(False, f"replace_mod: unknown catalog asset {asset_id!r}")

    try:
        mod_dir = ctx.resolve(f"{{modlist_dir}}/mods/{mod_name}")
    except PlaybookPathError as e:
        return StepResult(False, f"replace_mod: invalid mod name: {e}")

    try:
        acquired = acquire_asset(asset)
    except AcquisitionError as e:
        return StepResult(False, f"replace_mod: {e}")

    if mod_dir.exists():
        if fields.get("backup", True):
            backup_dir = mod_dir.with_name(mod_dir.name + ".bak")
            try:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                mod_dir.rename(backup_dir)
            except OSError as e:
                return StepResult(False, f"replace_mod: could not back up existing mod: {e}")
        else:
            try:
                shutil.rmtree(mod_dir)
            except OSError as e:
                return StepResult(False, f"replace_mod: could not remove existing mod: {e}")

    if not extract_archive(acquired, mod_dir):
        return StepResult(False, f"replace_mod: extraction failed for {mod_name}")

    return StepResult(True)
