"""
Menu handler input and readline tab completion.
Exports: READLINE_* constants, basic_input_prompt, input_prompt, simple_path_completer, _shell_path_completer, _simple_path_completer.
"""

import logging
import os
import glob

from jackify.shared.colors import COLOR_PROMPT, COLOR_RESET

READLINE_AVAILABLE = False
READLINE_HAS_PROMPT = False
READLINE_HAS_DISPLAY_HOOK = False

try:
    import readline
    READLINE_AVAILABLE = True
    logging.debug("Readline imported for tab completion")
    if hasattr(readline, 'set_prompt'):
        READLINE_HAS_PROMPT = True
        logging.debug("Readline has set_prompt capability")
    else:
        logging.debug("Readline does not have set_prompt capability, will use fallback")
    try:
        readline.parse_and_bind('tab: complete')
        logging.debug("Readline tab completion successfully configured")
    except Exception as e:
        logging.warning(f"Error configuring readline tab completion: {e}. Tab completion may be limited.")
    if hasattr(readline, 'set_completion_display_matches_hook'):
        READLINE_HAS_DISPLAY_HOOK = True
        logging.debug("Readline has completion display hook capability")

        def custom_display_completions(substitution, matches, longest_match_length):
            print()
            try:
                import shutil
                term_width = shutil.get_terminal_size().columns
            except (ImportError, AttributeError):
                term_width = 80
            items_per_line = max(1, term_width // (longest_match_length + 2))
            for i, match in enumerate(matches):
                print(f"{match:<{longest_match_length + 2}}", end='' if (i + 1) % items_per_line else '\n')
            if len(matches) % items_per_line != 0:
                print()
            current_input = readline.get_line_buffer()
            print(f"{COLOR_PROMPT}> {COLOR_RESET}{current_input}", end='', flush=True)

        try:
            readline.set_completion_display_matches_hook(custom_display_completions)
            logging.debug("Custom completion display hook successfully set")
        except Exception as e:
            logging.warning(f"Error setting completion display hook: {e}. Using default display behavior.")
            READLINE_HAS_DISPLAY_HOOK = False
    else:
        logging.debug("Readline doesn't have completion display hook capability, using default")
except ImportError:
    logging.warning("readline not available. Tab completion for paths will be disabled.")
except Exception as e:
    logging.warning(f"Error initializing readline: {e}. Tab completion for paths will be disabled.")


def basic_input_prompt(message, **kwargs):
    return input(message)


input_prompt = basic_input_prompt


def _shell_path_completer(text, state):
    """Shell-like pathname completer for readline. Expands ~, handles absolute/relative paths."""
    expanded = os.path.expanduser(os.path.expandvars(text))
    if os.path.isdir(expanded):
        pattern = os.path.join(expanded, '*')
    else:
        pattern = expanded + '*'
    matches = glob.glob(pattern)
    matches = [m + ('/' if os.path.isdir(m) else '') for m in matches]
    if not text:
        matches = glob.glob('*')
        matches = [m + ('/' if os.path.isdir(m) else '') for m in matches]
    try:
        return matches[state]
    except IndexError:
        return None


def _simple_path_completer(text, state):
    """Simple pathname completer for readline. Prefix matching on path components."""
    matches = glob.glob(text + '*')
    matches = [f + ('/' if os.path.isdir(f) else '') for f in matches]
    try:
        return matches[state]
    except IndexError:
        return None


simple_path_completer = _simple_path_completer
