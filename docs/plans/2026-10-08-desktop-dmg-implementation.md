# macOS DMG Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship a self-contained native macOS application as Apple Silicon and Intel DMGs without requiring Python.

**Architecture:** A Swift AppKit/WKWebView shell runs the existing bundled localhost server. The server selects an ephemeral port and writes its URL atomically; the shell loads it, manages native interactions, and owns the server lifetime. SQLite lives in Application Support outside the app.

**Tech Stack:** Swift, AppKit, WebKit, Python, SQLite, PyInstaller, hdiutil, GitHub Actions.

---

### Task 1: Desktop server lifecycle

Files: modify `app.py`; extend `tests/test_runtime.py` on dev.

1. Add integration tests which launch the real server with `SOCIOMETRY_PORT=0` and `SOCIOMETRY_READY_FILE=<temporary path>`, wait for JSON, assert a real nonzero localhost URL, create a synthetic study, then restart using the same DB and verify persistence. Add a parent-lifetime test using an invalid `SOCIOMETRY_PARENT_PID` and asserting a clean exit.
2. Run `/Users/daniilserki/.cache/opensociometry-desktop-venv/bin/python -m unittest discover -s tests -p test_runtime.py -v`; observe missing readiness/parent behavior.
3. After binding, atomically write `{"url": url, "pid": os.getpid()}` to the requested path. Start a daemon thread watching `os.getppid()` when a parent PID is supplied; call `server.shutdown()` when it changes. Close the server in `finally`. Existing non-desktop defaults remain compatible.
4. Re-run runtime tests, then all Python tests. Commit lifecycle changes.

### Task 2: Native macOS shell

Files: create `macos/OpenSociometry.swift`; test through compilation and the actual window.

1. Compile the requested source before it exists to demonstrate the missing native app.
2. Implement an AppKit delegate, native menu, window and WKWebView. Start `Contents/Resources/server/OpenSociometry` with DB in Application Support, port 0, readiness file, no browser, and parent PID. Poll startup for at most 45 seconds, surface failure with a log path, clean startup files, and stop the process on application termination.
3. Implement file inputs, JS alert/confirm, new-window external URLs, navigation download handling through WKDownload + NSSavePanel, and Blob exports via a WKScriptMessageHandler bridge. Intercept `window.print()` for native printing. Preserve current page navigation and locally stored settings.
4. Compile with `xcrun swiftc -O -target arm64-apple-macos14.0 macos/OpenSociometry.swift -o /tmp/OpenSociometry-shell -framework AppKit -framework WebKit`. Verify real app launch and synthetic import/export flows once bundled.
5. Commit the shell after compilation and manual smoke verification.

### Task 3: Package and release

Files: modify `.github/build_release.py`, `.github/workflows/build-bundles.yml`, `.gitignore`, `README.md`, and the in-app help text if its data-path guidance needs updating.

1. Add `--build-only` for local verification and use release `v0.2.0` consistently. Keep the Windows ZIP; create macOS DMGs containing `.app` and an Applications shortcut. Bundle the compiled shell, server and generated icon, create Info.plist, and ad hoc sign the complete app.
2. Extend bundled smoke verification to run on an ephemeral port via readiness JSON, use a temporary database, import the public synthetic Excel template, verify persistence and a 300 DPI chart. Never copy source data directories or private files into staging.
3. Build locally using `.github/build_release.py --slug macos-arm64 --build-only`, verify `codesign --verify --deep --strict`, attach DMG read-only, inspect contents, run it with an isolated DB, exercise UI upload, both chart downloads and print/PDF, then detach.
4. Update installation instructions, Gatekeeper limitation, data folder and migration guidance. Ignore generated DMGs and local app artifacts.
5. Run Python tests, Node PNG tests, syntax checks and diff checks. Review the feature, merge production files only to main, all work to dev, tag v0.2.0 and publish the GitHub release. Let CI build arm64, Intel and Windows, inspect job outputs and release assets before declaring completion.
