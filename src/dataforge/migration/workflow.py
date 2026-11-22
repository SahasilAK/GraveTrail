"""File-scoped AI conversion, source comparison and optimization checkpoints."""
from __future__ import annotations

from collections import defaultdict

from dataforge.migration import assistance, engine, service

STAGES = ("convert", "validate", "optimize")
PURPOSE = dict(zip(STAGES, ("convert", "critique", "optimize")))
INSTRUCTIONS = {
    "convert": "Translate this entire source file into the specified Databricks dbt outputs. Preserve "
               "shared setup, intermediate dependencies, branch predicates and all output behavior. "
               "Draft each output independently and document unfinished behavior.",
    "validate": "Independently compare the conversion draft to the original source file region by region. "
                "Account for outputs, dependencies, predicates, expressions, order, missing values and "
                "side effects. Identify omissions with a concrete engineer action. Return no edits.",
    "optimize": "Propose only behavior-preserving improvements to the supplied draft. Read the source and "
                "validation notes. Preserve unresolved comments and leave any unsafe improvement for review.",
}


def sources(project, base):
    """Summarize all included source files and keep their planned model names together."""
    plan = base["plan"]
    if not plan:
        return {}
    regions = defaultdict(list)
    for region in plan["regions"]:
        if region["disposition"] != "excluded":
            regions[region["source"]].append(region)
    return {
        row["id"]: {"path": row["path"], "regions": regions[row["id"]], "models": [
            model for region in regions[row["id"]] for model in region["outputs"]
            if not plan["outputs"][model].get("excluded")
        ], "retained": "decoded_hash" in row}
        for row in project["snapshot"]["sources"] if row["id"] in regions
    }


def _scope(project, base, source_id):
    entry = sources(project, base).get(source_id)
    if not entry or not entry["retained"] or not entry["models"]:
        raise ValueError("Choose a retained source file with a mapped output. Unmapped regions remain review findings.")
    if len(entry["models"]) > 50:
        raise ValueError("This file exceeds the 50-output request limit. Narrow the migration scope.")
    plan = base["plan"]
    related = set(entry["models"])
    pending = list(related)
    while pending:
        for model in plan["outputs"][pending.pop()]["inputs"]:
            if model in plan["outputs"] and model not in related:
                pending.append(model)
                related.add(model)
    settings = {key: value for key, value in base["settings"].items() if key != "ai_source_reviews"}
    key = engine.fingerprint([source_id, plan, settings, {
        model: base["files"].get(model, {}).get("hash") for model in sorted(related)
    }])
    return entry, key


def state(store, workspace, project, base, source_id):
    """Resume checkpoints while source mappings, settings and dependent artifacts agree."""
    entry, key = _scope(project, base, source_id)
    rows = store.rows("""SELECT body FROM migration_activity
        WHERE workspace_id=? AND project_id=? AND kind='ai_file' AND activity_id=?""",
        [workspace, project["id"], key])
    stages = service._read(rows[0]["body"]) if rows else {}
    receipt = base["settings"].get("ai_source_reviews", {}).get(source_id)
    applied = bool(receipt and all(base["files"].get(model, {}).get("hash") == digest
                                  for model, digest in receipt["files"].items()))
    return {"entry": entry, "key": key, "stages": stages, "applied": applied,
            "assessment": receipt,
            "next": next((stage for stage in STAGES if stage not in stages), "review")}


def _load_current(store, workspace, project_id, revision_id):
    project, base = service.load(store, workspace, project_id, revision_id)
    if project["revision"] != revision_id or not base["plan"] or not base["settings"].get("ai_workflow"):
        raise ValueError("Choose the current guided AI migration revision.")
    return project, base


def _candidate(stages):
    draft = stages.get("convert", {})
    edits = {model: row["sql"] for model, row in draft.get("proposal", {}).get("edits", {}).items()}
    rules = list(draft.get("proposal", {}).get("rules", ()))
    optimization = stages.get("optimize", {}).get("proposal", {})
    edits.update({model: row["sql"] for model, row in optimization.get("edits", {}).items()})
    rules.extend(rule for rule in optimization.get("rules", ()) if rule not in rules)
    return edits, rules


def _request(store, workspace, project, base, source_id, stage, feedback, static_reference):
    current = state(store, workspace, project, base, source_id)
    entry, stages = current["entry"], current["stages"]
    if stage not in STAGES or (stage != "convert" and current["next"] != stage):
        raise ValueError("Complete each earlier stage before starting this one.")
    if static_reference and stage != "convert":
        raise ValueError("Supply a static reference during conversion.")
    models = entry["models"]
    source = next(row for row in project["snapshot"]["sources"] if row["id"] == source_id)
    body = service._source_text(store, workspace, project["id"], source)
    # Include the entire retained file, even when the project selects only some of its outputs.
    regions = [region for region in base["plan"]["regions"] if region["source"] == source_id]
    file = {"id": source_id, "path": source["path"], "hash": source["hash"], "stage": stage,
            "checkpoint": engine.fingerprint(stages),
            "regions": [{**region, "original": body[region["start"]:region["end"]]} for region in regions]}
    message = INSTRUCTIONS[stage]
    candidate = None
    if stage != "convert" or feedback.strip() and "convert" in stages:
        drafts, rules = _candidate(stages)
        candidate = {**base, "files": {**base["files"], **{
            model: {"sql": sql, "hash": engine.digest(sql), "origin": "ai", "rules": rules}
            for model, sql in drafts.items()
        }}}
        if stage == "validate":
            file["validate_regions"] = [row["id"] for row in entry["regions"] if row["end"] > row["start"]
                                        and row["disposition"] != "non_executable"]
        elif stage == "optimize":
            models = [model for model in models if model in drafts]
            if not models:
                raise ValueError("There is no AI draft to optimize. Skip optimization and review the unresolved source.")
            file["validation_notes"] = stages["validate"]["coverage"]
        elif "validate" in stages:
            file["validation_notes"] = stages["validate"]["coverage"]
    if feedback.strip():
        message += "\nEngineer feedback: " + feedback.strip()
    static = None
    if static_reference:
        snapshot = service._stored_snapshot(store, workspace, project)
        _, files = engine.convert(snapshot)
        static = {model: files[model]["sql"] for model in models if model in files}
    return current, models, message, {"source_file": file, "candidate": candidate, "static_drafts": static}


def preview(store, workspace, project_id, revision_id, profile_id, source_id, stage, *,
            feedback="", static_reference=False):
    """Build the exact redacted disclosure for one file and stage."""
    project, base = _load_current(store, workspace, project_id, revision_id)
    _, models, message, context = _request(store, workspace, project, base, source_id, stage, feedback, static_reference)
    return assistance.prepare(store, workspace, project_id, revision_id, profile_id, models,
                              PURPOSE[stage], message, **context)


def _save(store, workspace, project, base, current, stages):
    with store.transaction():
        if service._project(store, workspace, project["id"])["revision"] != base["id"]:
            raise ValueError("Migration changed before saving the stage. Review the current revision.")
        rows = store.rows("""SELECT body FROM migration_activity
            WHERE workspace_id=? AND project_id=? AND activity_id=?""",
            [workspace, project["id"], current["key"]])
        latest = service._read(rows[0]["body"]) if rows else {}
        if latest != current["stages"]:
            raise ValueError("The file's workflow changed. Refresh its stages before retrying.")
        if rows:
            store.execute("""UPDATE migration_activity SET body=?
                WHERE workspace_id=? AND project_id=? AND activity_id=?""",
                [service._dump(stages), workspace, project["id"], current["key"]])
        else:
            assistance._insert(store, workspace, project["id"], current["key"], "ai_file", "saved", stages)


def run(store, workspace, project_id, revision_id, profile_id, source_id, stage, expected_pin, *,
        feedback="", static_reference=False, cancelled=lambda: False, transport=None, authorize=None):
    """Run one approved request and checkpoint the draft or observation without applying code."""
    project, base = _load_current(store, workspace, project_id, revision_id)
    current, models, message, context = _request(
        store, workspace, project, base, source_id, stage, feedback, static_reference)
    result = assistance.dispatch(store, workspace, project_id, revision_id, profile_id, models, PURPOSE[stage],
                                 message, expected_pin, cancelled=cancelled, transport=transport,
                                 authorize=authorize, **context)
    if cancelled():
        raise InterruptedError()
    if stage == "validate":
        report = service.report(project, context["candidate"])
        result["checks"] = [row for row in report["checks"] if row["model"] in models]
    stages = {} if stage == "convert" else current["stages"]
    _save(store, workspace, project, base, current, {**stages, stage: result})
    return result


def skip_optimization(store, workspace, project_id, revision_id, source_id):
    project, base = _load_current(store, workspace, project_id, revision_id)
    current = state(store, workspace, project, base, source_id)
    if current["next"] != "optimize":
        raise ValueError("Complete source validation before choosing whether to optimize.")
    _save(store, workspace, project, base, current, {**current["stages"], "optimize": {"skipped": True}})


def review(store, workspace, project_id, revision_id, source_id):
    """Rebuild the reviewed diff and its pin from saved stage results."""
    project, base = _load_current(store, workspace, project_id, revision_id)
    current = state(store, workspace, project, base, source_id)
    if current["next"] != "review":
        raise ValueError("Complete source validation and optimization before reviewing this draft.")
    stages = current["stages"]
    edits, rules = _candidate(stages)
    remaining = {model: sql for model, sql in edits.items() if base["files"].get(model, {}).get("sql") != sql}
    proposal = service.propose(base, remaining, stages["convert"]["answer"], origin="ai", rules=rules,
                               scopes=current["entry"]["models"]) if remaining else None
    receipt = {"files": {model: engine.digest(sql) for model, sql in edits.items()},
               "coverage": stages["validate"]["coverage"], "optimized": not stages["optimize"].get("skipped", False),
               "checks": stages["validate"]["checks"],
               "optimized_files": sorted(stages["optimize"].get("proposal", {}).get("edits", ())),
               "unresolved_outputs": stages["convert"].get("missing_outputs", []),
               "conversion_summary": stages["convert"]["answer"]}
    pin = engine.fingerprint([source_id, current["key"], base["id"], proposal and proposal["edits"], receipt, rules])
    if proposal:
        proposal["id"] = pin[:32]
    return proposal, receipt, pin


def apply(store, workspace, project_id, revision_id, source_id, expected_pin):
    with store.lock:
        proposal, receipt, pin = review(store, workspace, project_id, revision_id, source_id)
        if pin != expected_pin:
            raise ValueError("The staged diff changed. Review the current proposal before applying.")
        if proposal:
            approved = {row["id"] for row in assistance.lessons(store, workspace, project_id) if row["status"] == "approved"}
            if set(proposal["rules"]) - approved:
                raise ValueError("An approved lesson changed. Repeat conversion before applying this draft.")
            return service.apply(store, workspace, project_id, proposal, ai_review={source_id: receipt})
        return service.record_source_review(store, workspace, project_id, revision_id, source_id, receipt)
