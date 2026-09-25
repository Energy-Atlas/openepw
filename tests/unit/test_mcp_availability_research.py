"""Research safeguards: synthetic transports only, never provider acceptance."""

import hashlib
import importlib
import io
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def research():
    # Fail explicitly before the collector exists, rather than failing collection.
    assert importlib.util.find_spec("mcp_research.collector"), "Research collector is missing"
    return importlib.import_module("mcp_research.collector")


def spec(module, key="one", **kw):
    return module.Request(
        key,
        "example",
        "https://example.org/catalog",
        "inventory",
        "Check published site coverage",
        **kw,
    )


def test_resume_reuses_snapshot_and_keeps_request_ceiling(tmp_path):
    m = research()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"catalog"))
    limits = m.Limits(metadata_requests=1)
    with m.Collector(tmp_path, limits=limits, transport=transport, spacing=0) as c:
        assert c.collect(spec(m))["outcome"] == "saved"
    with m.Collector(tmp_path, limits=limits, transport=transport, spacing=0) as c:
        assert c.collect(spec(m))["outcome"] == "saved"
        assert c.collect(spec(m, "two"))["outcome"] == "request_budget"
        assert c.ledger["counts"]["metadata"] == 1


def test_oversized_stream_consumes_budget_without_snapshot(tmp_path):
    m = research()

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"1234"
            yield b"5678"

    transport = httpx.MockTransport(lambda r: httpx.Response(200, stream=Chunks()))
    with m.Collector(
        tmp_path, limits=m.Limits(total_bytes=6, ordinary_bytes=6), transport=transport, spacing=0
    ) as c:
        result = c.collect(spec(m))
        assert result["outcome"] == "byte_limit"
        assert c.ledger["charged_bytes"] <= 6
        assert not list((tmp_path / "raw").glob("*.body"))
        assert c.collect(spec(m, "two"))["outcome"] == "byte_budget"


def test_redirect_is_counted_and_unapproved_host_never_requested(tmp_path):
    m = research()
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/path?token=secret"})

    with m.Collector(tmp_path, transport=httpx.MockTransport(handler), spacing=0) as c:
        assert c.collect(spec(m))["outcome"] == "redirect_rejected"
        assert c.ledger["counts"]["metadata"] == 1
    assert visited == ["https://example.org/catalog"]
    assert "secret" not in (tmp_path / "ledger.json").read_text()


def test_rate_limit_blocks_provider_after_resume_and_errors_are_not_stored(tmp_path):
    m = research()
    transport = httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"retry-after": "3600"}, content=b"secret error body")
    )
    with m.Collector(tmp_path, transport=transport, spacing=0) as c:
        assert c.collect(spec(m))["outcome"] == "rate_limited"
    with m.Collector(tmp_path, transport=transport, spacing=0) as c:
        assert c.collect(spec(m, "two"))["outcome"] == "provider_backoff"
        assert c.ledger["counts"]["metadata"] == 1
    assert "secret error body" not in (tmp_path / "ledger.json").read_text()
    assert not list((tmp_path / "raw").glob("*.body"))


def test_range_ignored_is_rejected_before_reading_weather(tmp_path):
    m = research()
    with m.Collector(
        tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"large archive")),
        spacing=0,
    ) as c:
        result = c.collect(spec(m, headers={"Range": "bytes=-65536"}))
        assert result["outcome"] == "range_rejected"
        assert not list((tmp_path / "raw").glob("*.body"))


def test_exception_and_query_credentials_do_not_leak(tmp_path):
    m = research()

    def handler(request):
        raise httpx.ConnectError("token=super-secret", request=request)

    request = m.Request(
        "private",
        "example",
        "https://example.org/catalog?api_key=super-secret",
        "inventory",
        "Check catalog",
    )
    with m.Collector(tmp_path, transport=httpx.MockTransport(handler), spacing=0) as c:
        assert c.collect(request)["outcome"] == "transport_error"
    assert "super-secret" not in (tmp_path / "ledger.json").read_text()


def test_interrupted_reservation_is_not_forgotten(tmp_path):
    m = research()

    def interrupt(request):
        raise KeyboardInterrupt

    with m.Collector(
        tmp_path,
        limits=m.Limits(total_bytes=10, ordinary_bytes=10),
        transport=httpx.MockTransport(interrupt),
        spacing=0,
    ) as c:
        with pytest.raises(KeyboardInterrupt):
            c.collect(spec(m))
    with m.Collector(tmp_path, limits=m.Limits(total_bytes=10, ordinary_bytes=10), spacing=0) as c:
        assert c.ledger["counts"]["metadata"] == 1
        assert c.collect(spec(m, "two"))["outcome"] == "byte_budget"


def test_offline_commands_do_not_open_network(tmp_path, monkeypatch, capsys):
    research()
    cli = importlib.import_module("probe_mcp_availability")

    def forbidden(*a, **kw):
        pytest.fail("Offline command opened network client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    for command in ("plan", "analyze", "report"):
        assert cli.main([command, "--root", str(tmp_path)]) == 0
    assert "unknown" in capsys.readouterr().out


def test_inventory_identifiers_and_periods_do_not_claim_completeness():
    research()
    a = importlib.import_module("mcp_research.analysis")
    rows = a.station_history(
        b"USAF,WBAN,STATION NAME,LAT,LON,ELEV(M),BEGIN,END\n001234,00001,Site,42,-76,120,20000101,20241231\n"
    )
    assert rows == [
        {
            "id": "00123400001",
            "name": "Site",
            "country": None,
            "lat": 42.0,
            "lon": -76.0,
            "elevation_m": 120.0,
            "start": "2000-01-01",
            "end": "2024-12-31",
            "temporal_kind": "station_operating_interval",
            "completeness": "unknown",
        }
    ]


def test_cmip_intersection_never_combines_members():
    research()
    a = importlib.import_module("mcp_research.analysis")
    rows = []
    for experiment in ("historical", "ssp245"):
        for variable in ("tas", "tasmin", "tasmax", "hurs", "ps", "sfcWind", "rsds"):
            rows.append(
                dict(
                    source_id="M",
                    member_id="r1",
                    grid_label="gn",
                    table_id="Amon",
                    experiment_id=experiment,
                    variable_id=variable,
                    zstore="gs://cmip6/a",
                )
            )
    assert len(a.cmip_intersections(rows)) == 1
    rows[-1]["member_id"] = "r2"
    assert a.cmip_intersections(rows) == []


def test_repeated_points_preserve_occurrences_and_group_verified_sources():
    research()
    a = importlib.import_module("mcp_research.analysis")
    sites = [{"id": "001", "lat": 42.0, "lon": -76.0, "start": "2000-01-01", "end": "2024-12-31"}]
    result = a.map_sites([(42.0, -76.0), (42.0, -76.0), (-33.0, 151.0)], sites, "2024-01-01")
    assert len(result["mappings"]) == 3
    assert result["unique_sources"] == 1
    assert [r["eligibility"] for r in result["mappings"]] == ["supported", "supported", "unknown"]
    assert [r["occurrence"] for r in result["mappings"]] == [0, 1, 2]


def test_zip_directory_lists_members_without_extracting_weather():
    research()
    assert importlib.util.find_spec("mcp_research.archives"), "Directory reader missing"
    a = importlib.import_module("mcp_research.archives")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("folder/001_RCP8.5_2045_lat42.epw", b"weather must not be read")
    raw = stream.getvalue()
    location = a.directory_location(raw, len(raw))
    names = a.member_names(raw[location["offset"] : location["offset"] + location["size"]])
    assert names == ["folder/001_RCP8.5_2045_lat42.epw"]
    assert a.site_years(names) == {"001": {"RCP8.5": [2045]}}


def test_deadline_stops_slow_stream_and_preserves_attempt(tmp_path):
    import asyncio

    m = research()

    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"abc"
            await asyncio.sleep(1)
            yield b"late"

    with m.Collector(
        tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Slow())),
        spacing=0,
        deadline=0.01,
    ) as c:
        assert c.collect(spec(m))["outcome"] == "deadline"
        assert c.ledger["counts"]["metadata"] == 1
        assert not list((tmp_path / "raw").glob("*.body"))


def test_redirect_hops_and_probe_caps_are_both_counted(tmp_path):
    m = research()

    def handler(request):
        if request.url.path == "/catalog":
            return httpx.Response(302, headers={"location": "/next"})
        return httpx.Response(200, content=b"ok")

    with m.Collector(tmp_path, transport=httpx.MockTransport(handler), spacing=0) as c:
        first = m.Request("p1", "pvgis", "https://example.org/catalog", "probe", "test")
        assert c.collect(first)["outcome"] == "saved"
        second = m.Request("p2", "pvgis", "https://example.org/next", "probe", "test")
        assert c.collect(second)["outcome"] == "provider_limit"
        assert c.ledger["counts"]["probe"] == 2


def test_revision_requires_failed_original_and_cannot_repeat(tmp_path):
    m = research()
    with m.Collector(
        tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(404)), spacing=0
    ) as c:
        assert c.collect(spec(m))["outcome"] == "http_error"
        assert (
            c.collect(spec(m, "rev", revision_of="one", correction="Correct path"))["outcome"]
            == "http_error"
        )
        assert (
            c.collect(spec(m, "again", revision_of="one", correction="Repeat"))["outcome"]
            == "revision_rejected"
        )


def test_archive_directory_has_ten_mb_allowance_shared_with_tail(tmp_path):
    m = research()

    def handler(r):
        return httpx.Response(
            206,
            content=b"x" * 6_000_000,
            headers={"content-range": "bytes 0-5999999/9000000", "etag": '"v1"'},
        )

    request = m.Request(
        "directory",
        "oedi",
        "https://example.org/a.zip",
        "metadata",
        "Directory metadata",
        archive="rcp45",
        limit=6_000_000,
        headers={"Range": "bytes=0-5999999"},
    )
    with m.Collector(tmp_path, transport=httpx.MockTransport(handler), spacing=0) as c:
        assert c.collect(request)["outcome"] == "saved"
        assert c.ledger["archive_bytes"]["rcp45"] == 6_000_000


def test_probe_redirect_cannot_exceed_provider_cap(tmp_path):
    m = research()

    def handler(r):
        return httpx.Response(302, headers={"location": "/next"})

    with m.Collector(tmp_path, transport=httpx.MockTransport(handler), spacing=0) as c:
        request = m.Request("loop", "pvgis", "https://example.org/catalog", "probe", "Check")
        c.collect(request)
        assert c.ledger["counts"]["probe"] == 2


def test_zarr_metadata_sample_limit(tmp_path):
    m = research()
    with m.Collector(
        tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})), spacing=0
    ) as c:
        for i in range(5):
            result = c.collect(
                m.Request(
                    f"z{i}", "cmip6", f"https://example.org/{i}/.zmetadata", "metadata", "Sample"
                )
            )
        assert result["outcome"] == "provider_limit"
        assert c.ledger["counts"]["metadata"] == 4


def test_normalize_cds_and_tmy_temporal_meanings(tmp_path):
    m = research()
    payloads = {
        "/cds": {
            "id": "era5",
            "license": "CC-BY-4.0",
            "extent": {
                "spatial": {"bbox": [[0, -89, 360, 89]]},
                "temporal": {"interval": [["1940-01-01", "2026-09-17"]]},
            },
        },
        "/pvgis": {
            "inputs": {
                "meteo_data": {"year_min": 2005, "year_max": 2023, "radiation_db": "SARAH3"}
            },
            "outputs": {
                "months_selected": [{"month": 1, "year": 2007}],
                "tmy_hourly": [{"T2m": 10}],
            },
        },
    }
    with m.Collector(
        tmp_path,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payloads[r.url.path])),
        spacing=0,
    ) as c:
        c.collect(m.Request("cds-era5", "cds", "https://example.org/cds", "metadata", "extent"))
        c.collect(
            m.Request("pvgis-london", "pvgis", "https://example.org/pvgis", "probe", "period")
        )
    a = importlib.import_module("mcp_research.analysis").analyze(tmp_path)
    assert a["ledger_sha256"] == hashlib.sha256((tmp_path / "ledger.json").read_bytes()).hexdigest()
    assert a["source_checksums"]["cds-era5"] == hashlib.sha256(
        (tmp_path / "raw/cds-era5.body").read_bytes()).hexdigest()
    assert a["inventories"]["cds-era5"]["extent"]["spatial"]["bbox"] == [[0, -89, 360, 89]]
    assert a["inventories"]["pvgis-london"]["temporal_kind"] == "tmy_reference_period"
    assert "tmy_hourly" not in a["inventories"]["pvgis-london"]


def test_known_oversize_is_rejected_without_reading_body(tmp_path):
    m = research()

    class NeverRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("Known oversize response must not be consumed")
            yield b""

    with m.Collector(
        tmp_path,
        limits=m.Limits(ordinary_bytes=10),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"content-length": "100"}, stream=NeverRead())
        ),
        spacing=0,
    ) as c:
        assert c.collect(spec(m))["outcome"] == "byte_limit"
        assert c.ledger["charged_bytes"] == 0


def test_auth_headers_are_not_accepted_for_public_research(tmp_path):
    m = research()
    with m.Collector(tmp_path, spacing=0) as c:
        with pytest.raises(ValueError, match="headers"):
            c.collect(spec(m, headers={"Authorization": "Bearer private-key"}))
    assert "private-key" not in (tmp_path / "ledger.json").read_text()


def test_total_deadline_includes_redirect_chain(tmp_path):
    import asyncio

    m = research()

    async def handler(r):
        await asyncio.sleep(0.04)
        return httpx.Response(302, headers={"location": "/next"})

    with m.Collector(
        tmp_path, transport=httpx.MockTransport(handler), spacing=0, deadline=0.06
    ) as c:
        assert c.collect(spec(m))["outcome"] == "deadline"
        assert c.ledger["counts"]["metadata"] <= 2


def test_noaa_inventory_exception_is_scoped_to_exact_host_and_path(tmp_path):
    m = research()
    payload = b"x" * 5_000_001
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=payload))
    with m.Collector(tmp_path, transport=transport, spacing=0) as c:
        allowed = m.Request(
            "noaa-large",
            "noaa",
            "https://www.ncei.noaa.gov/pub/data/noaa/isd-inventory.csv",
            "inventory",
            "Authorized larger inventory",
            limit=20_000_000,
        )
        assert c.collect(allowed)["outcome"] == "saved"
        other = m.Request(
            "noaa-other",
            "noaa",
            "https://example.org/pub/data/noaa/isd-inventory.csv",
            "inventory",
            "No allowance for other hosts",
            limit=20_000_000,
        )
        assert c.collect(other)["outcome"] == "byte_limit"


def test_noaa_month_counts_preserve_sparse_years_and_unknown_quality():
    research()
    a = importlib.import_module("mcp_research.analysis")
    assert hasattr(a, "station_counts"), "Station/month inventory normalization missing"
    header = "USAF,WBAN,YEAR,JAN,FEB,MAR,APR,MAY,JUN,JUL,AUG,SEP,OCT,NOV,DEC\n"
    rows = (
        "001234,00001,2020,744,0,1500,0,0,0,0,0,0,0,0,0\n"
        "001234,00001,2022,1,0,0,0,0,0,0,0,0,0,0,0\n"
    )
    result = a.station_counts((header + rows).encode())
    assert result["station_years"] == {
        "00123400001": {
            "2020": [744, 0, 1500, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "2022": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        }
    }
    assert result["year_counts"] == {"2020": 1, "2022": 1}
    assert result["hourly_completeness"] == "unknown"
    assert result["variable_completeness"] == "unknown"


def test_noaa_count_conflicts_are_not_silently_overwritten():
    research()
    a = importlib.import_module("mcp_research.analysis")
    assert hasattr(a, "station_counts"), "Station/month inventory normalization missing"
    header = "USAF,WBAN,YEAR,JAN,FEB,MAR,APR,MAY,JUN,JUL,AUG,SEP,OCT,NOV,DEC\n"
    rows = "001234,00001,2020,1,0,0,0,0,0,0,0,0,0,0,0\n001234,00001,2020,2,0,0,0,0,0,0,0,0,0,0,0\n"
    with pytest.raises(ValueError, match="Conflicting"):
        a.station_counts((header + rows).encode())


def test_noaa_alphanumeric_station_identifiers_are_preserved():
    research()
    a = importlib.import_module("mcp_research.analysis")
    raw = (
        "USAF,WBAN,YEAR,JAN,FEB,MAR,APR,MAY,JUN,JUL,AUG,SEP,OCT,NOV,DEC\n"
        "A00002,53928,2024,1,0,0,0,0,0,0,0,0,0,0,0\n"
    ).encode()
    assert a.station_counts(raw)["station_years"]["A0000253928"]["2024"][0] == 1


def test_failed_inventory_analysis_returns_nonzero_status(tmp_path):
    m = research()
    with m.Collector(
        tmp_path,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"not a valid inventory")
        ),
        spacing=0,
    ) as c:
        c.collect(
            m.Request(
                "bad-noaa",
                "noaa",
                "https://www.ncei.noaa.gov/pub/data/noaa/isd-inventory.csv",
                "inventory",
                "Synthetic malformed catalog",
            )
        )
    cli = importlib.import_module("probe_mcp_availability")
    for command in ("analyze", "report"):
        assert cli.main([command, "--root", str(tmp_path)]) == 1


def test_authorized_oedi_budget_retains_charges_and_survives_resume(tmp_path):
    m = research()
    payload = b"x" * 6_740_745
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            206,
            content=payload,
            headers={
                "Content-Range": "bytes 100-6740844/9000000",
                "ETag": '"v1"',
            },
        )
    )
    request = m.Request(
        "authorized-directory",
        "oedi",
        "https://data.openei.org/files/5974/RCP4.5_v1.1.zip",
        "metadata",
        "Approved bounded follow-up",
        archive="rcp45",
        limit=len(payload),
        headers={"Range": "bytes=100-6740844", "If-Match": '"v1"'},
    )
    with m.Collector(tmp_path, transport=transport, spacing=0) as c:
        c.ledger["archive_bytes"]["rcp45"] = 5_075_668
        c.ledger["charged_bytes"] = 5_075_668
        c.save()
        assert c.collect(request)["outcome"] == "saved"
    with m.Collector(tmp_path, transport=transport, spacing=0) as c:
        assert c.ledger["archive_bytes"]["rcp45"] == 11_816_413
        assert c.collect(request)["outcome"] == "saved"
        assert c.ledger["counts"]["metadata"] == 1
        assert (
            c.collect(
                m.Request(
                    "second-directory",
                    "oedi",
                    request.url,
                    "metadata",
                    "Must not exceed cumulative allowance",
                    archive="rcp45",
                    limit=len(payload),
                    headers=request.headers,
                )
            )["outcome"]
            == "byte_limit"
        )


def test_onebuilding_matches_require_country_name_and_unambiguous_id():
    a = importlib.import_module("mcp_research.analysis")
    assert hasattr(a, "coordinate_matches")
    url = "https://climate.onebuilding.org/AUS_NSW_Sydney.AP.947670_TMYx.2011-2025.zip"
    site = dict(id="94767099999", country="AS", name="SYDNEY AIRPORT", lat=-33.9, lon=151.2)
    result = a.coordinate_matches([url], [site], [])
    assert result[0]["coordinate_basis"] == "station_identifier_and_name"
    assert result[0]["period"] == "2011-2025"
    assert result[0]["epw_coordinates_verified"] is False
    assert a.coordinate_matches([url], [dict(site, country="US")], [])[0]["lat"] is None
    assert a.coordinate_matches([url], [dict(site, name="UNRELATED")], [])[0]["lat"] is None
    other = dict(site, id="94767012345", lat=-35)
    assert a.coordinate_matches([url], [site, other], [])[0]["coordinate_basis"] == "unknown"
    assert a.coordinate_matches([url.replace("947670", "123")], [site], [])[0]["lat"] is None


def test_onebuilding_published_coordinates_preserve_conflicts():
    a = importlib.import_module("mcp_research.analysis")
    assert hasattr(a, "coordinate_matches")
    url = "https://climate.onebuilding.org/USA_NY_Ithaca.AP.725155_TMYx.zip"
    row = dict(url=url, lat=42.5, lon=-76.5, elevation_m=100, evidence_id="map")
    result = a.coordinate_matches([url], [], [row])[0]
    assert result["coordinate_basis"] == "published_product_index"
    assert result["evidence_ids"] == ["map"]
    result = a.coordinate_matches([url], [], [row, dict(row, lat=40)])[0]
    assert result["coordinate_basis"] == "unknown"
    assert result["reason"] == "conflicting_published_coordinates"


def test_onebuilding_retains_cross_source_coordinate_disagreement():
    a = importlib.import_module("mcp_research.analysis")
    url = "https://climate.onebuilding.org/USA_NY_Ithaca.AP.725155_TMYx.zip"
    published = dict(url=url, lat=42.5, lon=-76.5, elevation_m=100, evidence_id="map")
    noaa = dict(id="72515594761", country="US", name="ITHACA AIRPORT", lat=43, lon=-77)
    result = a.coordinate_matches([url], [noaa], [published])[0]
    assert result["coordinate_disagreement"] is True
    assert result["noaa_candidates"][0]["lat"] == 43
    assert result["lat"] == 42.5
    assert set(result["evidence_ids"]) == {"map", "noaa-history"}


@pytest.mark.parametrize("cell", ['<c r="A1" t="inlineStr"/>', '<c r="A1" t="s"><v>-1</v></c>'])
def test_malformed_coordinate_cells_fail_safely(cell):
    a = importlib.import_module("mcp_research.coordinates")
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData><row>{cell}</row></sheetData></worksheet>',
        )
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}"><si><t>Country</t></si></sst>')
    with pytest.raises(ValueError, match="Invalid (inline|shared) string"):
        a.spreadsheet_rows(buf.getvalue(), "synthetic")


def test_oedi_summary_does_not_hide_missing_years_or_unmatched_sites():
    a = importlib.import_module("mcp_research.archives")
    assert hasattr(a, "membership_summary")
    names = [
        "RCP4.5/",
        "RCP4.5/G1_RCP4.5_2045_lat1_long2.epw",
        "RCP4.5/G2_RCP4.5_2046_lat1_long2.epw",
        "RCP4.5/mystery.epw",
    ]
    result = a.membership_summary(names, {"G1"}, "RCP4.5")
    assert result["sites_with_all_expected_years"] == 0
    assert result["sites_without_location_record"] == 1
    assert result["unparsed_epw_members"] == 1
    assert result["weather_completeness"] == "unknown"


def test_coordinate_spreadsheet_preserves_ids_and_rejects_invalid_points():
    import xml.etree.ElementTree as E

    a = importlib.import_module("mcp_research.coordinates")
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = E.Element("worksheet", xmlns=ns)
    data = E.SubElement(root, "sheetData")
    header = [
        "Country",
        "City/Station",
        "WMO",
        "Latitude (N+/S-)",
        "Longitude (E+/W-)",
        "Elevation (m)",
        "URL",
    ]
    url = "https://climate.onebuilding.org/GBR_ENG_London.037720_TMYx.zip"
    for index, values in enumerate(
        [
            header,
            [
                "GBR",
                "London",
                "037720",
                "51.5",
                "-0.1",
                "",
                "https://climate.onebuilding.org/GBR_ENG_London.037720_TMYx.zip",
            ],
            ["GBR", "Bad", "000001", "999", "0", "0", url],
        ],
        1,
    ):
        row = E.SubElement(data, "row", r=str(index))
        for col, value in enumerate(values):
            cell = E.SubElement(row, "c", r=f"{chr(65 + col)}{index}", t="inlineStr")
            E.SubElement(E.SubElement(cell, "is"), "t").text = value
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", E.tostring(root))
    result = a.spreadsheet_rows(buf.getvalue(), "synthetic")
    assert result["rows"][0]["station_id"] == "037720"
    assert result["rows"][0]["elevation_m"] is None
    assert len(result["rows"]) == 1
    assert result["invalid_rows"] == 1
