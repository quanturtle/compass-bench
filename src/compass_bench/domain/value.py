"""The base of every domain value."""

from pydantic import BaseModel, ConfigDict


class Value(BaseModel):
    """Immutable value object; validation rejects unknown fields and coerced types, but a union tag accepts its str.

    Validate external data from JSON text: strict Python mode rejects lists for tuples and str for enum fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
