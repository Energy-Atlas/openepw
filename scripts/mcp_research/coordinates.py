"""Local research joins; published index points are not verified EPW headers."""

import io
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from urllib.parse import unquote, urlsplit


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def spreadsheet_rows(raw, evidence_id):
    """Read the source's first coordinate sheet with stdlib and bounded XML expansion.

    No formulas, external relationships, macros or hyperlinks are executed/followed.
    Station identity comes from the product URL when numeric Excel cells drop zeros.
    """
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(i.file_size for i in archive.infolist()) > 40_000_000:
                raise ValueError("Expanded coordinate workbook exceeds bound")

            def xml(name):
                body = archive.read(name)
                if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                    raise ValueError("XML declarations are not permitted")
                return ET.fromstring(body)

            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = [
                    "".join(n.itertext()) for n in xml("xl/sharedStrings.xml").findall("s:si", ns)
                ]
            sheet = xml("xl/worksheets/sheet1.xml")
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise ValueError("Invalid coordinate workbook") from exc
    rows, header, invalid = [], None, 0
    for row in sheet.findall("s:sheetData/s:row", ns):
        values = {}
        for cell in row.findall("s:c", ns):
            col = re.sub(r"\d", "", cell.get("r", ""))
            if cell.find("s:f", ns) is not None:
                value = ""
            elif cell.get("t") == "inlineStr":
                inline = cell.find("s:is", ns)
                if inline is None:
                    raise ValueError("Invalid inline string")
                value = "".join(inline.itertext())
            else:
                value = cell.findtext("s:v", "", ns)
                if cell.get("t") == "s":
                    try:
                        index = int(value)
                        if not 0 <= index < len(strings):
                            raise ValueError("Invalid shared string reference")
                        value = strings[index]
                    except (ValueError, IndexError):
                        raise ValueError("Invalid shared string reference") from None
            values[col] = value
        if header is None:
            header = values
            required = {
                "Country",
                "City/Station",
                "WMO",
                "Latitude (N+/S-)",
                "Longitude (E+/W-)",
                "URL",
            }
            if not required <= set(header.values()):
                raise ValueError("Unrecognized coordinate sheet columns")
            continue
        values = {title: values.get(col, "") for col, title in header.items()}
        lat, lon = number(values.get("Latitude (N+/S-)")), number(values.get("Longitude (E+/W-)"))
        url = values.get("URL", "")
        parsed = product_identity(url)
        if (
            lat is None
            or lon is None
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
            or not parsed
            or urlsplit(url).hostname != "climate.onebuilding.org"
            or urlsplit(url).scheme != "https"
            or parsed["country"] != values["Country"]
        ):
            invalid += 1
            continue
        rows.append(
            dict(
                url=url,
                station_id=parsed["station_id"],
                inventory_station_id=values.get("WMO"),
                country=values["Country"],
                name=values["City/Station"],
                lat=lat,
                lon=lon,
                elevation_m=number(values.get("Elevation (m)")),
                evidence_id=evidence_id,
            )
        )
    return {
        "rows": rows,
        "count": len(rows),
        "invalid_rows": invalid,
        "coordinate_basis": "published_product_index",
        "epw_coordinates_verified": False,
    }


def product_identity(url):
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    match = re.fullmatch(r"([A-Z]{3})_([A-Z0-9]+)_(.+)\.([A-Z0-9]{6})_(.+)\.zip", name)
    if not match:
        return None
    country, state, name, station, product = match.groups()
    period = re.search(r"(?<!\d)(\d{4}-\d{4})(?!\d)", product)
    return dict(
        country=country,
        state=state,
        name=name,
        station_id=station,
        product=product,
        period=period.group(1) if period else None,
    )


GENERIC_NAMES = {
    'AP', 'AIRPORT', 'AWS', 'INTL', 'INTERNATIONAL', 'STATION', 'MUNI',
    'MUNICIPAL', 'RGNL', 'REGIONAL', 'COUNTY', 'FIELD', 'FLD',
}


def distinctive_name(name):
    text = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().upper()
    return [t for t in re.findall('[A-Z]+', text) if t not in GENERIC_NAMES]


def name_tokens(name):
    return {t for t in distinctive_name(name) if len(t) >= 4}


def name_evidence(product_name, station_name):
    if name_tokens(product_name) & name_tokens(station_name):
        return 'token_overlap'
    left, right = distinctive_name(product_name), distinctive_name(station_name)
    if left and left == right and all(len(t) >= 3 for t in left):
        return 'exact_short_name'
    return 'none'


def country_evidence(country, raw_codes):
    expected = {'USA': 'US', 'GBR': 'UK', 'AUS': 'AS'}.get(country)
    if not expected or not raw_codes or any(not c for c in raw_codes):
        status = 'ambiguous'
    elif country == 'AUS' and 'AU' in raw_codes:
        status = 'ambiguous'
    elif all(c == expected for c in raw_codes):
        status = 'consistent'
    else:
        status = 'conflicting'
    return {'raw_codes': sorted(set(raw_codes), key=lambda c: str(c)),
            'expected_code': expected, 'status': status}


def coordinate_consensus(candidates):
    ids = sorted({c['id'] for c in candidates})
    result = dict(lat=None, lon=None, elevation_m=None, position_status='unknown',
                  station_identity_status='unique_candidate' if len(ids)==1 else 'ambiguous' if ids else 'unknown',
                  source_station_id=ids[0] if len(ids)==1 else None, source_station_ids=ids)
    points = [(number(c.get('lat')),number(c.get('lon'))) for c in candidates]
    if not points or any(lat is None or lon is None or not -90<=lat<=90 or not -180<=lon<=180 for lat,lon in points):
        return result
    if len(set(points)) != 1:
        return result
    result.update(lat=points[0][0],lon=points[0][1],position_status='inferred' if len(ids)==1 else 'consensus')
    elevations = {number(c.get('elevation_m')) for c in candidates}
    if len(elevations)==1 and None not in elevations:
        result['elevation_m'] = next(iter(elevations))
    return result


def coordinate_matches(urls, history, published):
    by_id, by_url = defaultdict(list), defaultdict(list)
    for site in history:
        by_id[site["id"][:6]].append(site)
    for row in published:
        by_url[row["url"]].append(row)
    results = []
    for url in sorted(set(urls)):
        product = product_identity(url)
        result = dict(
            url=url,
            **(product or {}),
            lat=None,
            lon=None,
            elevation_m=None,
            coordinate_basis="unknown",
            epw_coordinates_verified=False,
            evidence_ids=[],
            reason="no_unambiguous_identifier_name_country_match",
        )
        published_rows = by_url.get(url, [])
        candidates = []
        raw_candidates = by_id[product['station_id']] if product else []
        result['country_evidence'] = country_evidence(
            product['country'] if product else '', [s.get('country') for s in raw_candidates])
        result['name_match_method'] = 'none'
        if product:
            candidates = [
                s
                for s in by_id[product["station_id"]]
                if country_evidence(product['country'], [s.get('country')])['status'] == 'consistent'
                and name_evidence(product['name'], s.get('name')) != 'none'
            ]
        if candidates:
            result['name_match_method'] = ('token_overlap' if any(
                name_evidence(product['name'], s.get('name')) == 'token_overlap' for s in candidates)
                else 'exact_short_name')
        result["noaa_candidates"] = [
            {k: s.get(k) for k in ("id", "name", "lat", "lon", "elevation_m")} for s in candidates
        ]
        consensus = coordinate_consensus(candidates)
        result.update({k: consensus[k] for k in ('station_identity_status','source_station_id','source_station_ids')})
        result['position_status'] = 'unknown'
        result["published_candidates"] = [
            {k: s.get(k) for k in ("lat", "lon", "elevation_m", "evidence_id")}
            for s in published_rows
        ]
        result["coordinate_disagreement"] = False
        if published_rows:
            points = {(r["lat"], r["lon"], r.get("elevation_m")) for r in published_rows}
            result["evidence_ids"] = sorted({r["evidence_id"] for r in published_rows})
            if len(points) == 1:
                result.update(zip(("lat", "lon", "elevation_m"), next(iter(points))))
                result.update(
                    coordinate_basis="published_product_index", reason="exact_product_url", position_status='published'
                )
            else:
                result["reason"] = "conflicting_published_coordinates"
            if candidates:
                result["evidence_ids"].append("noaa-history")
                result["coordinate_disagreement"] = any(
                    (s["lat"], s["lon"]) != (r["lat"], r["lon"])
                    or (
                        s.get("elevation_m") is not None
                        and r.get("elevation_m") is not None
                        and s["elevation_m"] != r["elevation_m"]
                    )
                    for s in candidates
                    for r in published_rows
                )
        elif product and consensus['lat'] is not None:
            result.update(consensus)
            result.update(coordinate_basis='station_identifier_and_name' if consensus['position_status']=='inferred' else 'station_coordinate_consensus',
                          evidence_ids=['noaa-history'], reason='identifier_country_name_coordinate_agreement')
        result['unresolved_reasons'] = [result['reason']] if result['position_status']=='unknown' else []
        results.append(result)
    return results
