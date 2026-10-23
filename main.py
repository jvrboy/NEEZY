"""NSSM-friendly entry point for NEEZY's lightweight PC executor."""

from neezy_backend.executor_service import main

if __name__ == "__main__":
    raise SystemExit(main())
