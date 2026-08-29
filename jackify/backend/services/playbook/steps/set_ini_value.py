"""
set_ini_value step: set a `key=value` pair under `[section]` in an INI-style file.

Line-based, not `configparser` - MO2's own `.ini` files use `@ByteArray(...)`-wrapped values and
are case-sensitive on keys, and a generic INI parser would risk reformatting or mangling lines
it doesn't need to touch. A playbook author writing e.g. `@ByteArray(...)` into `value` gets it
written literally, matching how the `ini_value` confirm/completed_when expression already
compares values as plain strings with no special-casing.
"""
import os
import tempfile

from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed


def execute(ctx: StepContext, step) -> StepResult:
    fields = step.fields
    section, key, value = fields.get("section"), fields.get("key"), fields.get("value")
    if not section or not key or value is None:
        return StepResult(False, "set_ini_value: section, key, and value are all required")

    try:
        path = ctx.resolve(fields["path"])
    except (KeyError, PlaybookPathError) as e:
        return StepResult(False, f"set_ini_value: invalid path: {e}")

    if not path.is_file():
        return StepResult(False, f"set_ini_value: file does not exist: {path}")

    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return StepResult(False, f"set_ini_value: could not read {path}: {e}")

    eol = "\r\n" if "\r\n" in original else "\n"
    lines = original.split(eol)
    new_line = f"{key}={value}"

    section_header = f"[{section}]"
    section_start = next(
        (i for i, line in enumerate(lines) if line.strip() == section_header), None
    )

    if section_start is None:
        if not fields.get("create_section", False):
            return StepResult(False, f"set_ini_value: section {section!r} not found")
        new_content = eol.join(lines + ["", section_header, new_line]) if original else eol.join(
            [section_header, new_line]
        )
    else:
        section_end = len(lines)
        for i in range(section_start + 1, len(lines)):
            if lines[i].strip().startswith("[") and lines[i].strip().endswith("]"):
                section_end = i
                break

        key_line_index = None
        for i in range(section_start + 1, section_end):
            stripped = lines[i].strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                key_line_index = i
                break

        if key_line_index is not None:
            if lines[key_line_index] == new_line:
                return StepResult(True, "already set")
            lines[key_line_index] = new_line
        else:
            lines = lines[:section_end] + [new_line] + lines[section_end:]
        new_content = eol.join(lines)

    if new_content == original:
        return StepResult(True, "no change needed")

    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".playbook_ini_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_content)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        return StepResult(False, f"set_ini_value: write failed: {e}")

    return StepResult(True)
