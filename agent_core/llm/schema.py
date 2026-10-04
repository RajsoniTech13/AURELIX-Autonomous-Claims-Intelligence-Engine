"""
Turn a Pydantic model into a JSON schema that strict structured-output modes accept.

Groq's and OpenAI's `strict: true` and Anthropic's `output_config.format` all use
constrained decoding: the provider guarantees the answer matches the schema, which is far
stronger than asking nicely in the prompt. In return they require a disciplined schema —
every object closed (`additionalProperties: false`) and every property listed in
`required`. Pydantic's default output does neither: fields with defaults are left out of
`required`, and objects are open.

This function applies those two rules everywhere in the schema, including inside `$defs`,
and drops `title` keys, which are noise to a model. The Pydantic model is still the
contract: the answer is validated against it again after it comes back, because "the
provider promised" is not the same as "we checked".
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Type

from pydantic import BaseModel


def _close(schema: Any) -> Any:
    """
    Walk schema *nodes* only. `properties` and `$defs` are maps from a name to a schema, so
    their keys are field names, not keywords — a model with a field called `title` must keep
    it. Only the values of those maps are recursed into.
    """
    if not isinstance(schema, dict):
        return schema
    schema.pop("title", None)
    schema.pop("default", None)
    props = schema.get("properties")
    if schema.get("type") == "object" and isinstance(props, dict):
        schema["additionalProperties"] = False
        schema["required"] = list(props)
    for key in ("properties", "$defs"):
        for sub in (schema.get(key) or {}).values():
            _close(sub)
    if isinstance(schema.get("items"), dict):
        _close(schema["items"])
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key) or []:
            _close(sub)
    return schema


def strict_json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """A closed, all-required JSON schema for `model`. Does not mutate Pydantic's cache."""
    return _close(copy.deepcopy(model.model_json_schema()))
