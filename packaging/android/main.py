"""Android entry point. Buildozer runs this file as the app's main module.

The staged build tree (see stage.py) has neezy_mobile/, neezy_backend/ and the
vendored pure-Python packages next to this file.

Any exception during startup or in a UI callback is written to
``neezy-crash.log`` in the app's private storage and shown on screen, so a
failure reports its traceback instead of closing the app silently.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Android's Python has no system CA bundle. websocket-client needs one for wss://
_CACERT = os.path.join(HERE, "certifi", "cacert.pem")
if os.path.exists(_CACERT):
    os.environ.setdefault("SSL_CERT_FILE", _CACERT)

CRASH_LOG = "neezy-crash.log"


def _log_path() -> str:
    # python-for-android sets ANDROID_PRIVATE to the app's private files dir.
    return os.path.join(os.environ.get("ANDROID_PRIVATE", HERE), CRASH_LOG)


def _record(text: str) -> None:
    # stdio is forwarded to logcat (tag "python") by python-for-android.
    sys.stderr.write(text + "\n")
    try:
        with open(_log_path(), "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        pass


def _format(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def _error_view(text: str):
    from kivy.metrics import dp
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    scroll = ScrollView(do_scroll_x=False)
    label = Label(
        text=(f"NEEZY hit an error.\nFull log: {_log_path()}\n\n{text}"),
        halign="left",
        valign="top",
        font_size="12sp",
        size_hint_y=None,
        padding=(dp(12), dp(12)),
    )
    label.bind(
        width=lambda inst, w: setattr(inst, "text_size", (w, None)),
        texture_size=lambda inst, size: setattr(inst, "height", size[1] + dp(24)),
    )
    scroll.add_widget(label)
    return scroll


def _build_failure(exc: BaseException):
    text = _format(exc)
    _record(text)
    return _error_view(text)


def main() -> None:
    from kivy.app import App
    from kivy.base import ExceptionHandler, ExceptionManager
    from kivy.core.window import Window

    try:
        from neezy_mobile.main import NeezyApp
    except Exception as exc:  # noqa: BLE001 - shown on screen, never silent
        failure = _format(exc)
        _record(failure)

        class ImportFailedApp(App):
            def build(self):
                return _error_view(failure)

        ImportFailedApp().run()
        return

    class CrashHandler(ExceptionHandler):
        """Show the first uncaught UI exception in place of the app."""

        def __init__(self) -> None:
            self.shown = False

        def handle_exception(self, exception):
            _record(_format(exception))
            if not self.shown:
                self.shown = True
                app = App.get_running_app()
                if app is not None and app.root is not None:
                    Window.remove_widget(app.root)
                    Window.add_widget(_error_view(_format(exception)))
            return ExceptionManager.PASS

    class StartupApp(NeezyApp):
        def build(self):
            try:
                return super().build()
            except Exception as exc:  # noqa: BLE001 - shown on screen
                return _build_failure(exc)

    ExceptionManager.add_handler(CrashHandler())
    StartupApp().run()


main()
