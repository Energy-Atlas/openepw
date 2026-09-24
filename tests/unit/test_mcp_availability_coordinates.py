"""Synthetic coordinate evidence tests; no network or weather acceptance."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from mcp_research import analysis, coordinates


def test_diagnostics_count_products_not_period_ranges():
    matches = [
        dict(
            url=k,
            station_id="001234",
            product=f"TMYx.{period}",
            country="USA",
            coordinate_basis="unknown",
            noaa_candidates=[],
        )
        for k, period in [("a", "2004-2018"), ("b", "2011-2025")]
    ]
    result = analysis.coordinate_diagnostics(matches, [])
    assert result["product_count"] == 2
    assert result["unresolved_reason_counts"] == {"no_coordinate_bearing_identifier": 2}
    assert result["product_family_counts"] == {"TMYx": 2}


def test_diagnostics_distinguish_identity_from_name():
    history = [
        dict(id="00123400001", country="US", name="EXAMPLE AIRPORT"),
        dict(id="00123499999", country="US", name="EXAMPLE"),
    ]
    base = dict(station_id="001234", country="USA", product="TMY3", coordinate_basis="unknown")
    matches = [
        dict(base, url="a", noaa_candidates=history),
        dict(base, url="b", noaa_candidates=[]),
    ]
    assert analysis.coordinate_diagnostics(matches, history)["unresolved_reason_counts"] == {
        "ambiguous_station_identity": 1,
        "name_not_corroborated": 1,
    }


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("Hay.AP", "HAY AIRPORT AWS", "exact_short_name"),
        ("Hay.AP", "RAY AIRPORT AWS", "none"),
        ("Regional.AP", "REGIONAL AIRPORT", "none"),
        ("Ithaca.Tompkins.Rgnl.AP", "ITHACA TOMPKINS REGIONAL AIRPORT", "token_overlap"),
        ("Unalaska-Madsen.AP", "DUTCH HARBOR AIRPORT", "none"),
    ],
)
def test_name_evidence(left, right, expected):
    assert coordinates.name_evidence(left, right) == expected


def test_country_codes_remain_explicit():
    assert coordinates.country_evidence("AUS", ["AS"])["status"] == "consistent"
    assert coordinates.country_evidence("AUS", ["AU"])["status"] == "ambiguous"
    assert coordinates.country_evidence("USA", ["CA"])["status"] == "conflicting"
    assert coordinates.country_evidence("AUS", [])["status"] == "ambiguous"


def test_hay_recovers_but_au_requires_independent_evidence():
    url = "https://climate.onebuilding.org/AUS_NSW_Hay.AP.947020_TMYx.zip"
    site = dict(id="94702099999", country="AS", name="HAY AIRPORT AWS", lat=-34.533, lon=144.833)
    result = coordinates.coordinate_matches([url], [site], [])[0]
    assert result["lat"] == -34.533
    assert result["name_match_method"] == "exact_short_name"
    result = coordinates.coordinate_matches([url], [dict(site, country="AU")], [])[0]
    assert result["lat"] is None
    assert result["country_evidence"]["status"] == "ambiguous"


def test_shared_position_retains_identity_and_elevation_ambiguity():
    candidates = [
        dict(id="00123400001", lat=42.0, lon=-76.0, elevation_m=100),
        dict(id="00123499999", lat=42.0, lon=-76.0, elevation_m=110),
    ]
    out = coordinates.coordinate_consensus(candidates)
    assert (out["lat"], out["lon"]) == (42.0, -76.0)
    assert out["elevation_m"] is None
    assert out["position_status"] == "consensus"
    assert out["station_identity_status"] == "ambiguous"
    assert out["source_station_id"] is None
    assert out["source_station_ids"] == ["00123400001", "00123499999"]
    assert out == coordinates.coordinate_consensus(list(reversed(candidates)))


@pytest.mark.parametrize("second", [42.0001, float("nan"), None])
def test_coordinate_consensus_never_rounds_or_ignores_invalid_points(second):
    out = coordinates.coordinate_consensus(
        [dict(id="a", lat=42, lon=-76), dict(id="b", lat=second, lon=-76)]
    )
    assert out["lat"] is None
    assert out["position_status"] == "unknown"


def test_consensus_handles_empty_duplicates_and_zero_elevation():
    assert coordinates.coordinate_consensus([])["source_station_ids"] == []
    site = dict(id="a", lat=42, lon=-76, elevation_m=0)
    out = coordinates.coordinate_consensus([site, site])
    assert out["station_identity_status"] == "unique_candidate"
    assert out["elevation_m"] == 0
    assert (
        coordinates.coordinate_consensus([site, dict(site, id="b", elevation_m=None)])[
            "elevation_m"
        ]
        is None
    )
    out = coordinates.coordinate_consensus([site, dict(site, lat=43)])
    assert out["lat"] is None


def test_matcher_exposes_consensus_without_a_single_station_id():
    url = "https://climate.onebuilding.org/USA_NY_Testtown.001234_TMY3.zip"
    site = dict(id="00123400001", name="TESTTOWN", country="US", lat=42, lon=-76)
    result = coordinates.coordinate_matches([url], [site, dict(site, id="00123499999")], [])[0]
    assert result["coordinate_basis"] == "station_coordinate_consensus"
    assert result["source_station_id"] is None


@pytest.mark.parametrize("redirect_last", [False, True])
def test_only_approved_indexes_use_extension_and_resume(tmp_path, redirect_last):
    import httpx
    from mcp_research.collector import Collector, Request

    visits = []

    def respond(request):
        visits.append(str(request.url))
        if redirect_last and "TMY3a_" in str(request.url):
            return httpx.Response(302, headers={"Location": "/redirected-index.xlsx"})
        return httpx.Response(200, content=b"index")

    transport = httpx.MockTransport(respond)
    files = [
        ("onebuilding-au-coordinate-xlsx", "Region5_Southwest_Pacific_TMYx"),
        ("onebuilding-normals-coordinate-xlsx", "Normals"),
        ("onebuilding-tmy3-coordinate-xlsx", "TMY3a"),
    ]
    with Collector(tmp_path, transport=transport, spacing=0) as c:
        for i in range(12):
            assert (
                c.collect(
                    Request(
                        f"prior-{i}",
                        "onebuilding",
                        f"https://climate.onebuilding.org/prior-{i}",
                        "metadata",
                        "Synthetic prior attempt",
                    )
                )["outcome"]
                == "saved"
            )
        assert (
            c.collect(
                Request(
                    "unrelated",
                    "onebuilding",
                    "https://climate.onebuilding.org/unrelated",
                    "inventory",
                    "No extension",
                )
            )["outcome"]
            == "provider_limit"
        )
        for index, (key, filename) in enumerate(files):
            request = Request(
                key,
                "onebuilding",
                f"https://climate.onebuilding.org/sources/{filename}_EPW_Processing_locations.xlsx",
                "inventory",
                "Approved index",
                limit=5_000_000,
            )
            assert c.collect(request)["outcome"] == (
                "provider_limit" if redirect_last and index == 2 else "saved"
            )
    count = len(visits)
    with Collector(tmp_path, transport=transport, spacing=0) as c:
        assert c.ledger["counts"]["metadata"] == 15
        assert (
            c.collect(
                Request(
                    "beyond",
                    "onebuilding",
                    "https://climate.onebuilding.org/extra",
                    "metadata",
                    "Exhausted",
                )
            )["outcome"]
            == "provider_limit"
        )
    assert len(visits) == count
    assert not any("/redirected-index" in url for url in visits)


def test_index_family_variant_does_not_match_other_product():
    requested = "https://climate.onebuilding.org/USA_NY_Testtown.001234_TMY3.zip"
    row = dict(
        url=requested.replace("_TMY3.", "_TMY3a."),
        lat=42,
        lon=-76,
        elevation_m=None,
        evidence_id="index",
    )
    assert coordinates.coordinate_matches([requested], [], [row])[0]["lat"] is None


@pytest.mark.parametrize("missing_coordinate,formula_url", [(True, False), (False, True)])
def test_workbook_does_not_resolve_missing_points_or_formula_urls(missing_coordinate, formula_url):
    import io
    import xml.etree.ElementTree as E
    import zipfile

    root = E.Element("worksheet", xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main")
    data = E.SubElement(root, "sheetData")
    headers = ["Country", "City/Station", "WMO", "Latitude (N+/S-)", "Longitude (E+/W-)", "URL"]
    url = "https://climate.onebuilding.org/USA_NY_Test.001234_TMY3.zip"
    for i, values in enumerate(
        [headers, ["USA", "Test", "001234", "" if missing_coordinate else "42", "-76", url]], 1
    ):
        row = E.SubElement(data, "row")
        for col, value in enumerate(values):
            cell = E.SubElement(row, "c", r=f"{chr(65 + col)}{i}", t="inlineStr")
            E.SubElement(E.SubElement(cell, "is"), "t").text = value
            if formula_url and i == 2 and col == 5:
                E.SubElement(cell, "f").text = 'HYPERLINK("ignored")'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", E.tostring(root))
    out = coordinates.spreadsheet_rows(buf.getvalue(), "synthetic")
    assert out["rows"] == []
    assert out["invalid_rows"] == 1


def test_transitions_preserve_added_removed_and_improved_evidence():
    before = [
        dict(url="a", coordinate_basis="unknown"),
        dict(url="b", coordinate_basis="station_identifier_and_name"),
        dict(url="removed", coordinate_basis="unknown"),
    ]
    after = [
        dict(url="a", coordinate_basis="station_coordinate_consensus"),
        dict(url="b", coordinate_basis="published_product_index"),
        dict(url="added", coordinate_basis="unknown"),
    ]
    out = analysis.coordinate_transitions(before, after)
    assert out["counts"] == {
        "unknown -> station_coordinate_consensus": 1,
        "station_identifier_and_name -> published_product_index": 1,
    }
    assert out["added"] == ["added"]
    assert out["removed"] == ["removed"]
    assert out == analysis.coordinate_transitions(list(reversed(before)), list(reversed(after)))


def test_transitions_reject_conflicting_duplicate_products():
    row = dict(url="a", coordinate_basis="unknown")
    assert analysis.coordinate_transitions([row, row], [row])["counts"] == {"unknown -> unknown": 1}
    with pytest.raises(ValueError, match="Conflicting product"):
        analysis.coordinate_transitions(
            [row, dict(row, coordinate_basis="published_product_index")], []
        )


def test_reports_are_offline_deterministic_and_exclude_local_match_dumps(tmp_path, monkeypatch):
    import httpx
    from mcp_research.collector import Collector, Request

    url = "https://climate.onebuilding.org/USA_NY_Unknown.001234_TMY3.zip"
    with Collector(
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=f'<a href="{url}">test</a>'.encode())
        ),
        spacing=0,
    ) as c:
        c.collect(
            Request(
                "onebuilding-us",
                "onebuilding",
                "https://climate.onebuilding.org/catalog",
                "metadata",
                "Synthetic catalog",
            )
        )
    ledger = (tmp_path / "ledger.json").read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("Offline report opened network")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    first = analysis.report(tmp_path)
    serialized = (tmp_path / "evidence.json").read_bytes()
    second = analysis.report(tmp_path)
    assert first == second
    assert serialized == (tmp_path / "evidence.json").read_bytes()
    assert ledger == (tmp_path / "ledger.json").read_bytes()
    inv = first["inventories"]["onebuilding-us"]
    assert inv["unresolved_reason_counts"] == {"no_coordinate_bearing_identifier": 1}
    assert "unresolved_products" not in inv
    assert "coordinate_transition_details" not in inv
    assert "coordinate_matches" not in inv


@pytest.mark.parametrize("second_elevation", [110, None])
def test_published_position_survives_elevation_uncertainty(second_elevation):
    url = "https://climate.onebuilding.org/USA_NY_Test.001234_TMY3.zip"
    row = dict(url=url, lat=42, lon=-76, elevation_m=100, evidence_id="a")
    out = coordinates.coordinate_matches(
        [url], [], [row, dict(row, elevation_m=second_elevation, evidence_id="b")]
    )[0]
    assert (out["lat"], out["lon"]) == (42, -76)
    assert out["position_status"] == "published"
    assert out["elevation_m"] is None
    assert out["published_elevation_uncertainty"] is True
    assert len(out["published_candidates"]) == 2
