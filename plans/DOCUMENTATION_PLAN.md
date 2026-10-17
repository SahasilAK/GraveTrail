# Documentation and GitHub Pages implementation plan

**Goal:** Implement `docs/prompts/FEATURE_DOCUMENTATION_AND_GITHUB_PAGES.md` without
changing the application. Work on `feature/git-pages-and-cleanups`; user explicitly
requests autonomous execution, push and a reviewable PR, with no approval pauses.

**Architecture:** Material for MkDocs with locked, separate documentation dependencies.
Curated section indexes organize existing canonical references without breaking their
GitHub paths. Navigation and an explicit asset list define the publication allowlist.
Official artifact-based Pages deployment is restricted to `main`.

**Design:** Slate blue `#244766`, ink `#172b3a`, copper `#b6532c`, pale blue `#edf4f8`,
white `#ffffff`; system sans headings/body and monospace code, no external fonts.
A branching lineage illustration is the main visual, with brief restrained motion,
keyboard focus and reduced-motion support. Documentation chrome stays familiar.

## Tasks and checks

- [x] Audit implemented features/launchers/CLI/MCP/builds/license and canonical guides.
- [x] Rewrite README and create organized onboarding, user, integration, deployment,
  architecture, development and troubleshooting entry points. Preserve detailed references.
- [x] Add branded homepage, SVG assets, responsive light/dark styling and search.
- [x] Add failing publication-boundary/link tests, then implement MkDocs allowlist hook,
  build and output validation. Missing pages/assets, secret/runtime files, symlinks,
  broken fragments and incorrect project prefixes must fail.
- [x] Add PR validation and `main`-only deployment via configure-pages v5,
  upload-pages-artifact v4 and deploy-pages v4. PR jobs have read-only permissions;
  deploy job alone receives Pages/OIDC write. Install from `uv.lock`.
- [x] Document local preview/build, Pages activation, domain setup, troubleshooting,
  maintenance and repository metadata recommendations. Add contribution/security/templates.
- [x] Verify strict build, internal links/fragments/assets, publication inventory,
  fresh application pytest/Ruff, actual UI and docs browser (desktop/mobile/search/theme).
- [x] Review final diff, update status/knowledge, commit, push and create/attach PR.

## Rulings

- Preserve uppercase reference paths: required by the original master specification and
  existing README/agent links. New section indexes and MkDocs navigation provide hierarchy
  without copying or retiring valuable guides.
- Publish only navigation documents and named assets: prompts/plans/knowledge maps,
  review reports and runtime files must never enter HTML/search/static artifacts.
- Use hand-authored SVG branding/lineage imagery; any application screenshots must be
  captured from a real isolated running instance, never fabricated.
- Do not enable Pages or merge the PR on the user's behalf; deliver exact activation
  instructions after review. The expected URL is not a verified deployment.

Delivery: PR [#3](https://github.com/SahasilAK/dataforge-engineering-hub/pull/3), targeting main. Pages activation stays a maintainer step after review.
