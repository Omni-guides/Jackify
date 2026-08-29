"""
Expression grammar for playbook `confirm`, `completed_when`, and `success_when` blocks.

Evaluation is total and side-effect free: any leaf that hits an error (unreadable file,
permission denied, missing context data, unknown type) evaluates to False and never raises.
This lets every caller treat "expression didn't match" and "expression couldn't be evaluated"
identically, rather than needing a separate error path at every call site. See
docs/0.8_work/modlist_playbook_system.md section 4.4.
"""
import configparser
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .paths import PlaybookPathError, resolve_path

logger = logging.getLogger(__name__)

_MAX_DEPTH = 4
_MAX_TEXT_FILE_BYTES = 8 * 1024 * 1024


@dataclass
class ExpressionContext:
    """Runtime facts an expression may need beyond what it can read from disk itself."""
    roots: Dict[str, Path] = field(default_factory=dict)
    mo2_profile: Optional[str] = None
    game_type: Optional[str] = None
    exit_code: Optional[int] = None
    output: str = ""
    mod_enabled: Optional[Callable[[str], bool]] = None
    mod_present: Optional[Callable[[str], bool]] = None


def evaluate(expr: dict, ctx: ExpressionContext) -> bool:
    """Evaluate a confirm/completed_when/success_when expression tree. Never raises."""
    try:
        return _evaluate(expr, ctx, depth=0)
    except Exception:
        logger.debug("Expression evaluation failed, treating as false: %r", expr, exc_info=True)
        return False


def _evaluate(expr: Any, ctx: ExpressionContext, depth: int) -> bool:
    if not isinstance(expr, dict) or depth > _MAX_DEPTH:
        return False

    if "all" in expr:
        return all(_evaluate(e, ctx, depth + 1) for e in expr["all"])
    if "any" in expr:
        return any(_evaluate(e, ctx, depth + 1) for e in expr["any"])
    if "not" in expr:
        return not _evaluate(expr["not"], ctx, depth + 1)

    handler = _LEAF_HANDLERS.get(expr.get("type"))
    return handler(expr, ctx) if handler else False


def _resolve(expr: dict, ctx: ExpressionContext) -> Optional[Path]:
    try:
        return resolve_path(expr["path"], ctx.roots)
    except (PlaybookPathError, KeyError):
        return None


def _file_exists(expr: dict, ctx: ExpressionContext) -> bool:
    path = _resolve(expr, ctx)
    return path is not None and path.is_file()


def _file_absent(expr: dict, ctx: ExpressionContext) -> bool:
    path = _resolve(expr, ctx)
    return path is None or not path.exists()


def _dir_exists(expr: dict, ctx: ExpressionContext) -> bool:
    path = _resolve(expr, ctx)
    return path is not None and path.is_dir()


def _file_sha256(expr: dict, ctx: ExpressionContext) -> bool:
    path = _resolve(expr, ctx)
    if path is None or not path.is_file():
        return False
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == str(expr.get("sha256", "")).lower()


def _read_text_capped(path: Path) -> Optional[str]:
    if path.stat().st_size > _MAX_TEXT_FILE_BYTES:
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _text_present(expr: dict, ctx: ExpressionContext) -> bool:
    path = _resolve(expr, ctx)
    if path is None or not path.is_file():
        return False
    content = _read_text_capped(path)
    if content is None:
        return False
    text = expr.get("text", "")
    return text.lower() in content.lower() if expr.get("ignore_case") else text in content


def _text_absent(expr: dict, ctx: ExpressionContext) -> bool:
    return not _text_present(expr, ctx)


def _ini_value(expr: dict, ctx: ExpressionContext) -> bool:
    path = _resolve(expr, ctx)
    if path is None or not path.is_file():
        return False
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error:
        return False
    section, key = expr.get("section", ""), expr.get("key", "")
    if not parser.has_section(section) or not parser.has_option(section, key):
        return False
    return parser.get(section, key) == expr.get("equals", "")


def _mod_enabled(expr: dict, ctx: ExpressionContext) -> bool:
    return bool(ctx.mod_enabled and ctx.mod_enabled(expr.get("mod", "")))


def _mod_present(expr: dict, ctx: ExpressionContext) -> bool:
    return bool(ctx.mod_present and ctx.mod_present(expr.get("mod", "")))


def _mo2_profile(expr: dict, ctx: ExpressionContext) -> bool:
    return ctx.mo2_profile in expr.get("values", [])


def _game_type(expr: dict, ctx: ExpressionContext) -> bool:
    return ctx.game_type in expr.get("values", [])


def _exit_code(expr: dict, ctx: ExpressionContext) -> bool:
    return ctx.exit_code in expr.get("values", [])


def _output_contains(expr: dict, ctx: ExpressionContext) -> bool:
    text = expr.get("text", "")
    return text.lower() in ctx.output.lower() if expr.get("ignore_case") else text in ctx.output


_LEAF_HANDLERS: Dict[str, Callable[[dict, ExpressionContext], bool]] = {
    "file_exists": _file_exists,
    "file_absent": _file_absent,
    "dir_exists": _dir_exists,
    "file_sha256": _file_sha256,
    "text_present": _text_present,
    "text_absent": _text_absent,
    "ini_value": _ini_value,
    "mod_enabled": _mod_enabled,
    "mod_present": _mod_present,
    "mo2_profile": _mo2_profile,
    "game_type": _game_type,
    "exit_code": _exit_code,
    "output_contains": _output_contains,
}
