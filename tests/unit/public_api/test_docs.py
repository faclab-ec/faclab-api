"""The public documentation page (S6.5): the guides, core's and invoicing's
routes and the webhook events, built from the contracts without changing them."""

import copy
import json
import re

import pytest
from fastapi.testclient import TestClient

from main import app
from src.public_api.infra import docs
from src.public_api.infra.openapi import SNAPSHOT, public_openapi, render
from src.webhooks.infra.schemas import EVENT_MODELS

LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.fixture(scope="module")
def document() -> dict:
    return docs.build_docs_document(public_openapi(app), docs._invoicing())


def _refs(value) -> set[str]:
    if isinstance(value, dict):
        found = {value["$ref"]} if isinstance(value.get("$ref"), str) else set()
        return found.union(*(_refs(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_refs(item) for item in value))
    return set()


def test_it_has_core_and_invoicing_routes_and_every_event(document):
    core = public_openapi(app)
    invoicing = json.loads(docs.INVOICING_SPEC.read_text())

    assert set(core["paths"]) | set(invoicing["paths"]) == set(document["paths"])
    assert set(document["webhooks"]) == set(EVENT_MODELS)
    assert "Invoices" in {tag["name"] for tag in document["tags"]}


def test_every_reference_resolves(document):
    schemas = document["components"]["schemas"]
    for ref in _refs(document):
        assert ref.startswith("#/components/schemas/"), ref
        assert ref.removeprefix("#/components/schemas/") in schemas, ref
    assert "$defs" not in json.dumps(document)


def test_the_contract_is_not_changed_by_the_page():
    core = public_openapi(app)
    before = copy.deepcopy(core)

    docs.build_docs_document(core, docs._invoicing())

    assert core == before
    assert render(core) == SNAPSHOT.read_text()


def test_the_endpoint_routes_get_their_own_tag_on_the_page(document):
    tags = {tag["name"] for tag in document["tags"]}
    assert docs.ENDPOINTS_TAG in tags
    assert "Webhooks" not in tags
    assert document["paths"]["/api/v1/webhook-endpoints"]["get"]["tags"] == [
        docs.ENDPOINTS_TAG
    ]


def test_the_invoicing_copy_only_uses_core_scopes():
    invoicing = json.loads(docs.INVOICING_SPEC.read_text())
    core = public_openapi(app)["components"]["securitySchemes"]["clientCredentials"]

    scopes = invoicing["components"]["securitySchemes"]["clientCredentials"]
    assert set(scopes["flows"]["clientCredentials"]["scopes"]) <= set(
        core["flows"]["clientCredentials"]["scopes"]
    )


def test_a_path_in_both_documents_is_refused():
    core = public_openapi(app)
    clash = {"paths": {"/api/v1/branches": {}}, "components": {}}

    with pytest.raises(docs.DocsMergeError, match="/api/v1/branches"):
        docs.build_docs_document(core, clash)


def test_a_scope_core_does_not_have_is_refused():
    core = public_openapi(app)
    unknown = {
        "paths": {"/api/v1/elsewhere": {}},
        "components": {
            "securitySchemes": {
                "clientCredentials": {
                    "flows": {"clientCredentials": {"scopes": {"payments:write": ""}}}
                }
            }
        },
    }

    with pytest.raises(docs.DocsMergeError, match="payments:write"):
        docs.build_docs_document(core, unknown)


def test_without_the_invoicing_copy_the_page_has_core_alone():
    document = docs.build_docs_document(public_openapi(app), None)

    assert not [path for path in document["paths"] if "invoices" in path]


@pytest.mark.parametrize("name", docs.GUIDES)
def test_each_guide_is_for_integrators_and_its_files_exist(name):
    text = (docs.PUBLIC_DOCS / name).read_text()

    assert text.startswith("# ")
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "#")):
            continue
        path = target.split("#", 1)[0]
        # No architecture documents, ADR or sessions: integrators can't see them
        assert not path.startswith(".."), f"{name} links {target}"
        assert (docs.PUBLIC_DOCS / path).exists(), f"{name} links {target}"


def test_guide_links_become_text_and_file_links_point_at_the_files():
    text = docs._relink(
        "Ver [Webhooks](webhooks.md#3-verificar-la-firma), "
        "[el cliente](examples/python/faclab.py) y "
        "[la norma](https://www.standardwebhooks.com/)."
    )

    assert text == (
        "Ver **Webhooks**, "
        f"[el cliente]({docs.FILES_PATH}/examples/python/faclab.py) y "
        "[la norma](https://www.standardwebhooks.com/)."
    )


def test_the_page_its_document_and_files_are_served():
    client = TestClient(app)

    page = client.get("/docs/public")
    assert page.status_code == 200
    assert "/openapi/public-docs.json" in page.text

    served = client.get("/openapi/public-docs.json")
    assert served.status_code == 200
    assert served.json()["info"]["description"].startswith("# Primeros pasos")

    example = client.get(f"{docs.FILES_PATH}/examples/python/faclab.py")
    assert example.status_code == 200
    assert "class Faclab" in example.text
    assert client.get(f"{docs.FILES_PATH}/../../.env").status_code == 404
