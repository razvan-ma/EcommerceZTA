"""The Helm chart must not carry credentials in values.yaml (NFR-04)."""

import re
from pathlib import Path

import yaml

CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm" / "ecommerce-platform"
SECRET_KEY = re.compile(r"(password|secret|token|apikey|api_key)", re.IGNORECASE)
URL_WITH_CREDENTIALS = re.compile(r"://[^/@\s]+:[^/@\s]+@")


def _walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, path + (str(index),))
    else:
        yield path, node


def test_values_contain_no_credentials() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    for path, value in _walk(values):
        # Endpoint URLs (e.g. KEYCLOAK_TOKEN_URL) are fine; their values are
        # still checked for embedded credentials below.
        if not path[-1].upper().endswith("_URL"):
            assert not SECRET_KEY.search(path[-1]), ".".join(path)
        if isinstance(value, str):
            assert not URL_WITH_CREDENTIALS.search(value), ".".join(path)


def test_every_database_service_declares_its_tables() -> None:
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    database_services = {
        name for name, config in values["services"].items() if config.get("database")
    }
    assert database_services == {
        "product",
        "cart",
        "order",
        "inventory",
        "payment",
        "notification",
    }
    for name in database_services:
        assert values["services"][name]["database"]["tables"], name
