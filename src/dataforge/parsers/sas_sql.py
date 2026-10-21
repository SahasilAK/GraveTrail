"""SAS SELECT attributes and calculated aliases over the configured SQLGlot dialect."""
import re
from collections import Counter

from sqlglot import Dialect, exp
from sqlglot.errors import ParseError
from sqlglot.parser import Parser
from sqlglot.tokens import Token, TokenType

from dataforge.models import Diagnostic, ParseResult
from dataforge.parsers.sql import parse_sql

FORMAT_VALUE = re.compile(r'\$?(?:[A-Za-z_]\w*|[0-9]+)\.[0-9]*(?![\w.])')


def parse_proc_sql(statement: str, sql_dialect: str = '') -> ParseResult:
    """Parse one SAS PROC SQL statement with SAS projection attributes enabled.

    Args:
        statement: PROC SQL source statement.
        sql_dialect: SQLGlot dialect name used for SQL syntax.

    Returns:
        SQL parse result with SAS-specific alias diagnostics included.
    """
    dialect = Dialect.get_or_raise(sql_dialect)
    diagnostics = []

    class SASParser(dialect.parser_class):
        """Dialect parser override for SAS FORMAT, LENGTH, and CALCULATED syntax."""

        FUNCTIONS = {**dialect.parser_class.FUNCTIONS,
                     'DATETIME': lambda args: exp.Anonymous(this='DATETIME', expressions=args)}

        def _parse_projections(self: Parser) -> tuple[list[exp.Expr], list[exp.Expr] | None]:
            """Parse projections while marking their expression context.

            Args:
                self: SQLGlot parser instance.

            Returns:
                Projection expressions and an optional projection alias list.
            """
            previous = getattr(self, '_sas_projection', False)
            self._sas_projection = True
            try:
                return super()._parse_projections()
            finally:
                self._sas_projection = previous

        def _parse_expression(self: Parser) -> exp.Expr | None:
            """Parse a SAS projection expression and its surrounding attributes.

            Args:
                self: SQLGlot parser instance.

            Returns:
                Parsed expression, or ``None`` when the parser has no expression.
            """
            if not getattr(self, '_sas_projection', False):
                return super()._parse_expression()
            # Nested expression contexts keep their dialect grammar, including WHERE.
            self._sas_projection = False
            try:
                expression = self._parse_assignment()
                self._parse_sas_attributes()
                expression = self._parse_alias(expression)
                self._parse_sas_attributes()
                return expression
            finally:
                self._sas_projection = True

        def _parse_sas_attributes(self: Parser) -> None:
            """Consume supported SAS FORMAT and LENGTH projection attributes.

            Args:
                self: SQLGlot parser instance.

            Raises:
                ParseError: If an attribute does not use supported literal syntax.
            """
            while (self._curr.token_type in {TokenType.FORMAT, TokenType.VAR}
                   and self._curr.text.upper() in {'FORMAT', 'LENGTH'}
                   and self._next.token_type == TokenType.EQ):
                name = self._curr.text.upper()
                self._advance(2)
                if name == 'LENGTH':
                    if self._curr.token_type != TokenType.NUMBER or not re.fullmatch(r'[1-9][0-9]*', self._curr.text):
                        raise ParseError('Expected a positive literal SAS column length')
                    self._advance()
                else:
                    value = FORMAT_VALUE.match(self.sql, self._curr.start)
                    if not value:
                        raise ParseError('Expected a literal SAS format ending in a period or decimal precision')
                    while self._index < self._tokens_size and self._curr.start < value.end():
                        self._advance()

        def _parse_column(self: Parser) -> exp.Expr | None:
            """Parse CALCULATED aliases as derived variables in projection context.

            Args:
                self: SQLGlot parser instance.

            Returns:
                Parsed column expression, or ``None`` when no column is present.
            """
            if (self._curr.token_type == TokenType.VAR and self._curr.text.upper() == 'CALCULATED'
                    and self._next.token_type in self.ID_VAR_TOKENS):
                self._advance()
                line = self._curr.line
                alias = self._parse_id_var(any_token=False)
                # A calculated alias is a derived variable, never a direct base-table column.
                variable = exp.Var(this=alias.name)
                variable.meta.update(sas_calculated=True, sas_line=line)
                return variable
            return super()._parse_column()

        def parse(self: Parser, raw_tokens: list[Token], sql: str | None = None) -> list[exp.Expr | None]:
            """Parse tokens and diagnose missing or ambiguous CALCULATED aliases.

            Args:
                raw_tokens: SQLGlot tokens for the statement.
                sql: Original SQL text associated with the tokens, when available.

            Returns:
                Parsed expression trees, including ``None`` for empty statements.
            """
            trees = super().parse(raw_tokens, sql)
            for tree in trees:
                if tree is None:
                    continue
                for variable in tree.find_all(exp.Var):
                    if not variable.meta.get('sas_calculated'):
                        continue
                    select = variable.find_ancestor(exp.Select)
                    aliases = Counter(p.alias.casefold() for p in select.expressions if isinstance(p, exp.Alias)) if select else {}
                    if aliases.get(variable.name.casefold()) != 1:
                        diagnostics.append(Diagnostic('Unresolved or ambiguous SAS CALCULATED alias',
                            variable.meta['sas_line'], symbol=variable.name))
            return trees

    # Instance-local parser customization leaves SQL files and the dialect registry untouched.
    dialect.parser_class = SASParser
    result = parse_sql(statement, dialect)
    result.diagnostics.extend(diagnostics)
    return result
