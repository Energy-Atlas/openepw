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
