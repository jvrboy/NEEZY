"""Environment-aware command-line launcher for the Tk desktop app."""


def main() -> None:
    """Start NEEZY and explain missing platform GUI requirements clearly."""
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError as error:
        raise SystemExit(
            "NEEZY needs Tkinter. Install the operating-system Tk package "
            "(for example, python3-tk), then run the command again."
        ) from error
    from .enterprise import main as run_app

    run_app()
