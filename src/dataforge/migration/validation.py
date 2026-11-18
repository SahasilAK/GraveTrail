"""Engineer-confirmed checks and inert external evidence for an exported revision."""
import csv
import io
import math
import re
from datetime import date
from decimal import Decimal, localcontext

from dataforge.dbt.artifacts import bind_artifacts, read_artifact
from dataforge.migration.engine import NAME, digest, fingerprint, slug
from dataforge.migration.targets import warehouse

REVISION_ENV = "DBT_ENV_CUSTOM_ENV_GRAVETRAIL_REVISION"
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
COMMANDS = {"compile", "build", "run", "test"}
RESULTS = {"success", "pass", "fail", "error", "warn", "skipped", "partial success", "runtime error"}
RECONCILIATION_FIELDS = ("revision", "model", "comparison_id", "stage", "check", "column", "legacy_value",
                         "target_value", "comparison_value")
SNAPSHOT_FIELD = "input_snapshot_id"
REPLAY_STAGE = "initial_vs_repeat"
KEY_COUNTS = ("matched_keys", "missing_keys", "extra_keys")
KEYED_CHECKS = {*KEY_COUNTS, "column_mismatches"}


def approved_rules(model, values, details):
    """Validate explicit assertions against the known output and its dependencies."""
    columns = details["schemas"][model]

    def check_columns(names, layout):
        if (not isinstance(names, list) or len(names) > 32
                or any(not isinstance(name, str) or not NAME.fullmatch(name) or name not in layout for name in names)
                or len(set(names)) != len(names)):
            raise ValueError("Choose distinct, literal columns from the current output schema")
        return names

    rules = {kind: check_columns(values.get(kind, []), columns) for kind in ("not_null", "unique")}
    relation = values.get("relationship")
    if relation:
        if not isinstance(relation, dict) or set(relation) != {"column", "model", "field"}:
            raise ValueError("Choose a relationship column, parent model and parent field")
        parent = relation["model"]
        if (not isinstance(parent, str) or parent not in details["lineage"]["nodes"][model]
                or parent not in details["schemas"]):
            raise ValueError("Choose a direct upstream model for the relationship test")
        check_columns([relation["column"]], columns)
        check_columns([relation["field"]], details["schemas"][parent])
        rules["relationship"] = relation
    comparison = values.get("comparison")
    if comparison:
        fields = {"legacy", "keys", "totals", "tolerance"}
        if not isinstance(comparison, dict) or set(comparison) - {"window", "columns"} != fields:
            raise ValueError("Supply a legacy relation, comparison keys, total columns and tolerance")
        if details["model_config"][model]["materialized"] == "ephemeral":
            raise ValueError("Reconciliation needs a persisted target relation")
        legacy = comparison["legacy"]
        if not isinstance(legacy, str) or not re.fullmatch(r"[A-Za-z_]\w{0,127}(?:\.[A-Za-z_]\w{0,127}){1,2}", legacy):
            raise ValueError("Use a literal schema.table or catalog.schema.table for the legacy baseline")
        keys = check_columns(comparison["keys"], columns)
        totals = check_columns(comparison["totals"], columns)
        compared = check_columns(comparison.get("columns", []), columns)
        if compared and (not keys or set(compared) & set(keys)):
            raise ValueError("Choose comparison keys and distinct non-key value columns")
        if any(not re.match(r"(?:BIGINT|INT|SMALLINT|TINYINT|DECIMAL|DOUBLE|FLOAT)(?:\(|$)",
                            columns[name]["target_type"], re.I) for name in totals):
            raise ValueError("Comparison totals require known numeric output types")
        tolerance = comparison["tolerance"]
        if type(tolerance) not in (int, float) or not 0 <= tolerance <= 1e18 or not math.isfinite(tolerance):
            raise ValueError("Use a finite absolute tolerance of 0 to 10^18")
        rules["comparison"] = {"legacy": legacy, "keys": keys, "totals": totals, "tolerance": tolerance}
        if compared:
            rules["comparison"]["columns"] = compared
        if window := comparison.get("window"):
            if not isinstance(window, dict) or set(window) != {"column", "start", "end"}:
                raise ValueError("Supply a comparison window column, start and end")
            column, = check_columns([window["column"]], columns)
            if not columns[column]["target_type"].startswith(("DATE", "TIMESTAMP")):
                raise ValueError("A comparison window requires a known date or timestamp column")
            try:
                start, end = (date.fromisoformat(window[key]) for key in ("start", "end"))
            except (ValueError, TypeError) as exc:
                raise ValueError("Enter comparison dates as YYYY-MM-DD") from exc
            if start >= end:
                raise ValueError("The comparison end date must be after its start date")
            rules["comparison"]["window"] = {"column": column, "start": start.isoformat(), "end": end.isoformat()}
    return rules


def data_tests(model, rules, layout, active):
    """Return still-applicable, named generic dbt tests for a model."""
    tests = [(kind, column, {}) for kind in ("not_null", "unique")
             for column in rules.get(kind, []) if column in layout]
    relationship = rules.get("relationship", {})
    if relationship.get("model") in active and relationship.get("column") in layout:
        parent = relationship["model"]
        if relationship["field"] in active[parent]:
            tests.append(("relationships", relationship["column"], {"to": f"ref('{parent}')", "field": relationship["field"]}))
    return [(kind, column, "gt_" + kind + "_" + fingerprint([model, kind, column, args])[:16], args)
            for kind, column, args in tests]


def reconciliation_plan(project, revision, details):
    """Derive the exported metric definitions from the same revision used for evidence import."""
    rules = revision["settings"].get("validation_rules", {})
    catalog, schema = (project["snapshot"][field] for field in ("catalog", "schema"))
    plans = {}
    for model in sorted(details["active"]):
        confirmed = rules.get(model, {})
        comparison = confirmed.get("comparison")
        if not comparison or model in details["validation_warnings"]:
            continue
        null_columns = sorted(set(comparison["keys"] + comparison["totals"] + confirmed["not_null"]))
        config = details["model_config"][model]
        alias = config.get("alias", model)
        stages = ["initial_load", "repeat_run"] if config["materialized"] == "incremental" else ["comparison"]
        keyed_columns = sorted(set(comparison.get("columns", []) + comparison["totals"]) - set(comparison["keys"]))
        plan = {**comparison, "revision": revision["id"], "model": model,
                "target": f"{catalog}.{schema}.{alias}", "model_sha256": revision["files"][model]["hash"],
                "null_columns": null_columns, "stages": stages,
                "keyed_columns": keyed_columns if comparison["keys"] else []}
        plan["checks"] = list(dict.fromkeys(check for check, _ in _metric_keys(plan)))
        if config["materialized"] == "incremental":
            plan["replay_stage"] = REPLAY_STAGE
        plans[model] = {**plan, "comparison_id": fingerprint([project["id"], plan]), "status": "not_evaluated"}
    return plans


def _metric_keys(plan):
    return [("row_count", ""), *(("null_counts", col) for col in plan["null_columns"]),
            *([("duplicate_keys", "")] if plan["keys"] else []), *(("column_sums", col) for col in plan["totals"]),
            *((check, "") for check in KEY_COUNTS if plan["keys"]),
            *(("column_mismatches", col) for col in plan["keyed_columns"])]


def _expected_stages(plan):
    metrics = _metric_keys(plan)
    stages = dict.fromkeys(plan["stages"], metrics)
    if stage := plan.get("replay_stage"):
        stages[stage] = [metric for metric in metrics if metric[0] in KEYED_CHECKS]
    return stages


def reconciliation_template(plans):
    result = io.StringIO(newline="")
    writer = csv.writer(result)
    snapshot = (SNAPSHOT_FIELD,) if any(plan.get("replay_stage") for plan in plans.values()) else ()
    writer.writerow(RECONCILIATION_FIELDS + snapshot)
    for plan in plans.values():
        for stage, metrics in _expected_stages(plan).items():
            for check, column in metrics:
                writer.writerow((plan["revision"], plan["model"], plan["comparison_id"], stage, check, column)
                                + ("",) * (3 + len(snapshot)))
    return result.getvalue()


def _metric_value(value, *, count):
    pattern = r"[0-9]{1,20}" if count else r"-?[0-9]{1,38}(?:\.[0-9]{1,38})?"
    if not re.fullmatch(pattern, value):
        raise ValueError("Use nonnegative whole counts or finite decimal sums without separators")
    return Decimal(value)


def _stage_results(plan, stage, values):
    counts = values.get(("row_count", ""))
    matched, missing, extra = (values.get((check, "")) for check in KEY_COUNTS)
    key_integrity = [("duplicate_keys", ""), *(("null_counts", key) for key in plan["keys"])]
    bounds = {"matched_keys": min(counts), "missing_keys": counts[0], "extra_keys": counts[1]} if counts else {}
    if counts and all(values.get(check) == (0, 0) for check in key_integrity):
        if None not in (matched, missing, extra) and counts != (matched + missing, matched + extra):
            raise ValueError("Matched, missing and extra keys must account for both row counts")

    metrics = []
    left_label, right_label = ("initial", "repeat") if stage == REPLAY_STAGE else ("legacy", "target")
    for metric in _metric_keys(plan):
        check, column = metric
        item = {"stage": stage, "check": check, "column": column, "status": "not observed"}
        if metric in values:
            if check in KEYED_CHECKS:
                value = values[metric]
                bound = matched if check == "column_mismatches" else bounds.get(check)
                if bound is not None and value > bound:
                    raise ValueError("Keyed counts cannot exceed the corresponding row or matched-key count")
                passed = check == "matched_keys" or value == 0
                item["comparison"] = str(value)
            else:
                left, right = values[metric]
                if counts and check in {"duplicate_keys", "null_counts"} and (left > counts[0] or right > counts[1]):
                    raise ValueError("Null and duplicate counts cannot exceed the reported row count")
                difference = abs(left - right)
                tolerance = Decimal(str(plan["tolerance"])) if check == "column_sums" and stage != REPLAY_STAGE else Decimal(0)
                passed = left == right == 0 if metric in key_integrity else difference <= tolerance
                item.update({left_label: str(left), right_label: str(right), "difference": str(difference)})
            item["status"] = "pass" if passed else "fail"
        metrics.append(item)
    empty_sample = counts == (0, 0)
    complete = not empty_sample and len(values) == len(metrics)
    status = "fail" if any(item["status"] == "fail" for item in metrics) else "pass" if complete else "incomplete"
    return {"status": status, "complete": complete, "empty_sample": empty_sample}, metrics


def _replay_results(plan, by_stage, snapshots):
    initial_stage, repeat_stage = plan["stages"]
    initial, repeat = by_stage.get(initial_stage, {}), by_stage.get(repeat_stage, {})
    values = dict(by_stage.get(REPLAY_STAGE, {}))
    baseline_checks = [metric for metric in _metric_keys(plan) if metric[0] not in KEYED_CHECKS]
    baseline_observed = baseline_changes = 0
    for metric in baseline_checks:
        if metric in initial and metric in repeat:
            baseline_observed += 1
            baseline_changes += initial[metric][0] != repeat[metric][0]
            values[metric] = (initial[metric][1], repeat[metric][1])

    summary, checks = _stage_results(plan, REPLAY_STAGE, values)
    initial_id, repeat_id = snapshots.get(initial_stage, ""), snapshots.get(repeat_stage, "")
    snapshot_status = "not observed" if not initial_id or not repeat_id else "pass" if initial_id == repeat_id else "fail"
    baseline_status = "not observed"
    if baseline_changes:
        baseline_status = "fail"
    elif baseline_observed == len(baseline_checks):
        baseline_status = "pass"
    checks.extend([
        {"stage": REPLAY_STAGE, "check": SNAPSHOT_FIELD, "column": "", "initial": initial_id, "repeat": repeat_id,
         "status": snapshot_status},
        {"stage": REPLAY_STAGE, "check": "legacy_baseline", "column": "", "comparison": str(baseline_changes),
         "status": baseline_status},
    ])
    if not plan["keys"]:
        checks.append({"stage": REPLAY_STAGE, "check": "comparison_keys", "column": "", "status": "not observed"})
    summary["complete"] = all(item["status"] != "not observed" for item in checks) and not summary["empty_sample"]
    failed = any(item["status"] == "fail" for item in checks)
    summary["status"] = "fail" if failed else "pass" if summary["complete"] else "incomplete"
    return summary, checks


def reconciliation_summary(project, revision, details, body):
    """Score only approved metrics with supplied evidence. A partial upload cannot pass."""
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ValueError("Reconciliation results must be 16 MiB or smaller")
    plans = reconciliation_plan(project, revision, details)
    expected = {model: {stage: set(metrics) for stage, metrics in _expected_stages(plan).items()}
                for model, plan in plans.items()}
    observed = {}
    snapshots = {}
    seen = set()
    try:
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")), strict=True)
        if tuple(reader.fieldnames or ()) not in (RECONCILIATION_FIELDS, RECONCILIATION_FIELDS + (SNAPSHOT_FIELD,)):
            raise ValueError("Use the reconciliation results CSV from the handoff")
        for index, row in enumerate(reader, 1):
            if index > 50_000 or None in row or None in row.values():
                raise ValueError("Supply complete CSV rows, up to 50,000 per upload")
            model, stage, metric = row["model"], row["stage"], (row["check"], row["column"])
            plan = plans.get(model)
            if (plan is None or row["revision"] != revision["id"] or row["comparison_id"] != plan["comparison_id"]
                    or metric not in expected[model].get(stage, ())):
                raise ValueError("A result row does not match the selected revision and comparison plan")
            identity = (model, stage, metric)
            if identity in seen:
                raise ValueError("A reconciliation check appears more than once for the same model and stage")
            seen.add(identity)
            if snapshot := row.get(SNAPSHOT_FIELD, "").strip():
                if (not plan.get("replay_stage") or stage not in plan["stages"]
                        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,127}", snapshot)):
                    raise ValueError("Use a literal input snapshot ID of up to 128 characters on incremental run stages")
                existing = snapshots.setdefault(model, {}).setdefault(stage, snapshot)
                if snapshot != existing:
                    raise ValueError("Use one input snapshot ID per model and run stage")
            left, right, result = (row[field].strip() for field in ("legacy_value", "target_value", "comparison_value"))
            if not (left or right or result):
                continue
            keyed = metric[0] in KEYED_CHECKS
            if (keyed and (left or right or not result)) or (not keyed and (result or not left or not right)):
                raise ValueError("Supply comparison_value for keyed counts and both relation values for other checks")
            value = _metric_value(result, count=True) if keyed else tuple(
                _metric_value(value, count=metric[0] != "column_sums") for value in (left, right)
            )
            observed.setdefault(model, {}).setdefault(stage, {})[metric] = value
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Invalid UTF-8 reconciliation CSV") from exc
    if not observed:
        raise ValueError("Enter the result for at least one comparison check")

    models = {}
    with localcontext() as context:
        context.prec = 80
        for model, by_stage in sorted(observed.items()):
            plan = plans[model]
            stages, metrics = {}, []
            for stage in plan["stages"]:
                stages[stage], checks = _stage_results(plan, stage, by_stage.get(stage, {}))
                metrics.extend(checks)
            if stage := plan.get("replay_stage"):
                stages[stage], checks = _replay_results(plan, by_stage, snapshots.get(model, {}))
                metrics.extend(checks)
            complete = all(stage["complete"] for stage in stages.values())
            failed = any(stage["status"] == "fail" for stage in stages.values())
            models[model] = {"comparison_id": plan["comparison_id"], "legacy": plan["legacy"], "target": plan["target"],
                             "status": "fail" if failed else "pass" if complete else "incomplete",
                             "complete": complete, "stages": stages,
                             "empty_sample": any(stage["empty_sample"] for stage in stages.values()),
                             "checks": metrics}
    return {"revision": revision["id"], "models": models}


def _document(body, kind):
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ValueError("Each dbt artifact must be 16 MiB or smaller")
    try:
        document = read_artifact(None, body.decode("utf-8-sig"), node_limit=500_000, track_spans=False)
        if document.kind != kind:
            raise ValueError(f"Expected a dbt {kind} artifact")
        return document
    except (AttributeError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid dbt artifact") from exc


def import_summary(project, revision, details, manifest_bytes, results_bytes):
    """Bind observations to release identity and source code, then discard uploaded bodies."""
    manifest = _document(manifest_bytes, "manifest")
    results = _document(results_bytes, "run-results")
    try:
        return _summary(project, revision, details, manifest, results)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("Invalid dbt manifest or run results structure") from exc


def _summary(project, revision, details, manifest, results):
    target = warehouse(project["snapshot"])
    project_name = revision["plan"].get("project") or slug(project["name"])
    metadata = manifest.data["metadata"]
    run_metadata = results.data["metadata"]
    for header in (metadata, run_metadata):
        if header.get("env", {}).get("GRAVETRAIL_REVISION") != revision["id"]:
            raise ValueError("The artifacts must carry the revision printed in the handoff")
        if header.get("dbt_version") != target.core_version:
            raise ValueError("The artifact dbt version differs from the handoff profile")
    if metadata.get("project_name") != project_name or metadata.get("adapter_type") != target.dialect:
        raise ValueError("The manifest project or adapter differs from the handoff")
    command = results.data["args"]["which"]
    if command not in COMMANDS:
        raise ValueError("Upload results from dbt compile, run, build or test")
    nodes = manifest.data["nodes"]
    model_ids = {uid for uid in nodes if uid.startswith("model.")}
    expected = {f"model.{project_name}.{model}": model for model in details["active"]}
    if not model_ids or model_ids - expected.keys():
        raise ValueError("The manifest contains models outside the active handoff")
    present = {expected[uid] for uid in model_ids}
    snapshot = project["snapshot"]
    verified_tests = {}
    layouts = {model: details["schemas"].get(model, {}) for model in present}
    for uid in model_ids:
        model, node = expected[uid], nodes[uid]
        file = revision["files"][model]
        native_code = file["sql"].replace("\r\n", "\n").replace("\r", "\n").strip()
        config = details["model_config"][model]
        node_config = node["config"]
        if (node["original_file_path"].replace("\\", "/") != f"models/{model}.sql"
                or digest(node["raw_code"]) != digest(native_code)
                or any(node_config.get(key) != value for key, value in config.items())
                or node_config.get("pre-hook") or node_config.get("post-hook")
                or (node.get("database"), node.get("schema"), node.get("alias")) !=
                   (snapshot["catalog"], snapshot["schema"], config.get("alias", model))):
            raise ValueError(f"Manifest model {model} differs from the revision or target mapping")
        parents = details["lineage"]["nodes"][model]
        if any(parent in details["active"] and parent not in present for parent in parents):
            raise ValueError("The uploaded manifest omits a required upstream model")
        declared = set(node.get("depends_on", {}).get("nodes", []))
        expected_nodes = set()
        for parent in parents:
            if parent in present:
                expected_nodes.add(f"model.{project_name}.{parent}")
            elif physical := revision["plan"]["physical"].get(parent):
                source_id = f"source.{project_name}.{physical['group']}.{physical['name']}"
                source = manifest.data.get("sources", {}).get(source_id, {})
                if any(source.get(field) != physical[target_field] for field, target_field in (
                    ("database", "catalog"), ("schema", "schema"), ("identifier", "identifier"),
                )):
                    raise ValueError("The manifest source mapping differs from the handoff")
                expected_nodes.add(source_id)
        if declared != expected_nodes:
            raise ValueError(f"Manifest dependencies differ for model {model}")
        rules = revision["settings"].get("validation_rules", {}).get(model, {})
        if model in details.get("validation_warnings", {}):
            rules = {}
        for kind, column, name, args in data_tests(model, rules, layouts[model], layouts):
            verified_tests[name] = (uid, model, kind, column, args)
    raw_results = {row["unique_id"]: row for row in results.data["results"]}
    if len(raw_results) != len(results.data["results"]):
        raise ValueError("Duplicate result for a dbt node")
    observations = bind_artifacts([manifest, results])
    observations_by_model = {model: {"tests": {}} for model in present}
    for name, (_, model, kind, column, _) in verified_tests.items():
        observations_by_model[model]["tests"][name] = "not observed"
        observations_by_model[model].setdefault("test_labels", {})[name] = f"{kind} · {column}"
    for uid, observation in observations.items():
        result = observation["observed_run"]
        status = result.get("status")
        if status not in RESULTS:
            raise ValueError("Unknown dbt result status")
        if uid in expected and command != "test":
            entry = observations_by_model[expected[uid]]
            entry["compile" if command == "compile" else "build"] = status
            if command in {"run", "build"} and raw_results[uid].get("compiled") is True:
                entry["compile"] = "success"
        elif command in {"test", "build"} and uid.startswith("test."):
            node = nodes[uid]
            if definition := verified_tests.get(node.get("name")):
                parent, model, kind, column, arguments = definition
                test = node.get("test_metadata", {})
                kwargs = test.get("kwargs", {})
                config = node.get("config", {})
                defaults = {"where": None, "limit": None, "enabled": True, "severity": "ERROR",
                            "warn_if": "!= 0", "error_if": "!= 0", "fail_calc": "count(*)"}
                if (node.get("attached_node") == parent and test.get("name") == kind
                        and {key: value for key, value in kwargs.items() if key != "model"} == {"column_name": column, **arguments}
                        and all(config.get(key, value) == value for key, value in defaults.items())):
                    observations_by_model[model]["tests"][node["name"]] = status
    invocation = metadata["invocation_id"]
    if not isinstance(invocation, str) or not re.fullmatch(r"[0-9a-fA-F-]{16,64}", invocation):
        raise ValueError("Invalid dbt invocation identifier")
    return {"revision": revision["id"], "invocation": invocation, "command": command,
            "artifacts": {"manifest": digest(manifest.text), "run_results": digest(results.text)},
            "models": observations_by_model}
