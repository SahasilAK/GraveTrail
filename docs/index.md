---
hide:
  - navigation
  - toc
---

<div class="gt-hero" markdown>

# Nothing stays buried.

## Every dependency leaves a trail. { .gt-tagline }

<!-- Compatibility anchors for sections now linked from this page. -->
<span id="understand-your-datas-trail"></span>
<span id="nothing-stays-buried-every-dependency-leaves-a-trail"></span>
<span id="dbt-projects-models-and-macro-impact"></span>
<span id="how-can-my-tools-use-the-evidence"></span>


GraveTrail helps data engineers, analysts and architects understand SQL, SAS and
dbt projects. Turn source code and supported project artifacts into explorable
lineage, dependency relationships and the source evidence behind them.

[Build your first lineage](getting-started/quick-start.md){ .md-button .md-button--primary }
[Explore a live example](examples/interactive-lineage.md){ .md-button }

Local static analysis. No AI account required. Imported code is never executed.
{ .gt-local }

</div>

<figure class="gt-product" markdown>

![Current GraveTrail Lineage view tracing the safe SQL fixture upstream](assets/images/gravetrail-lineage-explorer.png)

<figcaption>Follow the dependencies. Open the evidence. Decide where to investigate next.</figcaption>
</figure>

## Begin with the question in front of you

<div class="gt-questions" markdown>
<div markdown>

### Where does this table come from?

Explore inputs across persistent tables and supported temporary steps. Open the
original statement and line range to understand the relationship.

[Explore lineage and evidence](user-guide/explore.md)

</div>
<div markdown>

### What depends on this change?

Follow consumers, direct column usage and supported transformations. Use findings
to plan a migration or review a change, then verify against runtime behavior.

[Investigate columns and impact](user-guide/columns.md)

</div>
<div markdown>

### What is hiding in this dbt project?

Inspect models, versions, sources and macro consumers. Supplied manifests can add
declared dependencies and compiled SQL evidence without executing dbt.

[Follow the dbt tutorial](examples/dbt.md)

</div>
</div>

## Local analysis first. AI when you choose.

Static analysis runs locally after installation without an API key, AI account
or paid model service. Large projects can use it too. Unsupported syntax and
runtime-dependent behavior remain visible coverage boundaries.

Optional AI **independently extracts** inferred lineage from selected files. It
sends source and authorized context to the configured provider. A locally addressed
gateway can forward requests upstream. AI does not guarantee complete or correct lineage.

[Understand analysis and disclosure](concepts/local-and-ai.md){ .md-button }
[Configure optional AI](AI_ANALYSIS.md){ .md-button }

## Choose your project

| Project | Start with | Know the boundary |
| --- | --- | --- |
| SQL | [SQL workflow](project-types/sql.md) | Dialect-specific syntax, dynamic SQL and unknown schema |
| SAS | [SAS workflow](project-types/sas.md) | Bounded DATA/PROC SQL and known-value macros; no execution |
| dbt | [dbt workflow](project-types/dbt.md) | Source/enriched/artifact modes; no Jinja, package download or warehouse execution |

## A useful first run, on your machine.

These guides describe development commit **1864dc8**. dbt and the current AI pipeline
postdate release v0.0.1. Use [the pinned installation](getting-started/installation.md)
to reproduce the examples rather than assuming an older binary has the same controls.

1. [Install and launch](getting-started/installation.md).
2. [Import a SQL sample and build static lineage](getting-started/quick-start.md).
3. [Inspect evidence](user-guide/evidence.md) and [review coverage](concepts/evidence-and-coverage.md).
4. [Export and reopen findings](user-guide/exports.md).

## A place for every part of your work

<nav class="gt-guides" aria-label="Documentation sections">
  <a class="gt-guide-card" href="getting-started/">
    <span class="gt-guide-title">Getting started</span>
    <span class="gt-guide-description">Install GraveTrail and trace your first project.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="user-guide/">
    <span class="gt-guide-title">User guides</span>
    <span class="gt-guide-description">Explore lineage, inspect evidence and export findings.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="concepts/">
    <span class="gt-guide-title">Concepts and limits</span>
    <span class="gt-guide-description">Understand evidence, coverage and analysis boundaries.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="examples/">
    <span class="gt-guide-title">Examples</span>
    <span class="gt-guide-description">Follow practical SQL, SAS and dbt walkthroughs.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="integrations/">
    <span class="gt-guide-title">CLI and MCP</span>
    <span class="gt-guide-description">Connect your tools and automate lineage workflows.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="development/">
    <span class="gt-guide-title">Developer documentation</span>
    <span class="gt-guide-description">Walk through the code, architecture and extension points.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="deployment/">
    <span class="gt-guide-title">Deployment and recovery</span>
    <span class="gt-guide-description">Set up your environment and recover project data.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
  <a class="gt-guide-card" href="troubleshooting/help/">
    <span class="gt-guide-title">Troubleshooting</span>
    <span class="gt-guide-description">Find answers by symptom and get back to work.</span>
    <span class="gt-guide-arrow" aria-hidden="true">→</span>
  </a>
</nav>

!!! info "Follow the evidence, including its limits"
    A graph describes established analysis relationships, not observed warehouse
    execution. Missing edges can mean missing coverage. Installation, optional AI,
    local static analysis and HTML exports have different [network boundaries](concepts/local-and-ai.md).
