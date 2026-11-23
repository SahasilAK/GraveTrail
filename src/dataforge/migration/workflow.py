"""File-scoped AI conversion, source comparison and optimization checkpoints."""
from __future__ import annotations

from collections import defaultdict

from dataforge.migration import assistance, engine, service

STAGES = ("convert", "validate", "optimize")
PURPOSE = dict(zip(STAGES, ("convert", "critique", "optimize")))
STATIC_GAPS = {"missing_output", "unsafe_sql", "artifact_integrity", "unmapped_table", "changed_dependencies",
               "broken_source", "source_structure", "unresolved_region", "changed_materialization",
               "missing_column", "target_aggregation", "set_layout", "sas_partition", "sas_stack_operation", "cycle",
               "broken_ref", "changed_projection", "sql_source_behavior", "sas_inline_rows", "sas_missing_filter",
               "sas_missing_assignment"}
STATIC_UNCERTAINTIES = {"critical_source", "source_mapping", "unknown_sensitive_type", "pending_ref",
                        "schema_conflict", "unknown_layout", "set_types", "prior_version", "unproven_column_binding"}
REFERENCE_REPAIRS = STATIC_GAPS - {"source_structure", "unresolved_region"}
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
    plan = base["plan"]
    related = engine.related_models(plan, entry["models"])
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
    status = engine.source_review_status(base).get(source_id)
    return {"entry": entry, "key": key, "stages": stages, "applied": status == "applied",
            "assessment": receipt, "assessment_status": status,
            "next": stages.get("_part", {}).get("stage") or next((stage for stage in STAGES if stage not in stages), "review")}


def resume_source(store, workspace, project, base):
    rows = store.rows("""SELECT activity_id,body FROM migration_activity
                         WHERE workspace_id=? AND project_id=? AND kind='ai_file'
                         ORDER BY created_at DESC LIMIT 1""", [workspace, project["id"]])
    source = service._read(rows[0]["body"]).get("_source") if rows else None
    if source:
        try:
            return source if _scope(project, base, source)[1] == rows[0]["activity_id"] else None
        except ValueError:
            return None
    return None


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


def _staged_revision(base, stages):
    drafts, rules = _candidate(stages)
    return {**base, "files": {**base["files"], **{
        model: {"sql": sql, "hash": engine.digest(sql), "origin": "ai", "rules": rules}
        for model, sql in drafts.items()
    }}}


def _checks(project, candidate, entry):
    report = service.report(project, candidate)
    models = set(entry["models"])
    regions = {region["id"] for region in entry["regions"]}
    findings = [row for row in report["findings"] if not row.get("inherited_from") and (
        row["model"] in models or row["model"] is None and row["region"] in regions)]
    return [row for row in report["checks"] if row["model"] in models], findings


def _validated_coverage(coverage, findings):
    severity = {"accounted": 0, "uncertain": 1, "gap": 2}
    for row in findings:
        region = row["region"]
        status = "gap" if row["code"] in STATIC_GAPS else "uncertain" if row["code"] in STATIC_UNCERTAINTIES else None
        if status and region in coverage and severity[status] > severity[coverage[region]["status"]]:
            original = coverage[region]
            coverage[region] = {"status": status, "detail": f"Static check: {row['message']}",
                                "ai_status": original.get("ai_status", original["status"]),
                                "ai_detail": original.get("ai_detail", original["detail"])}
    return coverage


def _recover_with_reference(project, base, entry, result, references):
    """Offer a mechanically checked candidate from an explicitly selected static reference."""
    edits, rules = _candidate({"convert": result})
    failures = {row["model"] for row in result["findings"] if row["code"] in REFERENCE_REPAIRS}
    replacements = {model: sql for model, sql in references.items() if model in failures and edits.get(model) != sql}
    if not replacements:
        return
    files = _staged_revision(base, {"convert": result})["files"]
    trial = {**base, "files": {**files, **{
        model: {"sql": sql, "hash": engine.digest(sql), "origin": "ai", "rules": rules}
        for model, sql in replacements.items()
    }}}
    _, findings = _checks(project, trial, entry)
    rejected = {row["model"] for row in findings if row["code"] in REFERENCE_REPAIRS}
    repaired = sorted(replacements.keys() - rejected)
    if repaired:
        edits.update({model: replacements[model] for model in repaired})
        edits = {model: sql for model, sql in edits.items() if base["files"].get(model, {}).get("sql") != sql}
        if edits:
            result["proposal"] = service.propose(base, edits, result["answer"], origin="ai", rules=rules,
                                                 scopes=entry["models"])
        else:
            result.pop("proposal", None)
        result["reference_recovered"] = repaired
        result["missing_outputs"] = [model for model in result["missing_outputs"] if model not in repaired]
        result["checks"], result["findings"] = _checks(project, _staged_revision(base, {"convert": result}), entry)


def _request(store, workspace, project, base, source_id, stage, feedback, static_reference):
    current = state(store, workspace, project, base, source_id)
    entry, stages = current["entry"], current["stages"]
    if stage not in STAGES or (stage != "convert" and current["next"] != stage):
        raise ValueError("Complete each earlier stage before starting this one.")
    if static_reference and stage != "convert":
        raise ValueError("Supply a static reference during conversion.")
    models = entry["models"]
    if stage == "convert" and current["assessment_status"] == "unresolved":
        unresolved = set(current["assessment"]["unresolved_outputs"])
        models = [model for model in models if model in unresolved] or models
    source = next(row for row in project["snapshot"]["sources"] if row["id"] == source_id)
    body = service._source_text(store, workspace, project["id"], source)
    # Include the entire retained file, even when the project selects only some of its outputs.
    regions = [region for region in base["plan"]["regions"] if region["source"] == source_id]
    file = {"id": source_id, "path": source["path"], "kind": source["kind"], "hash": source["hash"], "stage": stage,
            "checkpoint": engine.fingerprint(stages),
            "regions": [{**{key: region[key] for key in (
                "id", "start_line", "end_line", "outputs", "gap", "disposition")},
                "original": body[region["start"]:region["end"]]} for region in regions]}
    message = INSTRUCTIONS[stage]
    candidate = None
    if stage != "convert" or (feedback.strip() or static_reference) and "convert" in stages:
        candidate = _staged_revision(base, stages)
        if stage == "validate":
            file["validate_regions"] = [row["id"] for row in entry["regions"] if row["end"] > row["start"]
                                        and row["disposition"] != "non_executable"]
        elif stage == "optimize":
            invalid = {row["model"] for row in stages["validate"]["checks"] if row["status"] == "fail"
                       and row["check"] in {"target_sql_and_templates", "artifact_integrity", "schema"}}
            invalid.update(row["model"] for row in stages["validate"].get("findings", ()) if row["code"] in STATIC_GAPS)
            models = [model for model in models if model in candidate["files"] and model not in invalid]
            if not models:
                raise ValueError("No draft passed the required SQL checks. Skip optimization and revise the draft in Review.")
            model_regions = {base["plan"]["outputs"][model]["region"] for model in models}
            file["validation_notes"] = {region: note for region, note in stages["validate"]["coverage"].items()
                                        if region in model_regions}
        elif "validate" in stages:
            file["validation_notes"] = stages["validate"]["coverage"]
    if feedback.strip():
        message += "\nEngineer feedback: " + feedback.strip()
    static = None
    if static_reference:
        target = engine.warehouse(project["snapshot"])
        static = {}
        for model in models:
            if literals := base["plan"]["outputs"][model].get("sas_inline"):
                static[model] = engine.inline_reference(literals, target)
        if len(static) < len(models):
            snapshot = service._stored_snapshot(store, workspace, project)
            _, files = engine.convert(snapshot)
            static.update({model: files[model]["sql"] for model in models if model in files and model not in static})
        if not static:
            raise ValueError("No static draft exists for this file. Retry with feedback or supply the missing source evidence.")
    return current, models, message, {"source_file": file, "candidate": candidate, "static_drafts": static}


def _request_part(store, workspace, project, base, profile_id, source_id, stage, feedback, static_reference):
    current, models, message, context = _request(
        store, workspace, project, base, source_id, stage, feedback, static_reference)
    file = context["source_file"]
    outputs = base["plan"]["outputs"]
    region_models = defaultdict(list)
    for model in models:
        region_models[outputs[model]["region"]].append(model)
    if stage == "validate":
        units = [(region, model) for region in file["validate_regions"] for model in region_models[region] or [None]]
    else:
        units = [(outputs[model]["region"], model) for model in models]
    partial = current["stages"].get("_part", {})
    if partial.get("stage") != stage:
        partial = {}
    start = partial.get("done", 0)
    limit = min(len(units) - start, partial.get("limit") or assistance.MAX_MODELS_PER_REQUEST)
    whole = start == 0 and limit == len(units) and not partial
    reduce_context = False
    if stage == "convert" and partial.get("result"):
        context["candidate"] = _staged_revision(context["candidate"] or base, {"convert": partial["result"]})
    details = service.report(project, context["candidate"] or base)
    shared = {row["id"] for row in file["regions"] if not row["outputs"] and row["disposition"] != "non_executable"}
    available = {row["id"] for row in file["regions"]}
    while limit > 0:
        batch = units[start:start + limit]
        selected = [model for _, model in batch if model is not None]
        primary = {region for region, _ in batch}
        dependencies = {outputs[parent]["region"] for model in selected for parent in outputs[model]["inputs"]
                        if parent in outputs}
        extra = ((dependencies | shared) & available) - primary
        part = {"from": start + 1, "through": start + limit, "total": len(units)}
        scoped = {**file, "part": part, "regions": [
            row for row in file["regions"] if whole or row["id"] in (primary if reduce_context else primary | extra)]}
        if reduce_context:
            scoped["omitted_context"] = sorted(extra)
        if stage == "validate":
            scoped["validate_regions"] = sorted(primary)
        if notes := scoped.get("validation_notes"):
            scoped["validation_notes"] = {region: note for region, note in notes.items() if whole or region in primary}
        static = context["static_drafts"]
        payload = {"source_file": scoped, "candidate": context["candidate"],
                   "static_drafts": {model: static[model] for model in selected if model in static} if static else None}
        part_message = message if whole else message + (
            "\nWork only on this part's listed outputs or validation regions. Other disclosed regions are context. "
            "Flag any shared behavior you cannot verify.")
        args = (store, workspace, project["id"], base["id"], profile_id, selected, PURPOSE[stage], part_message)
        try:
            prepared = assistance.prepare(*args, **payload, details=details)
            return current, partial, part, args, payload, prepared
        except assistance.DisclosureSizeError as exc:
            if whole:
                whole = False
            elif limit > 1:
                limit //= 2
            elif extra and not reduce_context:
                reduce_context = True
            else:
                reason = f"Source part exceeds the provider disclosure limit. {exc}"
                pin = engine.fingerprint([base["id"], profile_id, scoped, message, payload["static_drafts"], reason])
                body = {"source_file": {"id": source_id, "stage": stage, "part": part,
                                        "regions": sorted(primary)}, "reason": reason}
                prepared = {"pin": pin, "recipient": None, "request": None, "body": body, "tokens": 0,
                            "scope": selected, "rules": [], "local_reason": reason}
                return current, partial, part, args, payload, prepared
    raise ValueError("This stage has no remaining source work.")


def preview(store, workspace, project_id, revision_id, profile_id, source_id, stage, *,
            feedback="", static_reference=False):
    """Build the exact redacted disclosure for one file and stage."""
    project, base = _load_current(store, workspace, project_id, revision_id)
    *_, prepared = _request_part(
        store, workspace, project, base, profile_id, source_id, stage, feedback, static_reference)
    return prepared


def _save(store, workspace, project, base, current, stages):
    stages = {**stages, "_source": current["entry"]["regions"][0]["source"]}
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
            store.execute("""UPDATE migration_activity SET body=?,created_at=current_timestamp
                WHERE workspace_id=? AND project_id=? AND activity_id=?""",
                [service._dump(stages), workspace, project["id"], current["key"]])
        else:
            assistance._insert(store, workspace, project["id"], current["key"], "ai_file", "saved", stages)


def _merge_parts(previous, latest):
    if not previous:
        return latest
    result = {**previous, "answer": (previous["answer"] + "\n" + latest["answer"])[:4000]}
    for field in ("scope", "citations", "missing_outputs", "normalized_models", "reference_recovered"):
        if field in previous or field in latest:
            result[field] = list(dict.fromkeys(previous.get(field, []) + latest.get(field, [])))
    for field in ("needs_static_reference", "rejected"):
        if field in previous or field in latest:
            result[field] = bool(previous.get(field) or latest.get(field))
    if "source_anchors" in latest:
        result["source_anchors"] = {**previous.get("source_anchors", {}), **latest["source_anchors"]}
    if "coverage" in latest:
        weights = {"accounted": 0, "uncertain": 1, "gap": 2}
        coverage = dict(previous.get("coverage", {}))
        for region, observation in latest["coverage"].items():
            if region not in coverage or weights[observation["status"]] > weights[coverage[region]["status"]]:
                coverage[region] = observation
        result["coverage"] = coverage
    if proposal := latest.get("proposal"):
        earlier = previous.get("proposal", {})
        result["proposal"] = {**proposal, "edits": {**earlier.get("edits", {}), **proposal["edits"]},
                              "rules": list(dict.fromkeys(earlier.get("rules", []) + proposal["rules"]))}
    return result


def run(store, workspace, project_id, revision_id, profile_id, source_id, stage, expected_pin, *,
        feedback="", static_reference=False, cancelled=lambda: False, transport=None, authorize=None):
    """Run one approved request and checkpoint the draft or observation without applying code."""
    project, base = _load_current(store, workspace, project_id, revision_id)
    current, partial, part, args, context, prepared = _request_part(
        store, workspace, project, base, profile_id, source_id, stage, feedback, static_reference)
    if prepared["pin"] != expected_pin:
        raise ValueError("The disclosure, lesson, source or recipient changed. Preview it again.")
    if cancelled():
        raise InterruptedError()
    models = prepared["scope"]
    reason = prepared.get("local_reason")
    if reason is None:
        try:
            result = assistance.dispatch(*args, expected_pin, cancelled=cancelled, transport=transport,
                                         authorize=authorize, **context)
        except assistance.ProviderOutputLimit as exc:
            count = part["through"] - part["from"] + 1
            if count > 1:
                if cancelled():
                    raise InterruptedError() from exc
                checkpoint = {**partial, "stage": stage, "done": part["from"] - 1, "limit": count // 2}
                _save(store, workspace, project, base, current, {**current["stages"], "_part": checkpoint})
                return {"answer": str(exc), "part": part, "next_size": checkpoint["limit"], "status": "resize"}
            reason = str(exc) + " This source part needs engineer review."
        except (assistance.OptimizationRejected, assistance.ProviderDraftError) as exc:
            if stage == "optimize" or stage == "convert" and context["static_drafts"]:
                reason = str(exc)
            else:
                raise
    if reason is not None:
        result = {"answer": reason, "missing_outputs": list(models) if stage == "convert" else [], "rejected": True}
        if stage == "validate":
            result["coverage"] = {region: {"status": "uncertain", "detail": reason}
                                  for region in context["source_file"]["validate_regions"]}
    if cancelled():
        raise InterruptedError()
    earlier = partial.get("result", {})
    if stage == "convert" and context["static_drafts"]:
        scoped_entry = {**current["entry"], "models": models}
        staged_base = _staged_revision(base, {"convert": earlier})
        result["checks"], result["findings"] = _checks(project, _staged_revision(staged_base, {"convert": result}), scoped_entry)
        _recover_with_reference(project, staged_base, scoped_entry, result, context["static_drafts"])
    if stage == "validate" and context["source_file"].get("omitted_context"):
        result["coverage"] = {region: ({"status": "uncertain", "detail": (
            "Related source regions exceeded the disclosure limit. Review their shared behavior against this draft.")}
            if observation["status"] == "accounted" else observation)
            for region, observation in result["coverage"].items()}
    result = _merge_parts(earlier, result)
    if part["through"] < part["total"]:
        checkpoint = {**partial, "stage": stage, "done": part["through"], "result": result}
        _save(store, workspace, project, base, current, {**current["stages"], "_part": checkpoint})
        return {"part": part, "status": "partial", "answer": result["answer"]}
    if stage in {"convert", "validate"}:
        candidate = _staged_revision(base, {"convert": result}) if stage == "convert" else context["candidate"]
        result["checks"], result["findings"] = _checks(project, candidate, current["entry"])
        if stage == "validate":
            result["coverage"] = _validated_coverage(result["coverage"], result["findings"])
    stages = {} if stage == "convert" else {key: value for key, value in current["stages"].items() if key != "_part"}
    _save(store, workspace, project, base, current, {**stages, stage: result})
    return result


def skip_optimization(store, workspace, project_id, revision_id, source_id):
    project, base = _load_current(store, workspace, project_id, revision_id)
    current = state(store, workspace, project, base, source_id)
    if current["next"] != "optimize":
        raise ValueError("Complete source validation before choosing whether to optimize.")
    stages = {key: value for key, value in current["stages"].items() if key != "_part"}
    if result := current["stages"].get("_part", {}).get("result"):
        stages["optimize"] = {**result, "skipped": True}
    else:
        stages["optimize"] = {"skipped": True}
    _save(store, workspace, project, base, current, stages)


def review(store, workspace, project_id, revision_id, source_id):
    """Rebuild the reviewed diff and its pin from saved stage results."""
    project, base = _load_current(store, workspace, project_id, revision_id)
    current = state(store, workspace, project, base, source_id)
    if current["next"] != "review":
        raise ValueError("Complete source validation and optimization before reviewing this draft.")
    stages = current["stages"]
    edits, rules = _candidate(stages)
    candidate = _staged_revision(base, stages)
    _, findings = _checks(project, candidate, current["entry"])
    withheld = defaultdict(list)
    for row in findings:
        if row["model"] in current["entry"]["models"] and row["model"] in candidate["files"] and (
            row["code"] in service.MECHANICAL_FINDINGS
        ):
            withheld[row["model"]].append(row["message"])
    edits = {model: sql for model, sql in edits.items() if model not in withheld}
    remaining = {model: sql for model, sql in edits.items() if base["files"].get(model, {}).get("sql") != sql}
    models = current["entry"]["models"]
    proposal = service.propose(base, remaining, stages["convert"]["answer"], origin="ai", rules=rules,
                               source_id=source_id) if remaining else None
    files = {**base["files"], **{model: {"hash": engine.digest(sql)} for model, sql in edits.items()}}
    missing = set(stages["convert"].get("missing_outputs", [])) | withheld.keys() | (set(models) - files.keys())
    context = engine.source_review_context(base["plan"], base["settings"])
    receipt = {"files": {model: files[model]["hash"] for model in models if model not in missing},
               "models": models, "key": engine.source_review_key(context, base["plan"], files, models),
               "coverage": stages["validate"]["coverage"],
               "optimized": not (stages["optimize"].get("skipped") or stages["optimize"].get("rejected")),
               "checks": stages["validate"]["checks"],
               "optimized_files": sorted(stages["optimize"].get("proposal", {}).get("edits", ())),
               "reference_recovered": stages["convert"].get("reference_recovered", []),
               "unresolved_outputs": sorted(missing),
               "withheld_drafts": {model: {"before": base["files"].get(model, {}).get("hash"), "reasons": reasons}
                                   for model, reasons in withheld.items()},
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
