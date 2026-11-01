"""Offline datatype suggestions and decimal entry rules for authored schemas."""
from __future__ import annotations

import math
import re

# Suggestions stay editable for nested, user-defined and version-specific types.
TYPE_CATALOG = {
    "Generic SQL": "SMALLINT|INTEGER|BIGINT|DECIMAL|NUMERIC|REAL|FLOAT|DOUBLE PRECISION|BOOLEAN|CHAR|VARCHAR|TEXT|BINARY|VARBINARY|DATE|TIME|TIMESTAMP|INTERVAL|JSON|ARRAY",
    "BigQuery": "INT64|INTEGER|SMALLINT|BIGINT|TINYINT|BYTEINT|NUMERIC|DECIMAL|BIGNUMERIC|BIGDECIMAL|FLOAT64|BOOL|BOOLEAN|STRING|BYTES|DATE|DATETIME|TIME|TIMESTAMP|INTERVAL|JSON|GEOGRAPHY|ARRAY|STRUCT|RANGE",
    "Oracle": "NUMBER|DECIMAL|NUMERIC|INTEGER|SMALLINT|FLOAT|BINARY_FLOAT|BINARY_DOUBLE|CHAR|NCHAR|VARCHAR2|NVARCHAR2|CLOB|NCLOB|BLOB|BFILE|RAW|LONG|LONG RAW|DATE|TIMESTAMP|TIMESTAMP WITH TIME ZONE|TIMESTAMP WITH LOCAL TIME ZONE|INTERVAL YEAR TO MONTH|INTERVAL DAY TO SECOND|ROWID|UROWID|XMLTYPE|JSON|BOOLEAN|VECTOR",
    "SAS": "NUMERIC|CHARACTER",
    "SAS PROC SQL": "NUMERIC|DECIMAL|INTEGER|SMALLINT|FLOAT|REAL|DOUBLE PRECISION|CHAR|VARCHAR",
    "Databricks": "TINYINT|SMALLINT|INT|BIGINT|DECIMAL|NUMERIC|FLOAT|DOUBLE|BOOLEAN|STRING|CHAR|VARCHAR|BINARY|DATE|TIMESTAMP|TIMESTAMP_NTZ|INTERVAL|ARRAY|MAP|STRUCT|VARIANT|VOID",
    "Redshift": "SMALLINT|INTEGER|BIGINT|DECIMAL|NUMERIC|REAL|DOUBLE PRECISION|BOOLEAN|CHAR|VARCHAR|VARBYTE|DATE|TIME|TIMETZ|TIMESTAMP|TIMESTAMPTZ|INTERVAL YEAR TO MONTH|INTERVAL DAY TO SECOND|SUPER|GEOMETRY|GEOGRAPHY|HLLSKETCH",
    "SQL Server": "BIGINT|INT|SMALLINT|TINYINT|BIT|DECIMAL|NUMERIC|MONEY|SMALLMONEY|FLOAT|REAL|CHAR|VARCHAR|TEXT|NCHAR|NVARCHAR|NTEXT|BINARY|VARBINARY|IMAGE|DATE|TIME|DATETIME|DATETIME2|SMALLDATETIME|DATETIMEOFFSET|UNIQUEIDENTIFIER|XML|JSON|SQL_VARIANT|ROWVERSION|HIERARCHYID|GEOGRAPHY|GEOMETRY|VECTOR",
    "Snowflake": "NUMBER|DECIMAL|NUMERIC|INT|INTEGER|BIGINT|SMALLINT|TINYINT|BYTEINT|FLOAT|FLOAT4|FLOAT8|DOUBLE|DOUBLE PRECISION|REAL|DECFLOAT|BOOLEAN|VARCHAR|CHAR|CHARACTER|STRING|TEXT|BINARY|VARBINARY|DATE|TIME|DATETIME|TIMESTAMP|TIMESTAMP_LTZ|TIMESTAMP_NTZ|TIMESTAMP_TZ|VARIANT|OBJECT|ARRAY|GEOGRAPHY|GEOMETRY|VECTOR|UUID|IPADDRESS",
    "PostgreSQL": "SMALLINT|INTEGER|BIGINT|DECIMAL|NUMERIC|REAL|DOUBLE PRECISION|SMALLSERIAL|SERIAL|BIGSERIAL|MONEY|BOOLEAN|CHAR|VARCHAR|TEXT|BYTEA|DATE|TIME|TIME WITH TIME ZONE|TIMESTAMP|TIMESTAMP WITH TIME ZONE|INTERVAL|UUID|JSON|JSONB|XML|ARRAY|BIT|BIT VARYING|INET|CIDR|MACADDR|MACADDR8|POINT|LINE|LSEG|BOX|PATH|POLYGON|CIRCLE|TSVECTOR|TSQUERY|INT4RANGE|INT8RANGE|NUMRANGE|TSRANGE|TSTZRANGE|DATERANGE",
    "MySQL": "TINYINT|SMALLINT|MEDIUMINT|INT|INTEGER|BIGINT|DECIMAL|NUMERIC|FLOAT|DOUBLE|BIT|BOOLEAN|CHAR|VARCHAR|BINARY|VARBINARY|TINYBLOB|BLOB|MEDIUMBLOB|LONGBLOB|TINYTEXT|TEXT|MEDIUMTEXT|LONGTEXT|ENUM|SET|DATE|DATETIME|TIMESTAMP|TIME|YEAR|JSON|GEOMETRY|POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON|GEOMETRYCOLLECTION",
    "MariaDB": "TINYINT|SMALLINT|MEDIUMINT|INT|BIGINT|DECIMAL|NUMERIC|FLOAT|DOUBLE|BIT|BOOLEAN|CHAR|VARCHAR|BINARY|VARBINARY|TINYBLOB|BLOB|MEDIUMBLOB|LONGBLOB|TINYTEXT|TEXT|MEDIUMTEXT|LONGTEXT|ENUM|SET|DATE|DATETIME|TIMESTAMP|TIME|YEAR|JSON|UUID|INET4|INET6|GEOMETRY|POINT|LINESTRING|POLYGON",
    "SQLite": "INTEGER|REAL|TEXT|BLOB|NUMERIC|DECIMAL|BOOLEAN|DATE|DATETIME",
    "DuckDB": "TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|UHUGEINT|DECIMAL|FLOAT|DOUBLE|BOOLEAN|VARCHAR|BLOB|BIT|DATE|TIME|TIMETZ|TIMESTAMP|TIMESTAMPTZ|INTERVAL|UUID|JSON|ENUM|LIST|ARRAY|STRUCT|MAP|UNION",
    "Spark SQL": "BYTE|SHORT|INT|LONG|FLOAT|DOUBLE|DECIMAL|BOOLEAN|STRING|CHAR|VARCHAR|BINARY|DATE|TIMESTAMP|TIMESTAMP_NTZ|INTERVAL|ARRAY|MAP|STRUCT|VOID",
    "Hive": "TINYINT|SMALLINT|INT|BIGINT|FLOAT|DOUBLE|DECIMAL|BOOLEAN|STRING|CHAR|VARCHAR|BINARY|DATE|TIMESTAMP|INTERVAL|ARRAY|MAP|STRUCT|UNIONTYPE",
    "DB2": "SMALLINT|INTEGER|BIGINT|DECIMAL|NUMERIC|DECFLOAT|REAL|DOUBLE|BOOLEAN|CHAR|VARCHAR|CLOB|GRAPHIC|VARGRAPHIC|DBCLOB|BINARY|VARBINARY|BLOB|DATE|TIME|TIMESTAMP|XML|ROWID",
    "Teradata": "BYTEINT|SMALLINT|INTEGER|BIGINT|DECIMAL|NUMERIC|NUMBER|FLOAT|REAL|DOUBLE PRECISION|CHAR|VARCHAR|CLOB|BYTE|VARBYTE|BLOB|DATE|TIME|TIMESTAMP|INTERVAL|JSON|XML|PERIOD|ST_GEOMETRY",
    "Trino": "TINYINT|SMALLINT|INTEGER|BIGINT|REAL|DOUBLE|DECIMAL|BOOLEAN|VARCHAR|CHAR|VARBINARY|DATE|TIME|TIME WITH TIME ZONE|TIMESTAMP|TIMESTAMP WITH TIME ZONE|INTERVAL YEAR TO MONTH|INTERVAL DAY TO SECOND|JSON|ARRAY|MAP|ROW|IPADDRESS|UUID|HYPERLOGLOG|P4HYPERLOGLOG|QDIGEST|TDIGEST",
    "ClickHouse": "Int8|Int16|Int32|Int64|Int128|Int256|UInt8|UInt16|UInt32|UInt64|UInt128|UInt256|Float32|Float64|Decimal|Decimal32|Decimal64|Decimal128|Decimal256|Bool|String|FixedString|Date|Date32|DateTime|DateTime64|UUID|IPv4|IPv6|Enum8|Enum16|Array|Tuple|Map|Nullable|LowCardinality|Nested|JSON|Dynamic|Variant",
}
TYPE_CATALOG = {name: values.split("|") for name, values in TYPE_CATALOG.items()}
TYPE_CATALOG["Azure Synapse"] = TYPE_CATALOG["SQL Server"]
TYPE_CATALOG["Presto"] = TYPE_CATALOG["Trino"]

# Official references for the decimal rules; catalogs are suggestions, not live capabilities.
TYPE_REFERENCES = {
    "BigQuery": "https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-types#parameterized_decimal_type",
    "Oracle": "https://docs.oracle.com/en/database/oracle/oracle-database/26/sqlrf/Data-Types.html",
    "Databricks": "https://docs.databricks.com/aws/en/sql/language-manual/data-types/decimal-type",
    "Redshift": "https://docs.aws.amazon.com/redshift/latest/dg/r_Numeric_types201.html",
    "SQL Server": "https://learn.microsoft.com/en-us/sql/t-sql/data-types/decimal-and-numeric-transact-sql",
    "PostgreSQL": "https://www.postgresql.org/docs/current/datatype-numeric.html",
    "Snowflake": "https://docs.snowflake.com/en/sql-reference/data-types-numeric",
}
DECIMAL = re.compile(r"^\s*(DECIMAL|DEC|NUMERIC|NUMBER|BIGNUMERIC|BIGDECIMAL)\s*(?:\(\s*([+-]?\d+)\s*(?:,\s*([+-]?\d+)\s*)?\))?\s*$", re.I)


def type_entry(data_type: str, system: str = "") -> dict:
    """Split parameterized decimals into editable grid cells without changing other types."""
    match = DECIMAL.fullmatch(data_type)
    if match and match[2] is not None and system.casefold() != "sas":
        return {"data_type": match[1].upper(), "precision": int(match[2]), "scale": int(match[3] or 0)}
    return {"data_type": data_type, "precision": None, "scale": None}


def _integer(value, label: str) -> int:
    try:
        if isinstance(value, bool) or (isinstance(value, float) and (not math.isfinite(value) or not value.is_integer())):
            raise ValueError
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a whole number") from None


def format_data_type(system: str, data_type: str, precision=None, scale=None) -> str:
    """Format explicit decimals, validate vendor limits, and preserve custom type expressions."""
    if not isinstance(data_type, str):
        raise ValueError("Data type must be text")
    if not isinstance(system, str) or len(system) > 100:
        raise ValueError("System / database must be text of at most 100 characters")
    value = data_type.strip()
    system = system.casefold()
    match = DECIMAL.fullmatch(value)
    fixed = match and system != "sas"
    if not fixed:
        if precision is not None or scale is not None:
            raise ValueError("Precision and scale apply to decimal types only; clear these cells for other types")
        return value
    kind = match[1].upper()
    if match[2] is not None:
        inline_p, inline_s = int(match[2]), int(match[3] or 0)
        if (precision is not None and _integer(precision, "Precision") != inline_p) or (scale is not None and _integer(scale, "Scale") != inline_s):
            raise ValueError("Decimal parameters conflict with the precision/scale cells")
        precision, scale = inline_p, inline_s
    if precision is None:
        if scale is None:
            return value
        raise ValueError("Enter precision when scale is provided, or leave both blank")
    p, s = _integer(precision, "Precision"), _integer(0 if scale is None else scale, "Scale")
    max_p = {"postgresql": 1000, "mysql": 65, "mariadb": 65, "db2": 31, "clickhouse": 76}.get(system, 38)
    min_s, max_s = 0, max_p
    scale_may_exceed_precision = False
    if system == "oracle":
        min_s, max_s, scale_may_exceed_precision = -84, 127, True
    elif system == "postgresql":
        min_s, max_s, scale_may_exceed_precision = -1000, 1000, True
    elif system in {"mysql", "mariadb"}:
        max_s = 30 if system == "mysql" else 38
    elif system == "snowflake":
        max_s = 37
    elif system == "bigquery":
        big = kind in {"BIGNUMERIC", "BIGDECIMAL"}
        max_p, max_s = (76, 38) if big else (38, 9)
        if p > s + (38 if big else 29):
            raise ValueError(f"{kind} in BigQuery allows at most {38 if big else 29} integer digits (precision − scale)")
    if not 1 <= p <= max_p:
        raise ValueError(f"Precision for {kind} in {system or 'Generic SQL'} must be between 1 and {max_p}")
    if not min_s <= s <= max_s or (not scale_may_exceed_precision and s > p):
        raise ValueError(f"Invalid scale for {kind}: use {min_s}–{max_s}" + (" and no greater than precision" if not scale_may_exceed_precision else ""))
    return f"{kind}({p},{s})"
