# .streamlit/

Local server and visual theme configuration; no credentials belong here.

## Files
- `config.toml` — Loopback/headless server defaults, upload/telemetry settings and active native theme. Settings preset picker updates its theme colors/base atomically; app-wide, independent of workspaces.

Native layout uses local system-ui at 16px, a 2.5rem primary heading, deliberate heading/metric weights and .75rem surfaces. Ocean dark is the shipped default; Ocean dark and Ink dark retain their exact native definitions. Nine additional palettes define sidebar and panel colors separately. The app uses theme-derived presentation.py/style.css for scoped chrome and accessibility feedback.
