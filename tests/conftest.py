import os

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "live" in item.keywords and os.getenv("OPENEPW_RUN_LIVE") != "1":
            item.add_marker(
                pytest.mark.skip(reason="Set OPENEPW_RUN_LIVE=1 for network acceptance")
            )
