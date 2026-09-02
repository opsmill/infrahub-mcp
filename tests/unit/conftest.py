import pytest


@pytest.fixture(autouse=True)
def _disable_dotenv_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable ``.env`` probing by default so a developer's repo-root ``.env`` never
    leaks into the test environment. Tests that exercise ``.env`` loading clear the
    environment themselves (``patch.dict(..., clear=True)``) and are unaffected.
    """
    monkeypatch.setenv("INFRAHUB_MCP_ENV_FILE", "")


@pytest.fixture
def locationsite_filters() -> dict[str, str]:
    return {
        "contact__value": "String",
        "address__value": "String",
        "city__value": "String",
        "name__value": "String",
        "description__value": "String",
        "devices__type__value": "String",
        "devices__name__value": "String",
        "devices__role__value": "String",
        "devices__description__value": "String",
        "devices__status__value": "String",
        "subscriber_of_groups__name__value": "String",
        "subscriber_of_groups__group_type__value": "String",
        "subscriber_of_groups__description__value": "String",
        "subscriber_of_groups__label__value": "String",
        "circuit_endpoints__description__value": "String",
        "profiles__profile_name__value": "String",
        "profiles__profile_priority__value": "Integer",
        "member_of_groups__name__value": "String",
        "member_of_groups__group_type__value": "String",
        "member_of_groups__description__value": "String",
        "member_of_groups__label__value": "String",
        "tags__description__value": "String",
        "tags__name__value": "String",
        "parent__name__value": "String",
        "parent__description__value": "String",
        "children__role__value": "String",
        "children__facility_id__value": "String",
        "children__serial_number__value": "String",
        "children__height__value": "String",
        "children__status__value": "String",
        "children__asset_tag__value": "String",
        "children__name__value": "String",
        "children__description__value": "String",
        "vlans__name__value": "String",
        "vlans__status__value": "String",
        "vlans__role__value": "String",
        "vlans__vlan_id__value": "Integer",
        "vlans__description__value": "String",
    }
