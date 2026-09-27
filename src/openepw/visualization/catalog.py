"""Finite, versioned visualization and variable vocabulary."""

from ..dataset import UNITS

INITIAL_FAMILIES = (
    "time_series", "annual_series", "monthly_series", "histogram", "spatial",
)
PLANNED_FAMILIES = (
    "month_of_year_profile", "diurnal_profile", "seasonal_summary",
    "calendar_heatmap", "month_hour_heatmap", "cumulative_distribution",
    "duration_curve", "box_plot", "scatter", "correlation_matrix",
    "wind_rose", "psychrometric", "threshold_timeline",
    "extreme_event_timeline", "difference_series", "anomaly_series",
    "summary_table",
)
FAMILIES = INITIAL_FAMILIES + PLANNED_FAMILIES

VARIABLES = {
    "dry_bulb": {"unit": UNITS["dry_bulb"], "aggregations": ["mean", "min", "max"]},
    "dew_point": {"unit": UNITS["dew_point"], "aggregations": ["mean", "min", "max"]},
    "relative_humidity": {"unit": UNITS["relative_humidity"],
                          "aggregations": ["mean", "min", "max"]},
    "pressure": {"unit": UNITS["pressure"], "aggregations": ["mean", "min", "max"]},
    "wind_speed": {"unit": UNITS["wind_speed"], "aggregations": ["mean", "min", "max"]},
    "wind_direction": {"unit": UNITS["wind_direction"], "aggregations": []},
    "ghi": {"unit": UNITS["ghi"], "aggregations": ["sum", "mean", "min", "max"]},
    "dni": {"unit": UNITS["dni"], "aggregations": ["sum", "mean", "min", "max"]},
    "dhi": {"unit": UNITS["dhi"], "aggregations": ["sum", "mean", "min", "max"]},
}


def capabilities() -> dict:
    return {
        "schema_version": "1",
        "families": [
            {"family": family, "status": "implemented" if family in INITIAL_FAMILIES
             else "planned", "supported_options": ["bins"] if family == "histogram" else [],
             "accepts_aggregation": family in ("annual_series", "monthly_series", "spatial")}
            for family in FAMILIES
        ],
        "variables": VARIABLES,
        "limits": {"source_epws": 100, "hourly_rows": 20_000,
                   "histogram_bins": 50, "page_rows": 200},
    }
