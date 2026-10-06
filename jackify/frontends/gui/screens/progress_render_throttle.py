"""Rate limit for install progress rendering.

The engine emits many progress lines per second during install; redrawing the banner and
Activity list on every one made the counters visibly flicker.
"""

import time

from PySide6.QtCore import QTimer

from jackify.shared.progress_models import InstallationProgress

RENDER_INTERVAL_SECONDS = 0.1


def should_render_progress(owner: object, state: InstallationProgress) -> bool:
    """Return True if progress should be redrawn now. Phase changes always render.

    A skipped update is redrawn once the interval ends, so the last state before a quiet
    period (CLF3 goes silent for long stretches while decompressing) is never lost.
    """
    now = time.monotonic()
    phase_key = (state.phase, state.phase_name, state.get_phase_label())
    last_key = getattr(owner, '_progress_render_phase_key', None)
    last_at = getattr(owner, '_progress_render_at', 0.0)
    elapsed = now - last_at
    if phase_key == last_key and elapsed < RENDER_INTERVAL_SECONDS:
        owner._progress_render_pending = state
        if not getattr(owner, '_progress_render_armed', False):
            owner._progress_render_armed = True
            delay_ms = int((RENDER_INTERVAL_SECONDS - elapsed) * 1000) + 1
            QTimer.singleShot(delay_ms, owner, lambda: _flush_pending(owner))
        return False
    owner._progress_render_phase_key = phase_key
    owner._progress_render_at = now
    owner._progress_render_pending = None
    return True


def _flush_pending(owner) -> None:
    owner._progress_render_armed = False
    state = getattr(owner, '_progress_render_pending', None)
    owner._progress_render_pending = None
    thread = getattr(owner, 'install_thread', None)
    # on_installation_finished waits for the thread before clearing the display, so a
    # stopped thread means the install is over and this state is stale.
    if state is None or thread is None or not thread.isRunning():
        return
    owner.on_progress_updated(state)
