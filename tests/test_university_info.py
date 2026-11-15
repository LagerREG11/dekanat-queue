"""Басты беттегі университет туралы деректердің тесттері."""
import pytest

from app import university_info as ui


@pytest.mark.parametrize("lang", ["kk", "ru"])
def test_localized_has_all_sections(lang):
    data = ui.localized(lang)
    for key in ("about", "facts", "history", "contacts",
                "building5", "buildings", "featured_partners", "mobility"):
        assert data[key], key
    assert len(data["institutes"]) == 5
    assert len(data["buildings"]) == 10          # бас корпус + 9 оқу корпусы
    assert data["history"][0]["year"] == "1937"


def test_unknown_language_falls_back_to_kk():
    assert ui.localized("en")["about"] == ui.ABOUT["kk"]


def test_both_languages_have_same_structure():
    kk, ru = ui.localized("kk"), ui.localized("ru")
    for key in ("facts", "history", "buildings", "featured_partners"):
        assert len(kk[key]) == len(ru[key]), key
    assert kk["about"] != ru["about"]


def test_partner_totals():
    countries, entries = ui.partner_totals()
    assert countries == len(ui.PARTNER_COUNTRIES) == 26
    assert entries == 136


def test_building5_address_and_labs():
    b5 = ui.localized("kk")["building5"]
    assert "66А" in b5["address"]
    assert any("321" in f["text"] for f in b5["features"])
    assert any("316" in f["text"] for f in b5["features"])
    assert b5["map_url"].startswith("https://")


def test_every_entry_translated():
    for item in ui.HISTORY + ui.FEATURED_PARTNERS + ui.BUILDING_5["features"]:
        assert item["kk"].strip() and item["ru"].strip()
