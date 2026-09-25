"""Deterministic, explained ordering of eligible source options."""

from __future__ import annotations

from .models import AvailabilityQuery, AvailabilityResult, FutureAvailabilityQuery


def rank(result: AvailabilityResult, query: AvailabilityQuery) -> AvailabilityResult:
    """Rank each input occurrence independently, retaining uncertain alternatives."""
    ranked = result.model_copy(deep=True)
    provider_order = (query.request.providers if not isinstance(query, FutureAvailabilityQuery)
                      else [])
    status_order = {"supported": 0, "unknown": 1, "excluded": 2}
    for location in ranked.locations:
        options = [option for option in ranked.options
                   if option.occurrence_index == location.occurrence_index]
        for option in options:
            if query.purpose == "thermal_extremes" and option.product.temporal_kind == "tmy_reference":
                option.reasons.append("TYPICAL_YEAR_LIMITATION")
            if query.purpose == "solar" and set(option.missing_preferred_variables) & {
                "ghi", "dni", "dhi"
            }:
                option.reasons.append("MISSING_PREFERRED_RADIATION")
            elif option.missing_preferred_variables:
                option.reasons.append("MISSING_PREFERRED_VARIABLES")
            if option.eligibility.status == "unknown":
                option.reasons.extend(option.eligibility.unknowns)
            if option.eligibility.status == "excluded":
                option.reasons.extend(option.eligibility.reasons)
        options.sort(key=lambda option: (
            status_order[option.eligibility.status],
            len(option.missing_preferred_variables),
            option.distance_km if option.distance_km is not None else float("inf"),
            option.elevation_delta_m if option.elevation_delta_m is not None else float("inf"),
            0 if not option.eligibility.stale else 1,
            0 if option.eligibility.access == "ready" else 1,
            provider_order.index(option.product.provider) if option.product.provider in provider_order
            else len(provider_order),
            option.id,
        ))
        location.ranked_option_ids = [option.id for option in options]
        location.recommended_option_ids = ([options[0].id] if options and
                                           options[0].eligibility.status == "supported" else [])
        for position, option in enumerate(options, start=1):
            option.rank = position
    return ranked
