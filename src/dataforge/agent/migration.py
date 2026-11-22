"""Workspace-authorized CLI and MCP access to the static migration service."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dataforge.agent.contracts import AgentError, compact
from dataforge.agent.paging import page
from dataforge.artifacts import write_artifact
from dataforge.connections import connection_scope, current_connections
from dataforge.exports import report_csv
from dataforge.lineage_builder import load_builder
from dataforge.migration import assistance, engine, inspection, service, validation, workflow
from dataforge.migration.targets import FORMATS, LEGACY_DATABRICKS, WAREHOUSES
from dataforge.provider_service import authorize_provider, get_profile
from dataforge.schema_imports import MAX_IMPORT_BYTES, import_schema

READS = {"migration_targets", "migration_list", "migration_preview", "migration_inspect", "migration_edit_preview",
         "migration_ai_preview", "migration_stage_preview"}
WRITES = {"migration_create", "migration_convert", "migration_change", "migration_ai_request", "migration_export",
          "migration_stage_request"}
SOURCE_ACTIONS = (READS | WRITES) - {"migration_targets", "migration_list", "migration_inspect"}

MigrationView = Literal[
    "summary", "sources", "models", "regions", "findings", "checks", "mappings", "schemas", "lineage",
    "column_lineage", "original_lineage", "history", "reviews", "comments", "lessons", "ai_attempts", "ai_responses",
    "validation_runs", "reconciliation_runs", "reconciliation_plan", "reconciliation_template",
    "source_mappings_template", "pilot", "artifact", "workflow",
]
MigrationChange = Literal[
    "resolve_scope", "set_contract", "apply", "revise_schemas", "bulk_mappings", "import_schema", "configure_validation",
    "import_validation", "import_reconciliation", "record_review", "restore", "add_comment", "resolve_comment",
    "save_lesson", "revoke_lesson", "apply_source_draft", "skip_optimization",
]
MigrationPurpose = Literal["convert", "explain", "critique", "propose", "optimize"]
MigrationStage = Literal["convert", "validate", "optimize"]


class MigrationSetup(BaseModel):
    """Select retained file IDs, analyzed assets, or a pinned Builder design."""

    model_config = ConfigDict(extra="forbid")
    selection: list[str] | None = Field(default=None, max_length=10_000)
    analysis_run: str | None = None
    selected_outputs: list[str] | None = Field(default=None, max_length=10_000)
    builder_revision: str | None = None
    builder_tables: list[str] | None = Field(default=None, max_length=10_000)
    dialects: dict[str, str] | None = Field(default=None, max_length=10_000)
    format: Literal["dbt"] = "dbt"
    warehouse: Literal["databricks"] = "databricks"
    profile: str | None = None
    catalog: str = Field(default="main", max_length=128)
    schema_name: str = Field(default="migration", max_length=128, alias="schema")
    materialization: Literal["table", "view"] = "table"


class _Edit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    before: str | None
    sql: str = Field(min_length=1, max_length=engine.MAX_ARTIFACT)


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=64)
    base: str = Field(min_length=1, max_length=64)
    edits: dict[str, _Edit] = Field(min_length=1, max_length=50)
    origin: Literal["manual", "ai", "optimization"]
    rationale: str = Field(min_length=1, max_length=4000)
    rules: list[str] = Field(max_length=50)


def _text_reply(opts, text, offset, **metadata):
    if type(offset) is not int or not 0 <= offset <= len(text):
        raise AgentError("invalid_argument", "Choose a character offset within the migration evidence")
    end = min(len(text), offset + opts.max_chars)
    while end >= offset:
        result = {**metadata, "offset": offset, "text": text[offset:end], "chars": len(text),
                  "next_offset": end if end < len(text) else None, "complete": end == len(text)}
        if len(compact(result)) <= opts.max_chars and (end > offset or end == len(text)):
            return result
        if end == offset:
            break
        end = offset + (end - offset) // 2
    raise AgentError("budget_too_small", "Increase max_chars to retrieve migration evidence")


def _payload_reply(opts, body, offset=0, **metadata):
    full = {**metadata, **body}
    if offset == 0 and len(compact(full)) <= opts.max_chars:
        return full
    return _text_reply(opts, compact(body), offset, encoding="json", **metadata)


class MigrationOperations:
    """Translate bounded agent requests to existing workspace and revision operations."""

    def _migration_targets(self, w, opts):
        builder = load_builder(self.store, w)
        return page([{"table_id": row.id, "name": row.name, "role": row.role} for row in builder.tables], opts,
                    [w, "migration_targets", builder.revision], formats=FORMATS,
                    warehouses={key: asdict(value) for key, value in WAREHOUSES.items()},
                    legacy_profiles=[LEGACY_DATABRICKS.profile], analysis_run=service.latest_run(self.store, w),
                    builder_revision=builder.revision)

    def _migration_list(self, w, opts):
        projects = service.projects(self.store, w)
        return page(current_connections().sanitize(projects), opts,
                    [w, "migration_projects", [(p["id"], p["revision"]) for p in projects]])

    def _migration_freeze(self, w, setup):
        args = MigrationSetup.model_validate(setup).model_dump(exclude_none=True, by_alias=True)
        if args.get("analysis_run") == "latest":
            args["analysis_run"] = service.latest_run(self.store, w)
            if not args["analysis_run"]:
                raise AgentError("not_found", "Run workspace analysis before selecting the latest analysis")
        if args.get("builder_revision") == "current":
            args["builder_revision"] = load_builder(self.store, w).revision
        if args.get("selected_outputs") and not args.get("analysis_run"):
            raise AgentError("invalid_argument", "Choose an analysis run for the selected lineage outputs")
        if args.get("builder_tables") is not None and not args.get("builder_revision"):
            raise AgentError("invalid_argument", "Choose a Builder revision for the selected design tables")
        if "selection" not in args:
            args["selection"] = [] if "builder_revision" in args else [row["file_id"] for row in self.store.files(w)
                if row["relative_path"].lower().endswith((".sql", ".sas", "dbt_project.yml", "dbt_project.yaml"))]
        return service.freeze(self.store, w, **args)

    def _migration_preview(self, w, opts, name, setup):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 160:
            raise AgentError("invalid_argument", "Enter a migration project name of up to 160 characters")
        snapshot = self._migration_freeze(w, setup)
        pin = engine.fingerprint([name, snapshot])
        plan, details = service.preview(snapshot)
        rows = [{"kind": "source", **{key: value for key, value in row.items() if key != "text"}}
                for row in snapshot["sources"]]
        rows.extend({"kind": "output", "model": model, "name": output["name"], "inputs": output["inputs"],
                     "excluded": output.get("excluded", False), "region": output["region"]}
                    for model, output in plan["outputs"].items())
        rows.extend({"kind": "finding", **finding} for finding in details["findings"])
        rows.extend({"kind": "admission", **entry} for entry in snapshot.get("upload_report", []))
        return page(current_connections().sanitize(rows), opts, [w, "migration_preview", pin], pin=pin,
                    models=len(plan["outputs"]), sources=len(snapshot["sources"]))

    def _migration_create(self, w, opts, name, setup, expected_pin):
        snapshot = self._migration_freeze(w, setup)
        if expected_pin != engine.fingerprint([name, snapshot]):
            raise AgentError("conflict", "Migration scope changed. Preview the retained sources again")
        return service.create_project(self.store, w, name, snapshot)

    def _migration_current(self, w, project_id, revision_id):
        project, base = service.load(self.store, w, project_id, revision_id)
        if project["revision"] != revision_id:
            raise AgentError("conflict", "Migration revision changed. Inspect the current revision and retry")
        return project, base

    def _migration_convert(self, w, opts, project_id, expected_revision, reconvert=False, plan_only=False):
        self._migration_current(w, project_id, expected_revision)
        job_id = assistance.start_job(self.store, w, project_id, self.jobs,
            lambda progress, cancelled: self._run_migration_conversion(
                w, project_id, expected_revision, reconvert, plan_only, progress=progress, cancelled=cancelled),
            access=self._workspace(w, write=True, source=True).model_dump(), operation="migration_convert")
        return {"job_id": job_id, "status": "queued"}

    def _run_migration_conversion(self, w, project_id, expected_revision, reconvert=False, plan_only=False, *,
                                  progress=None, cancelled=None):
        self._workspace(w, write=True, source=True)
        next_check = time.monotonic() + .5

        def revoked_or_cancelled():
            nonlocal next_check
            now = time.monotonic()
            if now >= next_check:
                self._workspace(w, write=True, source=True)
                next_check = now + .5
            return cancelled() if cancelled else False

        base = service.convert(self.store, w, project_id, expected_revision, cancelled=revoked_or_cancelled,
                               progress=progress, reconvert=reconvert, plan_only=plan_only)
        return {"project_id": project_id, "revision_id": base["id"], "converter_version": base["plan"]["version"]}

    def _migration_inspect(self, w, opts, project_id, revision_id=None, view="summary", item=None, anchor=None, offset=0):
        if view not in {"summary", "history"}:
            self._workspace(w, source=True)
        project, base = service.load(self.store, w, project_id, revision_id)
        plan = base["plan"]
        metadata = {"project_id": project_id, "revision_id": base["id"], "current_revision": project["revision"], "view": view}
        identity = [w, project_id, base["id"], view, item]
        redact = current_connections().sanitize
        if view == "history":
            rows = service.history(self.store, w, project_id)
            return page(rows, opts, [*identity, [row["id"] for row in rows]], **metadata)
        if view == "summary":
            details = service.report(project, base) if plan else {}
            target = project["snapshot"]
            return {**metadata, "name": redact(project["name"]),
                    "target": {key: target[key] for key in ("warehouse", "profile", "catalog", "schema")},
                    "converted": bool(plan), "converter_version": plan and plan["version"],
                    "coverage": details.get("coverage", {}), "eligible": details.get("eligible", False),
                    "job_id": assistance.latest_job(self.store, w, project_id), "runtime_equivalence": "not_evaluated"}
        if view == "sources":
            return page(redact(project["snapshot"]["sources"]), opts, identity, **metadata)
        if not plan:
            raise AgentError("conflict", "Convert the pinned sources before inspecting this view")
        if view == "workflow":
            if item:
                checkpoint = workflow.state(self.store, w, project, base, item)
                body = {"source": item, "workflow": checkpoint}
                if checkpoint["next"] == "review" and not checkpoint["applied"]:
                    proposal, assessment, pin = workflow.review(self.store, w, project_id, base["id"], item)
                    body.update(proposal=proposal, assessment=assessment, pin=pin,
                                diffs=dict(service.diffs(base, proposal)) if proposal else {})
                return _payload_reply(opts, body, offset, **metadata)
            rows = [{"source_id": key, "path": entry["path"], "models": entry["models"], "retained": entry["retained"]}
                    for key, entry in workflow.sources(project, base).items()]
        elif view == "regions":
            rows = plan["regions"]
        elif view == "reviews":
            rows = [{"model": model, **row} for model, row in base["reviews"].items()]
        elif view == "comments":
            rows = service.review_comments(self.store, w, project_id)
        elif view == "lessons":
            rows = assistance.lessons(self.store, w, project_id)
        elif view == "ai_attempts":
            rows = assistance.attempts(self.store, w, project_id)
        elif view in {"ai_responses", "validation_runs", "reconciliation_runs"}:
            readers = {"ai_responses": assistance.responses, "validation_runs": service.validation_runs,
                       "reconciliation_runs": service.reconciliation_runs}
            kwargs = {"prune": False} if view == "ai_responses" else {}
            records = readers[view](self.store, w, project_id, **kwargs)
            if item:
                record = next((row for row in records if (row.get("id") or row.get("invocation")) == item), None)
                if record is None:
                    raise AgentError("not_found", "Migration observation does not exist in this project")
                # A saved AI proposal must retain its exact hashes and SQL for review and explicit application.
                return _payload_reply(opts, {"record": record if view == "ai_responses" else redact(record)}, offset, **metadata)
            rows = [{key: value for key, value in row.items() if key not in {"models", "proposal", "answer"}}
                    for row in records]
        elif view in {"mappings", "source_mappings_template"}:
            rows = [{"source": key, **value} for key, value in plan["physical"].items()]
            if view == "source_mappings_template":
                fields = ("source", "catalog", "schema", "identifier")
                template = report_csv([{field: row[field] for field in fields} for row in rows]) if rows else "source,catalog,schema,identifier\n"
                return _text_reply(opts, template, offset, **metadata)
        else:
            details = service.report(project, base)
            if view in {"models", "artifact"}:
                entries = inspection.artifacts(project, base, details, service.review_comments(self.store, w, project_id))
                if view == "artifact":
                    entry = entries.get(item)
                    if not entry:
                        raise AgentError("not_found", "Choose an artifact from the migration models view")
                    anchor = anchor or "annotated"
                    if anchor == "source":
                        text = service.evidence(self.store, w, project_id, entry["region"])
                    elif anchor == "generated" and entry["file"]:
                        text = entry["file"]["sql"]
                        if engine.digest(text) != entry["file"]["hash"]:
                            raise AgentError("conflict", "Generated artifact failed its integrity check")
                    elif anchor == "annotated":
                        text = inspection.annotated(entry, redact=current_connections().redact)[0]
                    else:
                        raise AgentError("not_found", "That anchor has no evidence in this revision")
                    return _text_reply(opts, redact(text), offset, artifact=item, anchor=anchor,
                                       source=entry["region"]["id"], path=redact(entry["path"]), **metadata)
                rows = [{key: entry[key] for key in ("id", "model", "path", "confidence", "status", "open_notes")}
                        | {"region": entry["region"]["id"], "location": inspection.source_location(entry),
                           "findings": len(entry["findings"]),
                           "plan": plan["outputs"].get(entry["model"], {}),
                           "validation": base["settings"].get("validation_rules", {}).get(entry["model"], {}),
                           "config": details["model_config"].get(entry["model"], {})}
                        for entry in entries.values()]
            elif view in {"findings", "checks"}:
                rows = details[view]
            elif view == "schemas":
                rows = [{"relation": relation, "column": column, "scope": scope, **fact}
                        for scope, schemas in (("model", details["schemas"]), ("source", details["source_schemas"]))
                        for relation, fields in schemas.items() for column, fact in fields.items()]
            elif view in {"lineage", "column_lineage"}:
                rows = details["lineage"]["edges" if view == "lineage" else "columns"]
            elif view == "original_lineage":
                snapshot = project["snapshot"]
                rows = [{"source": source, "target": target} for source, target in
                        snapshot.get("original_edge_labels", snapshot.get("original_edges", []))]
            elif view in {"reconciliation_plan", "reconciliation_template"}:
                plan_rows = validation.reconciliation_plan(project, base, details)
                if item:
                    plan_rows = {name: row for name, row in plan_rows.items() if name == item}
                if view == "reconciliation_template":
                    return _text_reply(opts, validation.reconciliation_template(plan_rows), offset, **metadata)
                rows = list(plan_rows.values())
            elif view == "pilot":
                selected = item.split(",") if item else []
                models, inputs = service.pilot_scope(base, details, selected)
                rows = [{"model": model, "upstream": model not in selected} for model in sorted(models)]
                rows.extend({"source": dependency} for dependency in sorted(inputs))
            else:
                raise AgentError("invalid_argument", "Choose a valid migration inspection view")
        if item and view in {"models", "regions", "findings", "checks", "schemas", "lineage", "column_lineage", "comments", "reviews"}:
            rows = [row for row in rows if any(row.get(key) == item for key in ("id", "model", "relation", "target", "artifact"))]
        rows = redact(rows)
        return page(rows, opts, [*identity, engine.fingerprint(rows)], **metadata)

    def _migration_upload(self, arguments, content_key, path_key, limit):
        content, path = arguments.get(content_key), arguments.get(path_key)
        if (content is None) == (path is None):
            raise AgentError("invalid_argument", f"Supply {content_key} or {path_key}")
        if path is not None:
            file = self.policy.import_path(path)
            if not file.is_file():
                raise AgentError("invalid_path", "Select a bounded evidence file under an approved root")
            with file.open("rb") as stream:
                data = stream.read(limit + 1)
        elif isinstance(content, str):
            data = content.encode("utf-8")
        else:
            raise AgentError("invalid_argument", f"Supply UTF-8 text in {content_key}")
        if len(data) > limit:
            raise AgentError("resource_limit", "Migration input exceeds the file size limit")
        return data

    def _migration_import_schema(self, w, project_id, revision_id, base, arguments):
        body = self._migration_upload(arguments, "content", "path", MAX_IMPORT_BYTES)
        filename = Path(arguments.get("path") or arguments.get("filename") or "").name
        group = arguments.get("group")
        plan = base["plan"]
        if not plan or group not in plan["physical"] and group not in plan["outputs"]:
            raise AgentError("not_found", "Choose a physical source or model from this migration")
        definitions, warnings = import_schema(filename, body)
        if len(definitions) != 1 or warnings:
            raise AgentError("validation_failed", "Import one relation with complete type definitions")
        imported = {column.name: column.data_type for column in definitions[0].columns if column.data_type}
        if group in plan["physical"]:
            inputs = base["settings"].get("input_types", {})
            types = {**arguments.get("types", inputs.get(group, {})), **imported}
            settings = {"input_types": {**inputs, group: types}}
        else:
            prefix = group + "."
            outputs = base["settings"].get("types", {})
            previous = {key.removeprefix(prefix): value for key, value in outputs.items() if key.startswith(prefix)}
            types = {**arguments.get("types", previous), **imported}
            settings = {"types": {**{key: value for key, value in outputs.items() if not key.startswith(prefix)},
                                  **{prefix + key: value for key, value in types.items()}}}
        return service.revise_schemas(self.store, w, project_id, revision_id, settings)

    def _migration_proposal(self, arguments):
        if "proposal" not in arguments and "proposal_path" in arguments:
            body = self._migration_upload(arguments, "proposal", "proposal_path", 4 * engine.MAX_ARTIFACT)
            proposal = json.loads(body)
        else:
            proposal = arguments.get("proposal")
        return _Proposal.model_validate(proposal).model_dump()

    def _migration_edit_preview(self, w, opts, project_id, revision_id, arguments):
        project, base = self._migration_current(w, project_id, revision_id)
        args = dict(arguments)
        offset = args.pop("offset", 0)
        if "proposal" in args or "proposal_path" in args:
            proposal = self._migration_proposal(args)
        else:
            if "replacements_path" in args:
                data = self._migration_upload(args, "replacements", "replacements_path", 4 * engine.MAX_ARTIFACT)
                args["replacements"] = json.loads(data)
            proposal = service.ordered_sas_proposal(project, base, **args) if "order" in args else service.propose(
                base, args["replacements"], args["rationale"], scopes=args.get("scopes"))
            proposal["id"] = engine.fingerprint([w, project_id, {key: value for key, value in proposal.items() if key != "id"}])[:32]
        candidate = service.candidate(base, proposal)
        report = service.report(project, candidate)
        edited = proposal["edits"]
        redact = current_connections().for_workspace(self.store.home, w).sanitize
        if redact(proposal) != proposal:
            raise AgentError("validation_failed", "Remove credential values before preparing a migration edit")
        response = {"proposal": proposal, "diffs": redact(dict(service.diffs(base, proposal))),
                    "findings": [row for row in report["findings"] if row["model"] in edited],
                    "tiers": {model: report["tiers"][model] for model in edited}}
        return _payload_reply(opts, response, offset, project_id=project_id, revision_id=revision_id,
                              pin=engine.fingerprint([w, project_id, proposal]))

    def _migration_change(self, w, opts, project_id, revision_id, operation, arguments):
        args = dict(arguments)
        params = (self.store, w, project_id, revision_id)
        if operation == "import_validation":
            manifest = self._migration_upload(args, "manifest", "manifest_path", validation.MAX_ARTIFACT_BYTES)
            results = self._migration_upload(args, "run_results", "results_path", validation.MAX_ARTIFACT_BYTES)
            summary = service.import_validation(*params, manifest, results)
            return {"revision_id": revision_id, "invocation": summary["invocation"], "models": len(summary["models"])}
        if operation == "import_reconciliation":
            body = self._migration_upload(args, "csv", "path", validation.MAX_ARTIFACT_BYTES)
            summary = service.import_reconciliation(*params, body)
            return {"revision_id": revision_id, "models": len(summary["models"])}
        _, base = self._migration_current(w, project_id, revision_id)
        mutations = {"resolve_scope": service.resolve_scope, "set_contract": service.set_contract,
                     "revise_schemas": service.revise_schemas, "configure_validation": service.configure_validation,
                     "record_review": service.record_review, "apply_source_draft": workflow.apply}
        activity = {"add_comment": service.add_review_comment, "save_lesson": assistance.save_lesson}
        if operation in mutations:
            result = mutations[operation](*params, **args)
        elif operation in activity:
            item = activity[operation](*params, **args)
            return {"revision_id": revision_id, "status": "recorded", **({"lesson_id": item} if item else {})}
        elif operation == "skip_optimization":
            workflow.skip_optimization(*params, **args)
            return {"revision_id": revision_id, "status": "skipped"}
        elif operation == "apply":
            proposal = self._migration_proposal(args)
            if args.get("expected_pin") != engine.fingerprint([w, project_id, proposal]):
                raise AgentError("conflict", "Preview this exact proposal before explicitly applying it")
            if proposal["base"] != revision_id:
                raise AgentError("conflict", "The proposal belongs to an earlier migration revision")
            approved = {row["id"] for row in assistance.lessons(self.store, w, project_id) if row["status"] == "approved"}
            if set(proposal["rules"]) - approved:
                raise AgentError("conflict", "An approved conversion lesson changed. Prepare a fresh edit")
            result = service.apply(self.store, w, project_id, proposal)
        elif operation == "restore":
            result = service.restore_revision(*params, args["prior_revision"])
        elif operation == "bulk_mappings":
            data = self._migration_upload(args, "csv", "path", engine.MAX_ARTIFACT)
            mappings = {**base["settings"].get("source_mappings", {}), **service.read_source_mappings(data)}
            result = service.revise_schemas(*params, {"source_mappings": mappings})
        elif operation == "import_schema":
            result = self._migration_import_schema(w, project_id, revision_id, base, args)
        elif operation == "resolve_comment":
            service.resolve_review_comment(self.store, w, project_id, args["comment_id"])
            return {"revision_id": revision_id, "status": "resolved"}
        elif operation == "revoke_lesson":
            assistance.revoke_lesson(self.store, w, project_id, args["lesson_id"])
            return {"revision_id": revision_id, "status": "revoked"}
        else:
            raise AgentError("invalid_argument", "Choose a supported migration change")
        return {"project_id": project_id, "revision_id": result["id"], "parent": result["parent"]}

    def _migration_export(self, w, opts, project_id, revision_id, reviewed=False, image_format=None, workbook=False,
                          pilot=None, include_sources=False):
        data = service.bundle(self.store, w, project_id, revision_id, reviewed,
                              image_format=image_format, workbook=workbook, pilot=pilot, include_sources=include_sources)
        return write_artifact(self.store, w, "migration", "zip", data, True,
                              {"project_id": project_id, "revision_id": revision_id}, source_required=True)

    def _migration_provider(self, w, profile_id, *, send):
        profile = get_profile(self.store, w, profile_id)
        if send:
            authorize_provider(self.store, self.policy, w, profile)
        elif profile.key_env and profile.key_env not in self.policy.allowed_credential_refs:
            raise AgentError("credential_unavailable", "Named credential reference is not approved for this launch")
        return self._runtime_manager(w, profile_id, profile) or current_connections()

    def _migration_ai_preview(self, w, opts, project_id, revision_id, profile_id, models, purpose, message,
                              dependencies=False, offset=0):
        with connection_scope(self._migration_provider(w, profile_id, send=False)):
            prepared = assistance.prepare(self.store, w, project_id, revision_id, profile_id, models, purpose, message,
                                          dependencies=dependencies)
        body = {key: prepared[key] for key in ("recipient", "request", "body", "tokens", "scope", "rules")}
        return _payload_reply(opts, body, offset, pin=prepared["pin"], revision_id=revision_id, project_id=project_id)

    def _migration_ai_request(self, w, opts, project_id, revision_id, profile_id, models, purpose, message, expected_pin,
                              dependencies=False):
        def authorize(profile):
            self._workspace(w, write=True, source=True)
            authorize_provider(self.store, self.policy, w, profile)

        with connection_scope(self._migration_provider(w, profile_id, send=True)):
            reply = assistance.dispatch(self.store, w, project_id, revision_id, profile_id, models, purpose, message,
                                        expected_pin, dependencies=dependencies, transport=self.provider_transport,
                                        authorize=authorize)
        if len(compact(reply)) <= opts.max_chars:
            return reply
        return {"revision_id": revision_id, "status": "completed", "reply_exceeds_budget": True,
                "history_enabled": bool(self.store.setting(w, "llm_history", False)),
                "message": "Use saved AI responses when history is enabled, or increase max_chars before a new request."}

    def _migration_stage_preview(self, w, opts, project_id, revision_id, profile_id, source_id, stage,
                                 feedback="", static_reference=False, offset=0):
        with connection_scope(self._migration_provider(w, profile_id, send=False)):
            prepared = workflow.preview(self.store, w, project_id, revision_id, profile_id, source_id, stage,
                                        feedback=feedback, static_reference=static_reference)
        body = {key: prepared[key] for key in ("recipient", "request", "body", "tokens", "scope", "rules")}
        return _payload_reply(opts, body, offset, pin=prepared["pin"], revision_id=revision_id,
                              project_id=project_id, source_id=source_id, stage=stage)

    def _migration_stage_request(self, w, opts, project_id, revision_id, profile_id, source_id, stage, expected_pin,
                                 feedback="", static_reference=False):
        def authorize(profile):
            self._workspace(w, write=True, source=True)
            authorize_provider(self.store, self.policy, w, profile)

        with connection_scope(self._migration_provider(w, profile_id, send=True)):
            workflow.run(self.store, w, project_id, revision_id, profile_id, source_id, stage, expected_pin,
                         feedback=feedback, static_reference=static_reference, transport=self.provider_transport,
                         authorize=authorize)
        return {"revision_id": revision_id, "source_id": source_id, "stage": stage, "status": "completed"}
