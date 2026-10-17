# Publish the documentation with GitHub Pages

This repository builds its Markdown documentation with Material for MkDocs. GitHub
Actions validates the site on pull requests and deploys the static output from `main`.
GitHub Pages does not run the Streamlit application, Python services, or your workspaces.

## Prerequisites

- A GitHub repository with Pages available on its plan. Public repositories can use Pages
  with GitHub Free; private repositories require a plan supporting Pages. Check your
  organization's policy before publishing private repository documentation.
- Repository admin or maintainer access to configure Pages, and permission to run Actions.
- GitHub Actions enabled, with the actions in `.github/workflows/docs.yml` allowed by
  repository/organization policy. No personal access token or deployment secret is needed.
- For local authoring: Git, Python 3.11+, and [uv](https://docs.astral.sh/uv/getting-started/installation/).

The checked-in repository is `SahasilAK/dataforge-engineering-hub`, with default branch
`main`. For a fork, change `repo_url`, `repo_name`, `site_url`, and `edit_uri` in
`mkdocs.yml`; update workflow branch guards if your default branch differs.

## Preview locally

From the repository root, in PowerShell, Bash, or zsh:

```sh
uv sync --locked --group docs
uv run --group docs mkdocs serve --dev-addr 127.0.0.1:8000
```

Open the URL printed by MkDocs. With the configured project site it normally includes
`/dataforge-engineering-hub/`. Keep the terminal running; changes reload automatically.
Stop with Ctrl+C. Documentation dependencies are a separate locked dependency group,
not part of the application's production requirements.

For a docs-only environment (as used in CI):

```sh
uv sync --locked --only-group docs
uv run --no-sync mkdocs serve --dev-addr 127.0.0.1:8000
```

`--only-group docs` removes application/test dependencies from that environment. Use
`uv sync --locked --group docs --extra dev` to restore a combined development environment.

## Build and validate

```sh
uv run --group docs python scripts/docs/build.py
```

This runs `mkdocs build --strict --clean`, then checks generated links, anchors, images,
CSS resources, project-site prefixes, search entries and the complete output inventory.
The output is `site/`, already ignored by Git. For individual checks:

```sh
uv run --group docs mkdocs build --strict
uv run --group docs python -m scripts.docs.validate
```

Only Markdown pages explicitly listed in `mkdocs.yml` navigation and individually named
`extra.public_assets` are accepted by the publication hook. Theme assets and generated
search/sitemap files are checked separately. Prompts, plans, knowledge maps, review reports,
databases, credentials and imported originals are excluded. The workflow uploads **only
`site/` after validation succeeds**, never the repository or `docs/` directory.

## Enable Pages and publish

1. Review and merge the documentation pull request into **`main`**. PR builds validate
   without deploying; running the workflow on a feature branch also cannot deploy.
2. Open [repository Settings → Pages](https://github.com/SahasilAK/dataforge-engineering-hub/settings/pages).
3. Under **Build and deployment → Source**, select **GitHub Actions**. There is no
   `gh-pages` branch to create and no `/docs` publishing folder to select.
4. Open [Actions → documentation](https://github.com/SahasilAK/dataforge-engineering-hub/actions/workflows/docs.yml).
   Choose **Run workflow**, select **`main`**, and click **Run workflow**. This is useful
   if the merge-triggered run occurred before Pages was enabled.
5. Verify both **build** and **deploy** jobs succeed. The **github-pages** environment
   links to the deployment URL. Settings → Pages also shows **Visit site** once published.
6. Open the URL returned by that deployment. With this repository's current configuration,
   the expected address is:

   **`https://sahasilak.github.io/dataforge-engineering-hub/`**

That address is derived from the Git remote and configured project prefix; its appearance
here is not evidence that a deployment has happened. The successful deployment output
and **Visit site** link are authoritative, especially after a rename or custom domain.

The deployment job uses the `github-pages` environment and only grants `pages: write`
and `id-token: write`. If environment protection requires review, approve that deployment
in Actions. Restrict the environment's deployment branches to `main` in
**Settings → Environments → github-pages** when configuring repository policy.

## How future updates work

Pull requests always run the strict build and publication inspection. Relevant pushes
to `main` build and deploy automatically. Changes to docs, README, tooling, lock/config
or this workflow trigger deployment; manual dispatch on `main` also works. Application
CI remains in the existing `tests.yml` workflow.

There is one concurrent documentation run per branch/PR. A newer run cancels an older
one for that branch. Only trusted `main` runs can upload the Pages artifact and deploy;
PR validation has `contents: read` and receives no deployment secrets or write grants.

The workflow pins Node.js 24-compatible releases of official `actions/configure-pages@v6`,
`actions/upload-pages-artifact@v5`, and `actions/deploy-pages@v5` to commit SHAs, following
[GitHub's custom workflow guidance](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
Dependencies are installed from `uv.lock` with `--locked --only-group docs`.
Linux jobs use `ubuntu-24.04` explicitly so the `ubuntu-latest` migration to Ubuntu 26.04
does not change their operating system automatically.

## Optional custom domain

Keep the default address unless you own a domain and want to configure DNS.

1. Follow [GitHub's domain verification and DNS instructions](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site).
2. In **Settings → Pages → Custom domain**, enter the domain and complete DNS validation.
   Enable **Enforce HTTPS** when certificate provisioning allows it.
3. Change `site_url` in `mkdocs.yml` to the exact HTTPS domain and path. A domain-root
   site normally uses `/`; the project-site URL uses `/dataforge-engineering-hub/`.
4. Rebuild, validate, and merge. Run **documentation** on `main`, then use **Visit site**
   to verify CSS, images, search, and nested links at the new address.

This artifact-based workflow does not use a `CNAME` file to configure Pages. Configure
the domain in repository settings. Never add DNS tokens or private keys to the site.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Configure Pages says site not found | Enable **Settings → Pages → Source → GitHub Actions**, then rerun on `main`. |
| Workflow is missing | Merge `.github/workflows/docs.yml` into the default branch; confirm Actions is enabled. |
| Manual run builds but skips deployment | Select `main`. Feature branches and PR events intentionally cannot deploy. |
| Action is blocked or permission denied | Repository/organization Actions policy must allow the named actions. Deploy needs Pages/OIDC write permissions and the `github-pages` environment. |
| Waiting for approval | Inspect `github-pages` environment protection and deployment branch rules. |
| `mkdocs` or `material` cannot be found | Install `uv sync --locked --group docs`; use the `uv run --group docs` commands from the repository root. |
| Strict build fails | Read the first warning/error. Check the nav source exists, its links/anchors match headings, and images are named in `public_assets`. |
| Publication validation fails | Remove unexpected output, fix broken links, or explicitly register an intended public page/asset. Do not disable the boundary. |
| Missing `github-pages` artifact | Build must pass and upload must run in the same workflow run; deploy depends on build. PR runs intentionally do not upload. |
| Site returns 404 | Wait for a successful deployment; use the exact deployment URL including the repository prefix and trailing slash. Check Pages source/environment. |
| Nested pages, CSS, JS or images fail | Verify `site_url` and relative links. Do not hardcode `/assets/...` for a project site; rebuild after a rename/domain change. |
| Search has old content | Confirm the latest `main` deployment succeeded, then hard-refresh. The search index comes from the validated build. |
| Wrong published URL | Use the deploy job's environment URL or **Settings → Pages → Visit site**, not a guessed fork/custom-domain address. |

For application installation/runtime problems, see [troubleshooting](../troubleshooting/help.md).
For adding pages and updating dependencies, see [documentation maintenance](../development/documentation.md).

## Optional repository metadata

After the site is deployed, maintainers may set the repository **About → Website** to
the verified deployment URL. Suggested description: “Local-first SQL and SAS lineage
with source evidence, direct column usage, CLI and MCP.” Suggested topics:
`data-lineage`, `data-engineering`, `sql`, `sas`, `streamlit`, `duckdb`, `mcp`.
These are recommendations; building the documentation does not change repository settings.
