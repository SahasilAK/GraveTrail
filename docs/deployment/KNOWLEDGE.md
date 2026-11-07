# docs/deployment/

Pages defaults to Crimson Forge for first-time visitors; explicit saved theme selections persist.

- `index.md` — distinguish running the application from serving static documentation.
- `github-pages.md` — locked local preview/strict build, explicit publication inventory, PR validation versus main-only deploy, Pages activation/eligibility/domains and deployment evidence. Expected URL uses case-sensitive /GraveTrail/; a configured URL is not a deployment claim. Documentation theme comes from the shared registry.

scripts/docs/build.py first checks source-inventory freshness then builds/validates site. CI checkout fetch-depth0 retains the pinned application baseline for inventory links. Pages uploads only validated site output; it never runs Streamlit or stores user workspaces. Hosted activation/status must be checked separately.
