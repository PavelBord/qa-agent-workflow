"""Validate and normalize teacher-compatible eval case input."""
from copy import deepcopy


def normalize_case(case, *, confluence_page_id=None):
    value = deepcopy(case)
    if not isinstance(value, dict) or not isinstance(value.get("input"), dict):
        raise ValueError("Eval Case должен содержать объект input")
    value.setdefault("name", value.get("id", "Unnamed case"))
    data = value["input"]
    source = data.get("source")
    if source == "confluence":
        inline_keys = set(data) - {"source", "page_id", "task"}
        if inline_keys:
            raise ValueError(f"Eval Case {value.get('id')}: Confluence нельзя смешивать со встроенными данными")
        if confluence_page_id is not None:
            data["page_id"] = str(confluence_page_id).strip()
        if not str(data.get("page_id", "")).strip().isdigit():
            raise ValueError(f"Eval Case {value.get('id')}: нужен числовой page_id")
    elif source == "inline":
        if not (set(data) - {"source", "task"}):
            raise ValueError(f"Eval Case {value.get('id')}: inline input пуст")
    else:
        raise ValueError(f"Eval Case {value.get('id')}: неизвестный source {source}")
    if "forbidden_behaviour" in value:
        if "forbidden_behavior" in value and value["forbidden_behavior"] != value["forbidden_behaviour"]:
            raise ValueError(f"Eval Case {value.get('id')}: конфликтующие поля forbidden behavior")
        value["forbidden_behavior"] = value.pop("forbidden_behaviour")
    for field in ("expected_properties", "forbidden_behavior"):
        if not isinstance(value.get(field), list):
            raise ValueError(f"Eval Case {value.get('id')}: поле {field} должно быть списком")
    return value
