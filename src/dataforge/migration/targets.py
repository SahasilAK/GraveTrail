"""The dbt format registry and SQL warehouse boundary."""
import re
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.errors import ErrorLevel, SqlglotError


@dataclass(frozen=True)
class Warehouse:
    label: str
    dialect: str
    profile: str
    adapter_version: str
    core_version: str
    string_type: str = "STRING"
    materializations: tuple[str, ...] = ("table", "view", "ephemeral")

    def emit_sql(self, query):
        return query.sql(dialect=self.dialect, pretty=True, unsupported_level=ErrorLevel.RAISE)

    def map_type(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ (),<>:]*", value):
            return None
        try:
            node = exp.DataType.build(value, dialect=self.dialect)
            if any(t.this in {exp.DType.UNKNOWN, exp.DType.USERDEFINED} for t in node.find_all(exp.DataType)):
                return None
            return node.sql(dialect=self.dialect, unsupported_level=ErrorLevel.RAISE)
        except (SqlglotError, ValueError):
            return None


FORMATS = {"dbt": "dbt"}
LEGACY_DATABRICKS = Warehouse("Databricks", "databricks", "dbt-core-1.10.13-databricks-1.10.13", "1.10.13", "1.10.13")
WAREHOUSES = {
    "databricks": Warehouse("Databricks", "databricks", "dbt-core-1.12.5-databricks-1.12.8", "1.12.8", "1.12.5")
}


def warehouse(snapshot):
    if snapshot.get("format", "dbt") not in FORMATS or snapshot.get("warehouse") not in WAREHOUSES:
        raise ValueError("Choose a supported format and warehouse")
    target = WAREHOUSES[snapshot["warehouse"]]
    if snapshot.get("profile") == LEGACY_DATABRICKS.profile and target.dialect == LEGACY_DATABRICKS.dialect:
        target = LEGACY_DATABRICKS
    if snapshot.get("profile", target.profile) != target.profile:
        raise ValueError("Unknown compatibility profile")
    for field in ("catalog", "schema"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", snapshot.get(field, "")):
            raise ValueError(f"Enter a literal Databricks {field} identifier")
    if snapshot.get("materialization", "table") not in {"table", "view"}:
        raise ValueError("Choose table or view for new models")
    return target
