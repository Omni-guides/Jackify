"""
Step type dispatch: maps a playbook step's `type` to its `completed`/`execute` functions.

One module per type (section 6) so each stays small and independently reviewable. Adding a new
step type later is a new file here plus one dispatch entry, not a change to existing files.
"""
from . import (
    copy_files,
    create_directory,
    delete_file,
    offer_tool_flow,
    patch_text_file,
    replace_mod,
    replace_mod_file,
    run_catalog_tool,
    run_modlist_script,
    set_ini_value,
    set_mod_state,
    show_user_message,
)
from .base import StepContext, StepResult

STEP_MODULES = {
    "copy_files": copy_files,
    "create_directory": create_directory,
    "delete_file": delete_file,
    "offer_tool_flow": offer_tool_flow,
    "patch_text_file": patch_text_file,
    "replace_mod": replace_mod,
    "replace_mod_file": replace_mod_file,
    "run_catalog_tool": run_catalog_tool,
    "run_modlist_script": run_modlist_script,
    "set_ini_value": set_ini_value,
    "set_mod_state": set_mod_state,
    "show_user_message": show_user_message,
}


def is_completed(ctx: StepContext, step) -> bool:
    module = STEP_MODULES.get(step.type)
    if module is None:
        return False
    return module.completed(ctx, step)


def execute_step(ctx: StepContext, step) -> StepResult:
    module = STEP_MODULES.get(step.type)
    if module is None:
        return StepResult(False, f"unknown step type: {step.type!r}")
    return module.execute(ctx, step)
