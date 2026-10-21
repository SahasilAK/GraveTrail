# dbt fixture/

`gold.json` contains reviewed expected logical pairs, outside import inputs.
`input/` is synthetic retail: project config, sources/properties, SQL models
(ephemeral/incremental/versioned/multiple schemas), Python, seeds, nested macros,
SQL/YAML snapshots, docs, tests/unit fixtures, exposure and semantic declarations.
Distributable copy: tests/sample_data/gravetrail_dbt_lineage_test_project.zip.
No credentials/profiles/client data. Edge-case variants live in test_dbt_*.py.
