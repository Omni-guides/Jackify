"""
patch_text_file step: in-place line-level edits to an existing text file.

`anchor` is always a literal substring match, never a regex - the spec is explicit that
anything unreviewable in a diff (regex_replace, patch_binary_file) is out of scope entirely, and
this is the step that would otherwise be tempted to grow one. Atomic write via tempfile +
os.replace, matching problem_mods_service.py's existing pattern. Capped at 8MB, UTF-8 only.
"""
import os
import tempfile

from ..paths import PlaybookPathError
from .base import StepContext, StepResult, default_completed

completed = default_completed

_MAX_FILE_BYTES = 8 * 1024 * 1024
_VALID_OPERATIONS = {
    "append_line", "prepend_line", "insert_before", "insert_after",
    "replace_line", "ensure_line", "comment_line",
}


def _detect_line_ending(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def execute(ctx: StepContext, step) -> StepResult:
    fields = step.fields
    operation = fields.get("operation")
    if operation not in _VALID_OPERATIONS:
        return StepResult(False, f"patch_text_file: unknown operation {operation!r}")

    try:
        path = ctx.resolve(fields["path"])
    except (KeyError, PlaybookPathError) as e:
        return StepResult(False, f"patch_text_file: invalid path: {e}")

    if not path.is_file():
        return StepResult(False, f"patch_text_file: file does not exist: {path}")
    if path.stat().st_size > _MAX_FILE_BYTES:
        return StepResult(False, f"patch_text_file: file exceeds 8MB cap: {path}")

    try:
        # newline="" disables universal-newline translation on read - without it, \r\n would
        # already be collapsed to \n before _detect_line_ending ever sees it.
        original = path.read_text(encoding="utf-8", newline="")
    except (UnicodeDecodeError, OSError) as e:
        return StepResult(False, f"patch_text_file: could not read {path}: {e}")

    eol = _detect_line_ending(original)
    # A trailing newline produces a trailing empty element on split(); strip it before editing
    # and re-add it after, otherwise append_line/prepend_line would insert an extra blank line
    # rather than landing after/before the file's actual last line.
    has_trailing_newline = original.endswith(eol)
    body = original[: -len(eol)] if has_trailing_newline else original
    lines = body.split(eol)
    content = fields.get("content", "")
    anchor = fields.get("anchor")

    # Idempotent by construction, for every operation with a fixed target line: the runtime
    # already skips execute() when completed_when says done, but this is defense in depth
    # against a step that omitted it (and against insert_before/insert_after inserting a
    # duplicate on a second run, since the anchor line itself is never consumed).
    if operation != "comment_line" and content and content in lines:
        return StepResult(True, "already present")

    if operation in ("append_line", "prepend_line", "ensure_line"):
        lines = ([content] + lines) if operation == "prepend_line" else (lines + [content])
    else:
        if not anchor:
            return StepResult(False, f"patch_text_file: {operation} requires anchor")
        index = next((i for i, line in enumerate(lines) if anchor in line), None)
        if index is None:
            return StepResult(True, f"anchor not found, nothing to do: {anchor!r}")
        if operation == "insert_before":
            lines = lines[:index] + [content] + lines[index:]
        elif operation == "insert_after":
            lines = lines[:index + 1] + [content] + lines[index + 1:]
        elif operation == "replace_line":
            lines[index] = content
        elif operation == "comment_line":
            # comment_prefix isn't fixed by the spec (depends on the target file's syntax) -
            # defaults to "#", overridable per step for INI (";") or other formats.
            prefix = fields.get("comment_prefix", "#")
            if not lines[index].lstrip().startswith(prefix):
                lines[index] = f"{prefix}{lines[index]}"

    new_content = eol.join(lines)
    if has_trailing_newline:
        new_content += eol
    if new_content == original:
        return StepResult(True, "no change needed")

    if bool(fields.get("backup", False)):
        try:
            path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        except OSError as e:
            ctx.log(f"patch_text_file: backup failed for {path}: {e}")

    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".playbook_patch_", suffix=".tmp")
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
        return StepResult(False, f"patch_text_file: write failed: {e}")

    return StepResult(True)
