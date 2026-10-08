# Status charts design

Approved on 2026-10-08. The results page shows a flat status distribution chart immediately after the existing status summary. Plotly is selected by default. Two checkbox controls act as a mutually exclusive renderer selector. The choice persists in local browser storage. Both views use the six existing status categories, colors, counts, and percentages from the current report; no new personal data is stored or sent outside the local app.

Plotly.js is bundled as a local static asset and renders an interactive two-dimensional doughnut. Matplotlib uses the Agg backend on the local Python server to return a PNG generated at 300 DPI. The chart is visually consistent across renderers, with a category list and participant names available in the same UI. Empty categories remain in the legend but do not create zero-size slices. Empty groups display a clear message.

The Matplotlib chart downloads as a 300 DPI PNG. The Plotly chart downloads as SVG and as a 2400 × 1800 PNG, suitable for an 8 × 6 inch print at 300 pixels per inch. All assets are local. The portable Windows and macOS builds install Matplotlib during packaging. Source users install dependencies from `requirements.txt` for the Matplotlib view.

Tests use synthetic participants. Verify category counts, chart response MIME and PNG resolution metadata, empty group behavior, mutual exclusivity, offline Plotly loading, and packaged build smoke checks. `docs/` and `tests/` remain on `dev`; production code only is merged to `main`.
