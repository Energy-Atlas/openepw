"""Compatibility re-export until the chat coordinator is retired (P5).

The product catalogue now lives in ``openepw.availability.products``.
"""

from ..availability.products import (
    FIXED_PRODUCTS,
    MAX_CALLOUT_LOCATIONS,
    STATION_LAYERS,
    Product,
    onebuilding_product,
    point_availability,
    product_for,
    product_offers,
)

__all__ = ["FIXED_PRODUCTS", "MAX_CALLOUT_LOCATIONS", "STATION_LAYERS", "Product",
           "onebuilding_product", "point_availability", "product_for", "product_offers"]
