"""Synthetic coordinate evidence tests; no network or weather acceptance."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from mcp_research import analysis, coordinates


def test_diagnostics_count_products_not_period_ranges():
    matches = [dict(url=k, station_id='001234', product=f'TMYx.{period}',
                    country='USA', coordinate_basis='unknown', noaa_candidates=[])
               for k, period in [('a', '2004-2018'), ('b', '2011-2025')]]
    result = analysis.coordinate_diagnostics(matches, [])
    assert result['product_count'] == 2
    assert result['unresolved_reason_counts'] == {'no_coordinate_bearing_identifier': 2}
    assert result['product_family_counts'] == {'TMYx': 2}


def test_diagnostics_distinguish_identity_from_name():
    history = [dict(id='00123400001', country='US', name='EXAMPLE AIRPORT'),
               dict(id='00123499999', country='US', name='EXAMPLE')]
    base = dict(station_id='001234', country='USA', product='TMY3', coordinate_basis='unknown')
    matches = [dict(base, url='a', noaa_candidates=history),
               dict(base, url='b', noaa_candidates=[])]
    assert analysis.coordinate_diagnostics(matches, history)['unresolved_reason_counts'] == {
        'ambiguous_station_identity': 1, 'name_not_corroborated': 1}


@pytest.mark.parametrize('left,right,expected', [
    ('Hay.AP', 'HAY AIRPORT AWS', 'exact_short_name'),
    ('Hay.AP', 'RAY AIRPORT AWS', 'none'),
    ('Regional.AP', 'REGIONAL AIRPORT', 'none'),
    ('Ithaca.Tompkins.Rgnl.AP', 'ITHACA TOMPKINS REGIONAL AIRPORT', 'token_overlap'),
    ('Unalaska-Madsen.AP', 'DUTCH HARBOR AIRPORT', 'none'),
])
def test_name_evidence(left, right, expected):
    assert coordinates.name_evidence(left, right) == expected


def test_country_codes_remain_explicit():
    assert coordinates.country_evidence('AUS', ['AS'])['status'] == 'consistent'
    assert coordinates.country_evidence('AUS', ['AU'])['status'] == 'ambiguous'
    assert coordinates.country_evidence('USA', ['CA'])['status'] == 'conflicting'
    assert coordinates.country_evidence('AUS', [])['status'] == 'ambiguous'


def test_hay_recovers_but_au_requires_independent_evidence():
    url = 'https://climate.onebuilding.org/AUS_NSW_Hay.AP.947020_TMYx.zip'
    site = dict(id='94702099999',country='AS',name='HAY AIRPORT AWS',lat=-34.533,lon=144.833)
    result = coordinates.coordinate_matches([url],[site],[])[0]
    assert result['lat'] == -34.533
    assert result['name_match_method'] == 'exact_short_name'
    result = coordinates.coordinate_matches([url],[dict(site,country='AU')],[])[0]
    assert result['lat'] is None
    assert result['country_evidence']['status'] == 'ambiguous'
