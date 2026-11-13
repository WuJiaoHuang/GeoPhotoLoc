import os

import pytest

from geophotoloc.config import ConfigurationError, VisionConfig


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for key in list(os.environ):
        if key.startswith("GEOPHOTOLOC_VLM_"):
            monkeypatch.delenv(key)


def test_missing_api_key(tmp_path):
    with pytest.raises(ConfigurationError, match="Missing GEOPHOTOLOC_VLM_API_KEY"):
        VisionConfig.from_env(tmp_path / ".env")


def test_existing_dotenv_preserved_and_precedence(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = (
        "GEOPHOTOLOC_VLM_API_KEY=file-test-key\nGEOPHOTOLOC_VLM_MODEL=qwen3.8-flash\n"
        "GEOPHOTOLOC_VLM_TIMEOUT=12\nGEOPHOTOLOC_VLM_MAX_RETRIES=1\n"
    )
    path.write_text(original, encoding="utf-8")
    before = dict(os.environ)
    config = VisionConfig.from_env(path)
    assert config.timeout == 12
    assert config.max_retries == 1
    assert config.api_key.get_secret_value() == "file-test-key"
    assert config.model == "qwen3.8-flash"
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert dict(os.environ) == before
    monkeypatch.setenv("GEOPHOTOLOC_VLM_API_KEY", "environment-test-key")
    assert VisionConfig.from_env(path).api_key.get_secret_value() == "environment-test-key"
    assert path.read_text(encoding="utf-8") == original
    assert "environment-test-key" not in repr(VisionConfig.from_env(path))


@pytest.mark.parametrize("variable,value", [
    ("API_KEY", " "), ("MODEL", " "), ("TIMEOUT", "0"), ("TIMEOUT", "nan"),
    ("TIMEOUT", "abc"), ("MAX_RETRIES", "-1"), ("MAX_RETRIES", "1.5"),
    ("BASE_URL", "file:///secret-test-key"),
    ("BASE_URL", "https://user:secret-test-key@example.com"),
])
def test_invalid_configuration_safe_errors(tmp_path, monkeypatch, variable, value):
    monkeypatch.setenv("GEOPHOTOLOC_VLM_API_KEY", "secret-test-key")
    monkeypatch.setenv("GEOPHOTOLOC_VLM_" + variable, value)
    with pytest.raises(ConfigurationError) as caught:
        VisionConfig.from_env(tmp_path / ".env")
    assert "secret-test-key" not in str(caught.value)


def test_no_dotenv_variable_interpolation(tmp_path):
    path = tmp_path / ".env"
    path.write_text("GEOPHOTOLOC_VLM_API_KEY=test-${NOT_A_VARIABLE}\n", encoding="utf-8")
    assert VisionConfig.from_env(path).api_key.get_secret_value() == "test-${NOT_A_VARIABLE}"
