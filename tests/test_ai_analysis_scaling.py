"""Exact-source semantic paging and lossless review continuation."""

from dataclasses import asdict

import pytest

from dataforge.ai_analysis_models import AnalysisUnit


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
