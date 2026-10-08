# macOS desktop application design

Approved by the user on 2026-10-08. Deliver OpenSociometry as a macOS application in a DMG, with a separate native window and no Python installation. Keep the existing HTML/CSS/JavaScript UI. Release Apple Silicon and Intel images; retain the Windows portable package. Personal data and local databases must never enter Git or release assets. Tests and planning documents stay on dev; main contains production files only.

The macOS application is a small Swift AppKit/WKWebView shell. It launches the PyInstaller server bundled in Contents/Resources, requests an OS-assigned localhost port, and reads an atomic startup file containing the actual URL. It opens that URL in a persistent WKWebView store. The server watches its parent and stops if the shell exits unexpectedly; normal application termination also stops it. Startup failures display a readable dialog and a local log location.

The default database is ~/Library/Application Support/OpenSociometry/sociometry.db. It is outside the application and DMG, so replacing the application preserves studies. An explicit SOCIOMETRY_DB override is available for isolated verification. Existing portable data can be transferred through the current JSON backup/restore UI. A native menu opens the data folder.

The shell supports the existing file input, JavaScript confirmation dialogs, HTTP downloads, Blob/data URL downloads from chart exports, and print/PDF. Downloads use a native save dialog. External links open in the system browser. The app has the existing logo as its Dock icon and standard macOS edit/window/quit menus.

The build generates a self-contained .app, signs it ad hoc, and puts it in a compressed DMG with an Applications shortcut. No Developer ID identity is currently installed, so the initial distribution is not notarized and may require approval in macOS Privacy & Security. Do not imply that it is notarized. Document installation and the separate desktop data path.

Verify ephemeral-port startup, readiness handoff, parent exit, persistence, the bundled server's Excel import and 300 DPI chart output, native window interaction/downloads/printing, app signature, and a read-only mounted DMG. Use synthetic participants only. Build both macOS architectures and Windows in CI before publishing the desktop release.
