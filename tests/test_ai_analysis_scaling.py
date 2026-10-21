"""Exact-source semantic paging and lossless review continuation."""

import json
from dataclasses import asdict

import pytest

from dataforge.ai_analysis_models import AnalysisRequest, AnalysisUnit


def unit(code):
    return AnalysisUnit(
        unit_id="u",
        file_id="f",
        content_hash="h",
        path="q.sql",
        extension=".sql",
        first=1,
        last=code.count("\n") + 1,
        start_offset=0,
        end_offset=len(code),
        code=code,
    )


def test_projection_pages_keep_original_shared_context_and_ordinals():
    from dataforge.ai_semantic import source_view, split_projection_unit

    code = (
        "CREATE TABLE b AS SELECT a.x AS x, a.y+1 AS y, a.z AS z FROM a JOIN c ON a.id=c.id WHERE a.flag=1;"
    )
    original = unit(code)
    left, right = split_projection_unit(original)
    pages = (
        [*split_projection_unit(left), right]
        if left.focus.ordinal_end > 1
        else [left, *split_projection_unit(right)]
    )
    assert len(pages) == 3
    assert [(p.focus.ordinal_start, p.focus.ordinal_end) for p in pages] == [(0, 1), (1, 2), (2, 3)]
    for page in pages:
        assert page.code == code
        view = source_view(page)
        assert all(code[s["start_offset"] : s["end_offset"]] == s["code"] for s in view)
        assert "JOIN c ON a.id=c.id WHERE a.flag=1" in view[-1]["code"]
        assert len(view) == 3
    assert len({p.unit_id for p in pages}) == 3
    assert split_projection_unit(pages[0]) == ()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT DISTINCT a.x, a.y FROM a;",
        "SELECT a.x AS x, x+1 AS y FROM a;",
        "SELECT a.x AS x, a.y AS x FROM a;",
        "SELECT a.x, a.y FROM a ORDER BY 2;",
        "SELECT a.x, sum(a.y) FROM a GROUP BY a.x;",
        "WITH q AS (SELECT x,y FROM a) SELECT x,y FROM q;",
        "SELECT a.x, (SELECT max(y) FROM b) AS y FROM a;",
        "INSERT INTO b(x,y) SELECT a.x,a.y FROM a;",
        "SELECT a.*, a.x FROM a;",
    ],
)
def test_interdependent_or_ambiguous_projection_shapes_stay_indivisible(sql):
    from dataforge.ai_semantic import split_projection_unit

    assert split_projection_unit(unit(sql)) == ()


def test_focus_restricts_host_facts_but_preserves_contextual_dependencies():
    from dataforge.ai_semantic import focused_operation, split_projection_unit
    from dataforge.parsers.sql import parse_sql

    code = "CREATE TABLE b AS SELECT a.x AS x, a.y AS y FROM a JOIN c ON a.id=c.id WHERE a.flag=1;"
    left, right = split_projection_unit(unit(code))
    op = parse_sql(code).operations[0]
    a, b = focused_operation(op, left), focused_operation(op, right)
    assert [d["ordinal"] for d in a.derivations] == [0]
    assert [d["ordinal"] for d in b.derivations] == [1]
    assert {u.column for u in b.usages} == {"y"}
    assert b.table_pairs == []
    roles = {i["role"] for i in b.derivations[0]["inputs"]}
    assert {"value", "join", "row_filter", "rowset"} <= roles
    assert len(op.derivations) == 2
    assert asdict(op)["code"] == code


def test_review_batches_account_for_every_candidate_including_large_singletons():
    from dataforge.ai_analysis_models import EvidenceCitation, NormalizedFact
    from dataforge.llm import review_batches

    evidence = EvidenceCitation.from_unit(unit("select 1;"))
    facts = [
        NormalizedFact(
            kind="derivation",
            unit_id="u",
            evidence_key="k",
            evidence=evidence,
            candidate_id=str(i),
            table="b",
            column="x" + str(i),
            expression="x" * (3000 if i == 4 else 500),
        )
        for i in range(12)
    ]
    batches = review_batches(facts)
    ids = [c["candidate_id"] for b in batches for c in b]
    assert ids == [f.candidate_id for f in facts]
    assert len(batches) > 1
    assert any(len(b) == 1 and b[0]["candidate_id"] == "4" for b in batches)
    assert all(
        len(json.dumps(b, ensure_ascii=False, separators=(",", ":"))) <= 2000 or len(b) == 1 for b in batches
    )


def test_full_envelope_splits_wide_operation_and_rejects_cross_focus_claim(tmp_path):
    from dataforge.ai_analysis_models import (
        Coverage,
        DerivationCandidate,
        DerivationInput,
        EvidenceCitation,
        ProjectLineageResponse,
        ValidationContext,
    )
    from dataforge.ai_validation import validate_project_response
    from dataforge.analysis_service import _prepare
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile, analysis_prompt
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("wide")
    expressions = [f"a.x{i} + " + " + ".join("1" for _ in range(30)) + f" AS c{i}" for i in range(36)]
    code = "CREATE TABLE b AS SELECT " + ", ".join(expressions) + " FROM a;"
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    p = Profile(
        provider="Ollama", base_url="http://localhost:11434", model="m", retries=0, context_chars=11000
    )
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "m", p.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.set_setting(w, "max_context_chars", 11000)
    prepared, plan, execution, preview = _prepare(store, w, AnalysisRequest(mode="hybrid"))
    assert preview["valid"], preview["blocked"]
    assert len(plan.units) > 1
    assert sum(u.focus.ordinal_end - u.focus.ordinal_start for u in plan.units) == 36
    for u in plan.units:
        execution.catalog = plan.context_for(u)
        system, user, _ = analysis_prompt(u, "project_lineage", execution)
        assert len(system) + len(user) <= 11000
        context = json.loads(user[user.index("{") :])
        assert "code" not in context["unit"]
        assert len(context["source_segments"]) == 3
    first = plan.units[0]
    bad = ProjectLineageResponse(
        unit_id=first.unit_id,
        coverage=Coverage(status="complete"),
        derivations=[
            DerivationCandidate(
                target_table="b",
                target_column="c35",
                expression=expressions[35],
                ordinal=35,
                category="expression",
                inputs=[DerivationInput(table="a", column="x35")],
                evidence=EvidenceCitation.from_unit(first),
            )
        ],
    )
    result = validate_project_response(bad, ValidationContext(unit=first, workspace_id=w, source_text=code))
    assert not result.accepted and result.rejected
    store.close()


def test_large_static_proc_sql_pages_complete_statements_without_stateful_split():
    from dataforge.ai_context import PreparedAnalysis, SourceSnapshot, plan_ai_units

    sql = (
        "proc sql; "
        + " ".join("create table b" + str(i) + " as select x from a;" for i in range(12))
        + " quit;"
    )
    prepared = PreparedAnalysis(
        workspace="w",
        request=AnalysisRequest(mode="hybrid"),
        sources=(SourceSnapshot("f", "h", "q.sas", ".sas", "job", sql),),
        settings_json="{}",
    )
    plan = plan_ai_units(prepared, max_chars=100)
    assert plan.valid and len(plan.units) == 12
    assert all(sql[u.start_offset : u.end_offset] == u.code for u in plan.units)
    for header in ("proc sql noprint;", "proc sql; connect to oracle;"):
        unsafe = prepared.__class__(
            **{
                **prepared.__dict__,
                "sources": (
                    SourceSnapshot("f", "h", "q.sas", ".sas", "job", sql.replace("proc sql;", header)),
                ),
            }
        )
        assert plan_ai_units(unsafe, max_chars=100).blocked


def test_review_batches_resume_after_reopen_without_repeating_completed_batch(tmp_path):
    import httpx

    from dataforge.ai_analysis_models import (
        Coverage,
        DerivationCandidate,
        DerivationInput,
        EvidenceCitation,
        LineageReviewResponse,
        ProjectLineageResponse,
    )
    from dataforge.ai_wire import encode_project_result
    from dataforge.analysis_service import preview_analysis, run_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile
    from dataforge.store import Store

    code = "UPDATE b SET " + ", ".join(f"c{i}=a.x{i}" for i in range(24)) + " FROM a;"
    store = Store(tmp_path)
    w = store.create_workspace("batch review")
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    profile = Profile(
        provider="Ollama", base_url="http://localhost:11434", model="m", retries=0, context_chars=100000
    )
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "m", profile.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.set_setting(w, "max_context_chars", 100000)
    extraction = []
    reviews = []

    def respond(request):
        context = json.loads(json.loads(request.content)["messages"][-1]["content"].split("\n\n", 1)[1])
        u = AnalysisUnit.model_validate(context["unit"])
        task = "lineage_review" if "candidates" in context else "project_lineage"
        evidence = EvidenceCitation.from_unit(u)
        if task == "project_lineage":
            extraction.append(u.unit_id)
            result = ProjectLineageResponse(
                unit_id=u.unit_id,
                coverage=Coverage(status="complete"),
                derivations=[
                    DerivationCandidate(
                        target_table="b",
                        target_column=f"c{i}",
                        expression=f"a.x{i}",
                        ordinal=i,
                        category="direct",
                        expression_start_offset=code.index(f"=a.x{i}") + 1,
                        expression_end_offset=code.index(f"=a.x{i}") + 1 + len(f"a.x{i}"),
                        inputs=[DerivationInput(table="a", column=f"x{i}")],
                        evidence=evidence,
                    )
                    for i in range(24)
                ],
            )
        else:
            ids = [c["candidate_id"] for c in context["candidates"]]
            reviews.extend(ids)
            result = LineageReviewResponse(
                decisions=[
                    {"candidate_id": cid, "decision": "supported", "evidence": [evidence.model_dump()]}
                    for cid in ids
                ]
            )
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(encode_project_result(result))},
                "done_reason": "stop",
                "prompt_eval_count": 100,
                "eval_count": 100,
            },
        )

    transport = httpx.MockTransport(respond)
    first = run_analysis(
        store,
        w,
        AnalysisRequest(mode="ai", additional_ai_review=True, max_provider_attempts=2),
        transport=transport,
    )
    assert first.status == "awaiting_continuation", first.reasons
    assert len(extraction) == 1 and 0 < len(reviews) < 24
    assert not store.rows("SELECT * FROM analysis_runs")
    run_id = first.run_id
    store.close()
    store = Store(tmp_path)
    for _ in range(30):
        preview = preview_analysis(
            store, w, AnalysisRequest(mode="ai", resume_run_id=run_id, max_provider_attempts=1)
        )
        assert preview["valid"], preview["blocked"]
        result = run_analysis(
            store,
            w,
            AnalysisRequest(mode="ai", resume_run_id=run_id, max_provider_attempts=1),
            transport=transport,
        )
        if result.status == "committed":
            break
        assert result.status == "awaiting_continuation", result.reasons
    assert result.status == "committed" and result.complete, result.reasons
    assert result.counts["accepted"] == 24
    assert len(extraction) == 1 and len(reviews) == len(set(reviews)) == 24
    assert len(store.rows("SELECT * FROM analysis_runs")) == 1
    store.close()


def test_wide_query_real_transport_preserves_every_projection_and_one_writer(tmp_path):
    import httpx

    from dataforge.analysis_service import run_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("HTTP wide")
    expressions = [f"a.x{i} + " + " + ".join("1" for _ in range(30)) + f" AS c{i}" for i in range(36)]
    code = "CREATE TABLE b AS SELECT " + ", ".join(expressions) + " FROM a;"
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    profile = Profile(
        provider="OpenAI compatible",
        base_url="http://localhost:1234",
        model="m",
        retries=0,
        context_chars=11000,
    )
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "m", profile.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.set_setting(w, "max_context_chars", 11000)
    seen = []

    def respond(request):
        body = json.loads(request.content)
        context = json.loads(body["messages"][1]["content"].split("\n\n", 1)[1])
        assert len(body["messages"][0]["content"]) + len(body["messages"][1]["content"]) <= 11000
        u = context["unit"]
        focus = u["focus"]
        assert all(code[s["start_offset"] : s["end_offset"]] == s["code"] for s in context["source_segments"])
        seen.extend(range(focus["ordinal_start"], focus["ordinal_end"]))
        payload = {
            "unit_id": u["unit_id"],
            "coverage": {"status": "complete"},
            "derivations": [
                {
                    "target_table": "b",
                    "target_column": f"c{i}",
                    "expression": expressions[i],
                    "ordinal": i,
                    "category": "expression",
                    "inputs": [{"table": "a", "column": f"x{i}"}],
                    "evidence": context["evidence_reference"],
                }
                for i in range(focus["ordinal_start"], focus["ordinal_end"])
            ],
        }
        if focus["ordinal_start"] == 0:
            payload["relationships"] = [
                {
                    "source": "a",
                    "target": "b",
                    "operation": "CREATE",
                    "evidence": context["evidence_reference"],
                }
            ]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            },
        )

    transport = httpx.MockTransport(respond)
    first = run_analysis(store, w, AnalysisRequest(mode="ai", max_provider_attempts=1), transport=transport)
    assert first.status == "awaiting_continuation", first.reasons
    run_id = first.run_id
    store.close()
    store = Store(tmp_path)
    for _ in range(36):
        result = run_analysis(
            store,
            w,
            AnalysisRequest(mode="ai", resume_run_id=run_id, max_provider_attempts=1),
            transport=transport,
        )
        if result.status == "committed":
            break
        assert result.status == "awaiting_continuation", result.reasons
    assert result.status == "committed" and result.complete, result.reasons
    assert seen == list(range(36))
    assert store.rows("SELECT count(*) AS n FROM column_derivations")[0]["n"] == 36
    assert store.rows("SELECT count(DISTINCT operation_id) AS n FROM column_derivations")[0]["n"] == 1
    assert store.rows("SELECT count(*) AS n FROM analysis_runs")[0]["n"] == 1
    assert result.usage_known
    assert store.rows("SELECT DISTINCT version FROM prompt_versions WHERE task='project_lineage'") == [
        {"version": "4"}
    ]
    store.close()


def test_projection_segments_bind_unicode_literals_comments_and_absolute_offsets():
    from dataforge.ai_semantic import source_view, split_projection_unit

    code = "CREATE TABLE b AS SELECT concat('α,β', a.x) AS x, /* comma , */ a.y AS y FROM a;"
    original = unit(code)
    original = original.model_copy(update={"start_offset": 17, "end_offset": 17 + len(code)})
    pages = split_projection_unit(original)
    assert len(pages) == 2
    for page in pages:
        for segment in source_view(page):
            assert code[segment["start_offset"] - 17 : segment["end_offset"] - 17] == segment["code"]
    assert "'α,β'" in source_view(pages[0])[1]["code"]
    assert "a.y AS y" in source_view(pages[1])[1]["code"]


def test_forged_projection_bounds_fail_before_source_dispatch():
    from dataforge.ai_semantic import source_view, split_projection_unit

    page = split_projection_unit(unit("SELECT a.x AS x, a.y AS y FROM a;"))[0]
    bad = page.model_copy(
        update={"focus": page.focus.model_copy(update={"end_offset": page.focus.end_offset + 1})}
    )
    with pytest.raises(ValueError, match="partition"):
        source_view(bad)


def test_repeated_input_column_does_not_authorize_omitted_sibling_expression():
    from dataforge.ai_analysis_models import (
        ColumnCandidate,
        EvidenceCitation,
        ProjectLineageResponse,
        ValidationContext,
    )
    from dataforge.ai_semantic import focused_operation, split_projection_unit
    from dataforge.ai_validation import validate_project_response
    from dataforge.parsers.sql import parse_sql

    code = "CREATE TABLE b AS SELECT a.x+1 AS x, a.x+2 AS y FROM a;"
    page = split_projection_unit(unit(code))[0]
    parsed = parse_sql(code)
    scoped = focused_operation(parsed.operations[0], page)
    assert [u.expression for u in scoped.usages] == ["a.x + 1"]
    response = ProjectLineageResponse(
        unit_id=page.unit_id,
        columns=[
            ColumnCandidate(
                table="a",
                column="x",
                context="SELECT",
                expression="a.x+2",
                evidence=EvidenceCitation.from_unit(page),
            )
        ],
    )
    result = validate_project_response(
        response, ValidationContext(unit=page, workspace_id="w", source_text=code, parser_result=parsed)
    )
    assert not result.accepted and result.rejected


def test_changed_shorter_source_is_sanitized_stale_before_plan_hydration(tmp_path, monkeypatch):
    from dataforge.ai_analysis_models import ProjectLineageResponse, UnitAttemptResult
    from dataforge.analysis_service import preview_analysis, run_analysis
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("changed snapshot")
    Importer(store, w).files([("q.sql", b"SELECT 123456789; SELECT 987654321;")], {".sql"})
    p = Profile(
        provider="Ollama", base_url="http://localhost:11434", model="m", retries=0, context_chars=100000
    )
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "m", p.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.set_setting(w, "max_context_chars", 100000)
    monkeypatch.setattr(
        "dataforge.analysis_service.invoke_analysis_unit",
        lambda s, w, u, t, e: UnitAttemptResult(
            unit_id=u.unit_id, task=t, result=ProjectLineageResponse(unit_id=u.unit_id)
        ),
    )
    first = run_analysis(store, w, AnalysisRequest(mode="hybrid", max_provider_attempts=1))
    assert first.status == "awaiting_continuation"
    Importer(store, w).files([("q.sql", b"SELECT 1;")], {".sql"})
    with pytest.raises(ValueError, match="^source_or_configuration_changed$"):
        preview_analysis(store, w, AnalysisRequest(mode="hybrid", resume_run_id=first.run_id))
    resumed = run_analysis(store, w, AnalysisRequest(mode="hybrid", resume_run_id=first.run_id))
    assert resumed.status == "stale" and resumed.reasons == ["source_or_configuration_changed"]
    assert (
        store.rows("SELECT status FROM ai_analysis_runs WHERE run_id=?", [first.run_id])[0]["status"]
        == "stale"
    )
    assert not store.rows("SELECT * FROM analysis_runs")
    store.close()


@pytest.mark.parametrize(
    "sql,dialect",
    [
        ("CREATE TABLE b AS SELECT TOP 10 a.x AS x,a.y AS y FROM a;", "tsql"),
        ("CREATE TABLE b AS SELECT 1 AS x,2 AS y WHERE 1=0;", ""),
        ("CREATE TABLE b AS SELECT a.x AS x,a.y AS y FROM a WHERE x>0;", ""),
    ],
)
def test_select_modifiers_and_sibling_clause_aliases_remain_indivisible(sql, dialect):
    from dataforge.ai_semantic import split_projection_unit

    assert split_projection_unit(unit(sql), dialect) == ()


def test_projection_cardinality_is_paged_even_when_context_fits(tmp_path):
    from dataforge.analysis_service import _prepare
    from dataforge.ingestion import Importer
    from dataforge.llm import Profile
    from dataforge.store import Store

    store = Store(tmp_path)
    w = store.create_workspace("response ceiling")
    code = "CREATE TABLE b AS SELECT " + ",".join(f"a.x{i} AS x{i}" for i in range(140)) + " FROM a;"
    Importer(store, w).files([("q.sql", code.encode())], {".sql"})
    profile = Profile(
        provider="Ollama", base_url="http://localhost:11434", model="m", retries=0, context_chars=100000
    )
    store.execute("INSERT INTO llm_profiles VALUES (?,?,?,?)", ["p", w, "m", profile.model_dump_json()])
    store.set_setting(w, "default_profile", "p")
    store.set_setting(w, "max_context_chars", 100000)
    _, plan, _, preview = _prepare(store, w, AnalysisRequest(mode="hybrid"))
    assert preview["valid"] and len(plan.units) > 1
    assert sum(u.focus.ordinal_end - u.focus.ordinal_start for u in plan.units) == 140
    assert all(u.focus.ordinal_end - u.focus.ordinal_start <= 100 for u in plan.units)
    store.close()


@pytest.mark.parametrize(
    "sql,dialect",
    [
        ("CREATE TABLE b AS SELECT 1 AS x,2 AS y CONNECT BY LEVEL<=3;", "oracle"),
        ("CREATE TABLE b AS SELECT SQL_CALC_FOUND_ROWS a.x AS x,a.y AS y FROM a;", "mysql"),
        ("CREATE TABLE b AS SELECT a.x AS x,a.y AS y FROM a FOR UPDATE;", "postgres"),
    ],
)
def test_unrecognized_select_clauses_never_become_omitted_projection_text(sql, dialect):
    from dataforge.ai_semantic import split_projection_unit

    assert split_projection_unit(unit(sql), dialect) == ()


def test_reserved_from_column_cannot_end_the_projection_list():
    from dataforge.ai_semantic import source_view, split_projection_unit

    code = "CREATE TABLE b AS SELECT a.x AS x,a.from AS y FROM a;"
    left, right = split_projection_unit(unit(code), "postgres")
    assert source_view(right, "postgres")[1]["code"] == "a.from AS y"
    assert source_view(left, "postgres")[-1]["code"].strip() == "FROM a;"
