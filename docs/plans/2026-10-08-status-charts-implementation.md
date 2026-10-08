# Status Charts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show a flat, switchable status distribution chart in the results UI, with local Plotly and Matplotlib renderers and print-quality export.

**Architecture:** Use the existing `compute()` report as the sole source of category counts. Bundle Plotly.js for offline browser rendering. Add a local API route that renders the same counts with Matplotlib Agg to a 300 DPI PNG. The browser has one active renderer, shared category details, and separate exports.

**Tech Stack:** Python stdlib HTTP server, Matplotlib Agg, local Plotly.js, vanilla JavaScript/CSS, unittest, PyInstaller.

---

### Task 1: Matplotlib image endpoint

**Files:** `tests/test_status_chart.py`, `app.py`, `requirements.txt`

1. Add a synthetic study test for a 300 DPI PNG response, including PNG metadata and a study with zero participants.
2. Run `python -m unittest tests.test_status_chart -v`; confirm it fails because the endpoint is missing.
3. Add an Agg renderer using category counts from `compute()`, with a flat doughnut, labels, legend, and `savefig(dpi=300)`; expose `GET /api/criteria/{id}/status-chart.png`.
4. Run the test and all Python tests; confirm passes. Commit the focused change.

### Task 2: Browser renderer and UI

**Files:** `static/app.js`, `static/style.css`, `static/index.html`, `static/vendor/plotly.min.js`, `static/vendor/PLOTLY-LICENSE.txt`, `tests/test_status_chart_ui.py`

1. Add a browser smoke assertion against a synthetic report: two checkbox controls, Plotly selected by default, Plotly and Matplotlib views mutually exclusive, category details, download controls.
2. Confirm the smoke check fails on current results UI.
3. Bundle a pinned Plotly.js distribution and license under `static/vendor/`; load it locally only. Add the chart panel after status summary, default Plotly, local renderer selection, category names/counts/percentages and participant list. Export Plotly SVG and 2400×1800 PNG; display the Matplotlib image and offer its 300 DPI PNG.
4. Run the browser smoke and Python tests; confirm passes. Commit the focused change.

### Task 3: Portable packages and documentation

**Files:** `.github/build_release.py`, `.github/workflows/build-bundles.yml`, `README.md`, `tests/test_runtime.py`

1. Add a failing bundle smoke check for the chart endpoint and Plotly asset.
2. Confirm failure, then install Matplotlib in CI and include all needed resources in PyInstaller. Update source dependency instructions and version references for a new release.
3. Run tests, compile checks, local smoke, and (where possible) a local bundle build. Inspect `git status` for personal data and unwanted files.
4. Commit on `dev`, merge only production files to `main`, tag a new release, and verify cross-platform CI assets. Keep tests/docs on `dev` only.
