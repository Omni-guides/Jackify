"""Shortcut loading for ConfigureExistingModlistScreen (Mixin)."""
from PySide6.QtCore import QThread, Signal, QObject
import logging
import warnings

logger = logging.getLogger(__name__)
class ConfigureExistingModlistShortcutsMixin:
    """Mixin providing shortcut loading for ConfigureExistingModlistScreen."""

    def _load_shortcuts_async(self):
        """Load ModOrganizer.exe shortcuts asynchronously to avoid blocking UI"""
        from PySide6.QtCore import QThread, Signal, QObject
        
        class ShortcutLoaderThread(QThread):
            finished_signal = Signal(list)  # Emits list of shortcuts when done
            error_signal = Signal(str)  # Emits error message if something goes wrong
            
            def run(self):
                try:
                    # Suppress all logging/output in background thread to avoid reentrant stderr issues
                    import logging
                    import sys
                    
                    # Temporarily redirect stderr to avoid reentrant calls
                    old_stderr = sys.stderr
                    try:
                        # Use a null device or StringIO to capture errors without writing to stderr
                        from io import StringIO
                        sys.stderr = StringIO()
                        
                        # Fetch shortcuts for ModOrganizer.exe using existing backend functionality
                        from jackify.backend.handlers.modlist_handler import ModlistHandler  
                        
                        # Initialize modlist handler with empty config dict to use default initialization
                        modlist_handler = ModlistHandler({})
                        discovered_modlists = modlist_handler.discover_executable_shortcuts("ModOrganizer.exe")
                        
                        # Convert to shortcut_handler format for UI compatibility
                        shortcuts = []
                        for modlist in discovered_modlists:
                            # Convert discovered modlist format to shortcut format
                            shortcut = {
                                'AppName': modlist.get('name', 'Unknown'),
                                'AppID': modlist.get('appid', ''),
                                'StartDir': modlist.get('path', ''),
                                'Exe': f"{modlist.get('path', '')}/ModOrganizer.exe"
                            }
                            shortcuts.append(shortcut)
                        
                        # Restore stderr before emitting signal
                        sys.stderr = old_stderr
                        self.finished_signal.emit(shortcuts)
                    except Exception as inner_e:
                        # Restore stderr before emitting error
                        sys.stderr = old_stderr
                        error_msg = str(inner_e)
                        self.error_signal.emit(error_msg)
                        self.finished_signal.emit([])
                except Exception as e:
                    # Fallback error handling
                    error_msg = str(e)
                    self.error_signal.emit(error_msg)
                    self.finished_signal.emit([])
        
        # Show loading state in dropdown
        if hasattr(self, 'shortcut_combo'):
            self.shortcut_combo.clear()
            self.shortcut_combo.addItem("Loading modlists...")
            self.shortcut_combo.setEnabled(False)
        
        # Clean up any existing thread: disconnect its signal so results are ignored,
        # terminate it, and park it in a holding list so the QThread object is not
        # GC'd while still running (which would cause Qt to abort).
        if self._shortcut_loader is not None:
            if self._shortcut_loader.isRunning():
                if hasattr(self, '_park_thread'):
                    self._park_thread(self._shortcut_loader, ["finished_signal", "error_signal"])
                else:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        try:
                            self._shortcut_loader.finished_signal.disconnect()
                        except Exception:
                            pass
                        try:
                            self._shortcut_loader.error_signal.disconnect()
                        except Exception:
                            pass
                    if not hasattr(self, '_old_loaders'):
                        self._old_loaders = []
                    self._old_loaders.append(self._shortcut_loader)
            self._shortcut_loader = None

        # Purge finished threads from the holding list
        if hasattr(self, '_old_loaders'):
            self._old_loaders = [t for t in self._old_loaders if t.isRunning()]

        # Start background thread
        self._shortcut_loader = ShortcutLoaderThread()
        self._shortcut_loader.finished_signal.connect(self._on_shortcuts_loaded)
        self._shortcut_loader.error_signal.connect(self._on_shortcuts_error)
        self._shortcut_loader.start()

    def _on_shortcuts_loaded(self, shortcuts):
        """Update UI when shortcuts are loaded"""
        self.mo2_shortcuts = shortcuts

        if hasattr(self, 'shortcut_combo'):
            self.shortcut_combo.clear()
            self.shortcut_combo.setEnabled(True)
            self.shortcut_combo.addItem("Please Select...")
            self.shortcut_map.clear()

            for shortcut in self.mo2_shortcuts:
                display = f"{shortcut.get('AppName', shortcut.get('appname', 'Unknown'))} ({shortcut.get('StartDir', shortcut.get('startdir', ''))})"
                self.shortcut_combo.addItem(display)
                self.shortcut_map.append(shortcut)

    def _on_shortcuts_error(self, error_msg):
        """Handle errors from shortcut loading thread"""
        # Log error from main thread (safe to write to stderr here)
        logger.debug(f"Warning: Failed to load shortcuts: {error_msg}")
        # Update UI to show error state
        if hasattr(self, 'shortcut_combo'):
            self.shortcut_combo.clear()
            self.shortcut_combo.setEnabled(True)
            self.shortcut_combo.addItem("Error loading modlists - please try again")
