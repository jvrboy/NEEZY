# Releasing NEEZY

This is the runbook for cutting a release. Follow it top to bottom; every
step exists because skipping it once cost an afternoon.

## 1. Before you tag

- [ ] `main` is green: both "Python CI" and "Release builds" workflows pass
      on the head commit.
- [ ] `python local_ci.py` passes locally (compile, lint, format, tests).
- [ ] `CHANGELOG.md` has a section for the new version with a date.
- [ ] `neezy_backend/__init__.py` `__version__` and `pyproject.toml`
      `version` match the version you are about to tag.

## 2. Version bump

1. Update `pyproject.toml` `[project] version`.
2. Update `neezy_backend/__init__.py` `__version__` to the same value.
3. Commit: `chore(release): bump version to X.Y.Z`.

## 3. Tag and build

```sh
git tag -a vX.Y.Z -m "NEEZY X.Y.Z"
git push origin main vX.Y.Z
```

Tagging (and manual dispatch) triggers the **Release builds** workflow:
- Windows EXE (PyInstaller onefile) — smoke-started before upload.
- Android APK (Buildozer) — per-ABI splits if configured in
  `packaging/android/buildozer.spec`.

Artifacts land on the GitHub Release with the changelog section as the
release notes (extracted automatically).

## 4. Verify the artifacts

- [ ] Download the EXE and APK from the release page on a clean machine.
- [ ] `NEEZY.exe --version` matches the tag (console build) and the window
      title/About show the same version.
- [ ] The APK installs and reaches the signals screen on a device/emulator.
- [ ] Checksums in `SHA256SUMS` match a local `sha256sum`.

## 5. After the release

- Move the changelog section from "Unreleased" to the version heading if it
  is not already there.
- Announce in the channels you use; link the release, not the tags page.

## Rollback

Bad build? Delete the release and tag, fix on main, re-tag. The workflow
key on artifacts means a re-run rebuilds from scratch; there is no partial
state to clean up.
