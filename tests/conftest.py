"""Shared test setup: keep every test away from the real data folder and the network."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path_factory.mktemp("jhdata")))
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    monkeypatch.setenv("JOBHUNTER_NO_DOWNLOAD", "1")  # even CLI tests, whose profiles default to auto-download
    from jobhunter import datasets, embed, visa, wages

    def no_network(*a, **k):
        raise AssertionError("tests must not call BLS")
    monkeypatch.setattr(wages, "_request", no_network)
    datasets.configure(auto_download=False)
    datasets._directory.cache_clear()
    visa._sponsors.cache_clear()
    embed.wanted.cache_clear()
    monkeypatch.setattr(embed, "available", lambda: False)  # the optional model stays out of unit tests
    yield
