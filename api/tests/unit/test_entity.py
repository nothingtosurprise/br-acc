import pytest
from httpx import AsyncClient

from icarus.services.neo4j_service import CypherLoader

# Expected node labels that form the IDOR allowlist.
# If a new label is added to the queries, add it here too.
EXPECTED_LABELS = {
    "Person", "Company", "Contract", "Sanction", "Election",
    "Amendment", "Finance", "Embargo", "Health", "Education",
    "Convenio", "LaborStats", "PublicOffice",
}

# Expected entity ID property fields in lookup/coalesce chains.
EXPECTED_ID_FIELDS = {
    "cpf", "cnpj", "contract_id", "sanction_id", "amendment_id",
}


def _load_cypher(name: str) -> str:
    try:
        return CypherLoader.load(name)
    finally:
        CypherLoader.clear_cache()


def test_entity_by_id_has_label_allowlist() -> None:
    """IDOR prevention: entity_by_id.cypher must restrict to known labels."""
    cypher = _load_cypher("entity_by_id")
    for label in EXPECTED_LABELS:
        assert f"e:{label}" in cypher, (
            f"entity_by_id.cypher missing label allowlist entry: {label}"
        )


def test_investigation_add_entity_has_label_allowlist() -> None:
    """IDOR prevention: investigation_add_entity.cypher must restrict to known labels."""
    cypher = _load_cypher("investigation_add_entity")
    for label in EXPECTED_LABELS:
        assert f"e:{label}" in cypher, (
            f"investigation_add_entity.cypher missing label allowlist entry: {label}"
        )


def test_investigation_remove_entity_has_label_allowlist() -> None:
    """IDOR prevention: investigation_remove_entity.cypher must restrict to known labels."""
    cypher = _load_cypher("investigation_remove_entity")
    for label in EXPECTED_LABELS:
        assert f"e:{label}" in cypher, (
            f"investigation_remove_entity.cypher missing label allowlist entry: {label}"
        )


def test_label_allowlists_are_consistent_across_queries() -> None:
    """All three entity-resolving queries must use the same label allowlist."""
    import re

    queries = ["entity_by_id", "investigation_add_entity", "investigation_remove_entity"]
    label_sets: dict[str, set[str]] = {}
    for qname in queries:
        cypher = _load_cypher(qname)
        # Extract labels like e:Person, e:Company etc.
        labels = set(re.findall(r"e:(\w+)", cypher))
        label_sets[qname] = labels

    base = label_sets["entity_by_id"]
    for qname in queries[1:]:
        assert label_sets[qname] == base, (
            f"Label allowlist mismatch between entity_by_id and {qname}: "
            f"missing={base - label_sets[qname]}, extra={label_sets[qname] - base}"
        )


def test_entity_by_id_has_all_id_fields() -> None:
    """entity_by_id.cypher must look up by all entity ID property fields."""
    cypher = _load_cypher("entity_by_id")
    for field in EXPECTED_ID_FIELDS:
        assert f"e.{field}" in cypher, (
            f"entity_by_id.cypher missing ID field lookup: e.{field}"
        )


@pytest.mark.anyio
async def test_entity_lookup_rejects_invalid_format(client: AsyncClient) -> None:
    response = await client.get("/api/v1/entity/abc")
    assert response.status_code == 400
    assert "Invalid CPF or CNPJ" in response.json()["detail"]


@pytest.mark.anyio
async def test_entity_lookup_rejects_short_number(client: AsyncClient) -> None:
    response = await client.get("/api/v1/entity/12345")
    assert response.status_code == 400


@pytest.mark.anyio
async def test_entity_lookup_rejects_15_digits(client: AsyncClient) -> None:
    response = await client.get("/api/v1/entity/123456789012345")
    assert response.status_code == 400


@pytest.mark.anyio
async def test_connections_rejects_invalid_depth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/entity/test-id/connections?depth=5")
    assert response.status_code == 422


@pytest.mark.anyio
async def test_connections_rejects_zero_depth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/entity/test-id/connections?depth=0")
    assert response.status_code == 422
