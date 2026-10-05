"""Validate the JSON Schema subset used by fei tools without coercion."""
import math

def validate(value, schema, path="arguments"):
    kind = schema.get("type")
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "string": lambda v: isinstance(v, str), "integer": lambda v: type(v) is int, "number": lambda v: type(v) in (int, float) and math.isfinite(v), "boolean": lambda v: type(v) is bool, "null": lambda v: v is None}
    if kind and (kind not in checks or not checks[kind](value)):
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: raise ValueError(f"{path}.{key}: required")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties", False) is False:
                raise ValueError(f"{path}.{key}: unknown argument")
    if isinstance(value, str):
        for bound, test in [("minLength", len(value) < schema.get("minLength", 0)), ("maxLength", len(value) > schema.get("maxLength", float("inf")))]:
            if test: raise ValueError(f"{path}: violates {bound}={schema[bound]}")
    if type(value) in (int, float):
        if not math.isfinite(value): raise ValueError(f"{path}: must be finite")
        if value < schema.get("minimum", float("-inf")): raise ValueError(f"{path}: below minimum")
        if value > schema.get("maximum", float("inf")): raise ValueError(f"{path}: above maximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): raise ValueError(f"{path}: too few items")
        if len(value) > schema.get("maxItems", float("inf")): raise ValueError(f"{path}: too many items")
        for i, item in enumerate(value): validate(item, schema.get("items", {}), f"{path}[{i}]")
