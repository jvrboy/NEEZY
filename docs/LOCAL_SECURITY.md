# NEEZY Local Security Policy & Hardening Guidelines

## Core Principles

1. **Local Desktop Only**: No cloud user accounts, no remote database connections, no multi-tenant server infrastructure.
2. **Zero Involuntary Telemetry**: All data remains local inside `NEEZY_HOME` (`~/.config/neezy` or specified override).
3. **Bring-Your-Own-Key Confidentiality**: Provider API keys are stored in `ai-keys.json` with POSIX `0600` owner-only permissions. Keys are never printed in full, logged, or sent anywhere except directly to the designated user-selected AI provider over HTTPS.

---

## Security Controls

### Path Traversal Protection
The `sanitize_path` helper in `neezy_backend/storage.py` resolves and validates all user-supplied file paths against `get_data_dir()`. Any attempt to access files outside the sandboxed application directory via relative paths (`../`) is blocked with a `ValueError`.

### Backup & Restore Safety
Backup zip archives created by `create_local_backup` and restored by `restore_local_backup` sanitize every zip member filename to eliminate Zip Slip vulnerabilities.

### Tool Permission Tiers
Agent backend tools in `neezy_backend/tools.py` carry explicit permission levels (`READ_ONLY`, `WRITE`, `DESTRUCTIVE`). Destructive tools require user confirmation or automated snapshot backups prior to execution.
