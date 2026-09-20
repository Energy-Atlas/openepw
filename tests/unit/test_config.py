from openepw.config import RuntimeConfig


def test_precedence_and_secret_redaction(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[credentials]\nnlr_api_key="file-value"\n')
    monkeypatch.setenv("OPENEPW_NLR_API_KEY", "env-value")
    assert RuntimeConfig.load(path).nlr_api_key.get_secret_value() == "env-value"
    config = RuntimeConfig.load(path, nlr_api_key="test-secret-value")
    assert config.nlr_api_key.get_secret_value() == "test-secret-value"
    assert "test-secret-value" not in repr(config)
    assert "test-secret-value" not in config.model_dump_json()
