import os

import pytest

_TRACING = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")


def pytest_collection_modifyitems(items):
    for item in items:
        if "live" in item.keywords and os.getenv("OPENEPW_RUN_LIVE") != "1":
            item.add_marker(
                pytest.mark.skip(reason="Set OPENEPW_RUN_LIVE=1 for network acceptance")
            )


@pytest.fixture(autouse=True)
def offline_environment(request, monkeypatch, tmp_path_factory):
    """Keep offline tests independent of the developer's working directory and keys.

    Code that defaults to ".env" reads the working directory's file. In the main checkout that file
    turns on LangSmith tracing with a real key, and in a worktree there is no key at all, so results
    depended on where pytest ran. Live tests keep the real environment.
    """
    if "live" in request.keywords:
        return
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-offline-not-real")
    for name in _TRACING:
        monkeypatch.delenv(name, raising=False)
