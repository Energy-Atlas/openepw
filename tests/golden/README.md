# Synthetic reference weather

`tests/unit/test_epw.py::synthetic` generates small, annual and leap-year inputs
deterministically. Expected timestamps, fields, sentinels and statistics are
asserted independently. No provider weather or uncertain-license fixtures are
committed. Real downloaded artifacts stay in ignored `.local/` and are exercised
only by explicitly enabled live checks.
