"""Static Databricks pipeline syntax and script-local relation names."""
from __future__ import annotations

from dataclasses import dataclass

from sqlglot import Dialect, exp
from sqlglot.dialects.databricks import Databricks
from sqlglot.errors import ErrorLevel, ParseError
from sqlglot.optimizer.scope import Scope
from sqlglot.tokens import TokenType


def is_native_dialect(dialect: Dialect) -> bool:
    """Keep the pipeline grammar out of callers with an instance-local parser, such as PROC SQL."""
    return isinstance(dialect, Databricks) and dialect.parser_class is Databricks.parser_class


def static_table(table: exp.Expression | None) -> bool:
    return (isinstance(table, exp.Table) and 1 <= len(table.parts) <= 3
            and all(isinstance(part, exp.Identifier) for part in table.parts))


def column_parts(node: exp.Expression) -> list[exp.Expression]:
    """Keep field segments in Databricks paths that extend past SQLGlot's Column width."""
    suffix = []
    while isinstance(node, (exp.Dot, exp.Paren)):
        if isinstance(node, exp.Dot):
            if not isinstance(node.expression, (exp.Identifier, exp.Star)):
                return []
            suffix.append(node.expression)
        node = node.this
    return [*node.parts, *reversed(suffix)] if isinstance(node, exp.Column) else []


def qualified_source(mapping: dict[str, exp.Table | Scope], parts: list[exp.Expression]) -> tuple[exp.Table | Scope | None, int]:
    """Consume the longest visible relation qualifier, leaving nested field segments intact."""
    if len(parts) < 2:
        return None, 0
    for length in range(min(3, len(parts) - 1), 1, -1):
        prefix = [part.name.casefold() for part in parts[:length]]
        matches = {id(source): source for source in mapping.values()
                   if isinstance(source, exp.Table) and not source.alias
                   and [part.name.casefold() for part in source.parts][-length:] == prefix}
        if len(matches) == 1:
            return next(iter(matches.values())), length
    matches = [source for name, source in mapping.items() if name.casefold() == parts[0].name.casefold()]
    return (matches[0], 1) if len(matches) == 1 else (None, 0)


@dataclass
class Namespace:
    """Track names supplied explicitly by USE directives within one script."""

    catalog: exp.Identifier | None = None
    schema: exp.Identifier | None = None

    def use(self, tree: exp.Use) -> str | None:
        kind = tree.args.get("kind")
        kind = kind.name.upper() if kind else "SCHEMA"
        table = tree.this
        if kind not in {"CATALOG", "DATABASE", "SCHEMA"}:
            return "Unsupported Databricks USE directive"
        parts = table.parts if static_table(table) and not table.alias else []
        if kind == "CATALOG":
            if len(parts) == 1:
                self.catalog, self.schema = table.this, exp.to_identifier("default")
                return None
            self.catalog = self.schema = None
        elif 1 <= len(parts) <= 2:
            if table.args.get("db"):
                self.catalog = table.args["db"]
            self.schema = table.this
            return None
        else:
            self.catalog = self.schema = None
        return "Dynamic or unsupported Databricks USE namespace"

    def bind(self, table: exp.Table) -> None:
        if not static_table(table) or table.args.get("catalog"):
            return
        if self.schema is not None and not table.args.get("db"):
            table.set("db", self.schema.copy())
        if self.catalog is not None and table.args.get("db"):
            table.set("catalog", self.catalog.copy())


def ddl_schema_property(prop: exp.Expression) -> bool:
    return (isinstance(prop, (exp.StreamingTableProperty, exp.MaterializedProperty))
            or isinstance(prop, exp.FileFormatProperty) and prop.name.upper() == "DELTA")


class _PipelineParser(Databricks.parser_class):
    """Lower supported pipeline clauses to existing SQLGlot relation/query nodes."""

    def _parse_constraint(self):
        index = self._index
        start = self._curr.start
        if self._match(TokenType.CONSTRAINT) and (name := self._parse_id_var()) and self._match_text_seq("EXPECT"):
            predicate = self._parse_wrapped(self._parse_disjunction)
            if predicate is None:
                self.raise_error("Expected a Databricks expectation predicate")
            policy = "warn"
            if self._match_text_seq("ON", "VIOLATION"):
                if self._match_text_seq("DROP", "ROW"):
                    policy = "drop"
                elif self._match_text_seq("FAIL", "UPDATE"):
                    policy = "fail"
                else:
                    self.raise_error("Expected DROP ROW or FAIL UPDATE after ON VIOLATION")
            constraint = exp.Constraint(this=name, expressions=[predicate])
            constraint.meta["databricks_expectation"] = (policy, self.sql[start:self._prev.end + 1])
            return constraint
        self._retreat(index)
        return super()._parse_constraint()

    def _parse_stream(self):
        index = self._index
        if self._match(TokenType.STREAM) and not self._match(TokenType.L_PAREN, advance=False):
            source = self._try_parse(self._parse_table_parts)
            if isinstance(source, exp.Table) and self._parse_stream_options():
                return exp.Stream(this=source, alias=self._parse_table_alias())
        self._retreat(index)
        stream = super()._parse_stream()
        if stream is not None and self._parse_stream_options():
            if alias := self._parse_table_alias():
                stream.set("alias", alias)
        return stream

    def _parse_stream_options(self):
        if self._match_pair(TokenType.WITH, TokenType.L_PAREN, advance=False):
            self._advance()
            self._parse_wrapped_csv(self._parse_assignment)
            return True
        return False

    def _parse_create(self):
        index = self._index
        if self._match_text_seq("FLOW") and self._parse_id_var():
            if self._match(TokenType.COMMENT) and not self._parse_string():
                self.raise_error("Expected a flow comment string")
            if self._match_text_seq("AS", "AUTO", "CDC"):
                self._match_text_seq("ONCE")
                self._cdc_require("INTO")
                target = self._parse_table_parts()
                query = self._parse_cdc_query()
                return exp.Insert(this=target, expression=query)
        self._retreat(index)
        return super()._parse_create()

    def _parse_ddl_select(self):
        if self._match_text_seq("FLOW", "AUTO", "CDC"):
            self._match_text_seq("ONCE")
            return self._parse_cdc_query()
        return super()._parse_ddl_select()

    def _cdc_require(self, *words):
        if not self._match_text_seq(*words):
            raise ParseError("Expected " + " ".join(words) + " in AUTO CDC flow")

    def _cdc_columns(self):
        if self._match(TokenType.STAR):
            except_ = self._cdc_column_list() if self._match(TokenType.EXCEPT) else []
            return [exp.Star(except_=except_ or None)]
        return self._cdc_column_list()

    def _cdc_column_list(self):
        names = self._parse_wrapped_id_vars()
        if not names:
            raise ParseError("Expected at least one AUTO CDC column")
        return [exp.Column(this=name) for name in names]

    def _parse_cdc_query(self):
        from_start = self._curr.start
        self._cdc_require("FROM")
        stream = self._match(TokenType.STREAM)
        if self._match_text_seq("SNAPSHOT", advance=False):
            raise ParseError("AUTO CDC FROM SNAPSHOT is outside the supported change-feed grammar")
        source = self._parse_wrapped(self._parse_table_parts, optional=True) if stream else self._parse_table_parts()
        if stream:
            self._parse_stream_options()
        from_evidence = self.sql[from_start:self._prev.end + 1]

        self._cdc_require("KEYS")
        controls = [("match_key", key) for key in self._cdc_column_list()]
        if self._match_text_seq("IGNORE", "NULL", "UPDATES"):
            columns = self._cdc_columns() if self._match(TokenType.ON) else [exp.Star()]
            controls.extend(("ignore_null_update", col) for col in columns)
        for clause, role in (("DELETE", "delete_condition"), ("TRUNCATE", "truncate_condition")):
            if self._match_text_seq("APPLY", "AS", clause, "WHEN"):
                controls.append((role, self._parse_disjunction()))
        self._cdc_require("SEQUENCE", "BY")
        controls.append(("sequence", self._parse_disjunction()))
        if self._match_text_seq("SYSTEM", "SEQUENCE", "BY"):
            controls.append(("system_sequence", self._parse_disjunction()))

        projections, evidence = [exp.Star()], {}
        if self._match_text_seq("COLUMNS"):
            start = self._curr.start
            projections = self._cdc_columns()
            if isinstance(projections[0], exp.Star):
                projections[0].meta.update(start=start, end=self._prev.end)
                evidence[id(projections[0])] = self.sql[start:self._prev.end + 1]
            else:
                for column in projections:
                    evidence[id(column)] = self.sql[column.this.meta["start"]:column.this.meta["end"] + 1]
        else:
            evidence[id(projections[0])] = from_evidence

        tracks_history = False
        if self._match_text_seq("STORED", "AS"):
            if not self._match_text_seq("BITEMPORAL"):
                self._cdc_require("SCD", "TYPE")
                tracks_history = self._match_text_seq("2")
                if not tracks_history and not self._match_text_seq("1"):
                    raise ParseError("Expected SCD TYPE 1 or SCD TYPE 2")
        if self._match_text_seq("TRACK", "HISTORY", "ON"):
            controls.extend(("history", column) for column in self._cdc_columns())
        elif tracks_history:
            controls.append(("history", exp.Star()))
        if self._curr or any(node is None for _, node in controls):
            raise ParseError("Unsupported or incomplete AUTO CDC clause")

        query = exp.Select(expressions=projections, from_=exp.From(this=source))
        query.meta["databricks_cdc"] = {
            "databricks_insert_by_name": True, "databricks_controls": controls, "databricks_evidence": evidence,
        }
        return query


def parse_statement(code: str, dialect: Databricks) -> exp.Expression | None:
    """Parse the original source with Databricks extensions scoped to one invocation."""
    tokens = dialect.tokenize(code)
    if tokens and tokens[0].token_type == TokenType.CREATE:
        head = 1
        if [token.text.upper() for token in tokens[head:head + 2]] in (["OR", "REFRESH"], ["OR", "REPLACE"]):
            head += 2
        if head < len(tokens) and tokens[head].text.upper() == "STREAMING":
            head += 1
        if head + 1 < len(tokens) and tokens[head].text.upper() == "LIVE" and tokens[head + 1].token_type == TokenType.TABLE:
            # Legacy DLT spelling. Keeping the remaining offsets preserves original evidence.
            del tokens[head]
    parsed = _PipelineParser(dialect=dialect, error_level=ErrorLevel.RAISE).parse(tokens, code)
    if len(parsed) > 1:
        return exp.Block(expressions=parsed)
    return parsed[0] if parsed else None


def normalize_statement(tree: exp.Expression) -> list[str]:
    """Prepare extensions before SQLGlot scopes are built, retaining original AST offsets."""
    diagnostics = []
    for stream in list(tree.find_all(exp.Stream)):
        source = stream.this
        aliases = [stream.args["alias"]] if stream.args.get("alias") else []
        pivots = []
        if isinstance(source, exp.Subquery):
            pivots = source.args.get("pivots", [])
            if source.args.get("alias"):
                aliases.append(source.args["alias"])
            source = source.this
        if isinstance(source, exp.Table) and source.args.get("alias"):
            aliases.append(source.args["alias"])
        alias = aliases[0] if aliases else None
        if static_table(source) and not source.args.get("joins") and len(aliases) <= 1:
            if alias is not None:
                source.set("alias", alias)
            if pivots:
                source.set("pivots", [*source.args.get("pivots", []), *pivots])
            stream.replace(source)
            continue
        diagnostics.append("Dynamic or unsupported Databricks STREAM source; physical relation cannot be established")
        stream.replace(exp.Table(this=exp.Anonymous(this="STREAM"), alias=alias))

    query = tree.expression
    if isinstance(query, exp.Select) and query.meta.get("databricks_cdc"):
        tree.meta.update(query.meta["databricks_cdc"])
        if not static_table(query.args["from_"].this):
            diagnostics.append("Dynamic or unsupported Databricks AUTO CDC source")
    if isinstance(tree, exp.Create) and isinstance(tree.this, exp.Schema):
        kept, rules = [], []
        for column in tree.this.expressions:
            rule = column.meta.get("databricks_expectation")
            if rule is None:
                kept.append(column)
                continue
            policy, evidence = rule
            rules.append((column.name, policy, column.expressions[0], evidence))
        if rules:
            if kept:
                tree.this.set("expressions", kept)
            else:
                tree.set("this", tree.this.this)
            tree.meta["databricks_expectations"] = rules
    return diagnostics
