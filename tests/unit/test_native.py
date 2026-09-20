import io
import zipfile

import pytest

from openepw.models import OpenEPWError
from openepw.providers.onebuilding import catalog_links, extract_epw


def test_native_zip_rejects_traversal_and_ambiguous_members():
    for names in [["../bad.epw"], ["a.epw", "b.epw"], ["a.txt"]]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            for name in names:
                z.writestr(name, b"not real weather")
        with pytest.raises(OpenEPWError):
            extract_epw(stream.getvalue())


def test_catalog_handles_relative_links_without_external_urls():
    links = catalog_links(
        '<a href="NY_New_York/test.zip">x</a><a href="https://evil.example/other.zip">y</a>',
        "https://climate.onebuilding.org/USA/index.html",
    )
    assert links == ["https://climate.onebuilding.org/USA/NY_New_York/test.zip"]
