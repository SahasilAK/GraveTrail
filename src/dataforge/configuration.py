"""Typed trust boundary for imported workspace parsing settings."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlglot import Dialect


class ParsingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dialect: str = ""
    dialect_by_folder: dict[str, str] = Field(default_factory=dict)
    library_mappings: dict[str, str] = Field(default_factory=dict)
    macros: dict[str, str] = Field(default_factory=dict)
    case_sensitive: bool = False

    @field_validator("dialect")
    @classmethod
    def dialect_known(cls, value):
        if value not in Dialect.classes:
            raise ValueError("Unknown SQL dialect")
        return value

    @field_validator("dialect_by_folder")
    @classmethod
    def folder_dialects_known(cls, value):
        if any(d not in Dialect.classes for d in value.values()):
            raise ValueError("Unknown SQL dialect in folder mappings")
        return value
