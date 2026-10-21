---
hide:
  - navigation
  - toc
---

<div class="gt-hero" markdown>

# Nothing stays buried.

## Every dependency leaves a trail.

Understand the SQL, SAS and dbt pipelines in front of you. Follow a table’s dependencies
all the way back to the original statements, in a workspace that keeps your source local.

[Build your first lineage](getting-started/quick-start.md){ .md-button .md-button--primary }
[Explore the guides](user-guide/index.md){ .md-button }

Local storage. No LLM required. Imported code is never executed.
{ .gt-local }

</div>

## dbt projects, models and macro impact

Import multiple models, property YAML, sources, seeds, snapshots and supplied package
code together. Follow logical model dependencies across versions and schemas, inspect
macro consumers, and trace supported SQL column expressions. Already-generated dbt
manifests can supply declared dependencies and compiled SQL with exact JSON evidence.

dbt uses local static analysis: templates, Python and dbt commands are never executed.
Dynamic macros retain partial coverage; Python and semantic resources have explicit
dependency/metadata limits.

[Explore dbt support and limits](DBT_SUPPORT.md){ .md-button }

<figure class="gt-product" markdown>

![GraveTrail’s redesigned Lineage workspace with grouped navigation and the supplied SQL project](assets/images/gravetrail-lineage-explorer.png)

<figcaption>A real SQL project. Original source behind every established relationship.</figcaption>
</figure>

## Local analysis first. AI when you choose.

**The local parser is the primary, default option.** Generate table lineage,
column usage and supported transformations without giving source to an AI provider.
No model connection, API key or AI token usage is needed. Leave **Use AI for
analysis** unchecked in **Analysis → Run**.

For large or complex systems where you want additional coverage, optional
**AI + parser (hybrid)** analysis compares locally established facts with
source-backed AI proposals. It sends selected source and relevant context to your
configured provider, subject to your privacy controls. A local gateway may forward
that source upstream. Large projects can also use local parsing alone.

Both workflows are built in. AI can help investigate gaps; it does not guarantee
complete or universally correct lineage. Review evidence, omissions and unresolved
coverage before relying on the results.

[Compare the analysis options](AI_ANALYSIS.md){ .md-button }

## Begin with the question in front of you

<div class="gt-questions" markdown>
<div markdown>

### Where does this table come from?

Follow upstream dependencies across persistent tables and temporary stages. Open a
relationship to inspect the original statement and line range.

[Explore lineage and evidence](user-guide/index.md)

</div>
<div markdown>

### What depends on this change?

Trace downstream impact, inspect direct column usage, and search related source.
Follow output expressions in the separate [Transformation lineage view](TRANSFORMATION_LINEAGE.md),
with original evidence and explicit SQL/SAS coverage boundaries.
Export an offline graph or a report to share your findings.

[Investigate your project](USER_GUIDE.md)

</div>
<div markdown>

### How can my tools use the evidence?

Query stored analysis through the CLI or MCP with explicit permissions, freshness
metadata and bounded responses. Optional AI stays behind your privacy controls.

[Connect your tools](integrations/index.md)

</div>
</div>

<div class="gt-start" markdown>
<div markdown>

## A useful first run, on your machine.

Install from source with Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Try an included SQL or SAS project, then trace `pub.all_kpis` through seven dependency layers.

[Follow the walkthrough](getting-started/quick-start.md)

</div>
<div markdown>

```sh
git clone https://github.com/SahasilAK/GraveTrail.git
cd GraveTrail
uv sync --locked --extra dev
uv run gravetrail-ui
```

Using pip, Docker or a native bundle? Read the [installation reference](SETUP_AND_DEPLOYMENT.md)
for supported workflows and verification limits.

</div>
</div>

## A place for every part of your work

Import in **Sources**, run **Analysis**, then investigate in **Lineage**, **Columns**
or **Engineering tools**. Workspace preferences, AI connections, data management and
automation each have a focused destination.

<div class="gt-guides" markdown>

[Getting started](getting-started/index.md)
[Workspace and UI reference](USER_GUIDE.md)
[Architecture and parsing coverage](architecture/overview.md)
[Integrations and privacy](integrations/index.md)
[Deployment and recovery](deployment/index.md)
[Development and testing](development/index.md)
[Troubleshooting](troubleshooting/help.md)
[Contributing](development/contributing.md)

</div>

!!! info "Follow the evidence, including its limits"
    GraveTrail performs static analysis. Unsupported syntax, dynamic macros and ambiguous
    identities remain diagnostic boundaries. Optional project AI facts remain inferred
    after local validation and publication; manual assistance uses a separate explicit merge. Read the [SQL](SQL_PARSING.md) and
    [SAS](SAS_PARSING.md) coverage before drawing conclusions from missing edges.
