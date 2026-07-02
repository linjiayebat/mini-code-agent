from pathlib import Path

import pytest

from mini_code_agent.config import (
    AppSettings,
    ConfigurationError,
    LogLevel,
    ProviderName,
    load_settings,
)


@pytest.fixture(autouse=True)
def clear_project_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MINI_CODE_AGENT_LOG_LEVEL",
        "MINI_CODE_AGENT_DATA_DIR",
        "MINI_CODE_AGENT_TRACE_ENABLED",
        "MINI_CODE_AGENT_ANTHROPIC_API_KEY",
        "MINI_CODE_AGENT_OPENAI_API_KEY",
        "MINI_CODE_AGENT_PROVIDER",
        "MINI_CODE_AGENT_MODEL",
        "MINI_CODE_AGENT_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_valid_without_a_config_file(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.toml")

    assert settings.log_level is LogLevel.INFO
    assert settings.trace_enabled is True
    assert settings.provider is ProviderName.OPENAI_COMPATIBLE
    assert settings.model is None
    assert settings.base_url is None
    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None


def test_precedence_is_defaults_then_file_then_env_then_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mini_code_agent]
log_level = "warning"
trace_enabled = false
data_dir = "from-file"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINI_CODE_AGENT_LOG_LEVEL", "error")
    monkeypatch.setenv("MINI_CODE_AGENT_DATA_DIR", str(tmp_path / "from-env"))

    settings = load_settings(
        config_path=config_path,
        overrides={"log_level": "debug"},
    )

    assert settings.log_level is LogLevel.DEBUG
    assert settings.trace_enabled is False
    assert settings.data_dir == tmp_path / "from-env"


def test_safe_dict_never_contains_secret_values(tmp_path: Path) -> None:
    settings = AppSettings.model_validate(
        {
            "data_dir": tmp_path,
            "provider": "openai_compatible",
            "model": "Pro/zai-org/GLM-4.7",
            "base_url": "https://api.siliconflow.cn/v1",
            "anthropic_api_key": "anthropic-secret",
            "openai_api_key": "openai-secret",
        }
    )

    payload = settings.safe_dict()
    rendered = str(payload)

    assert "anthropic-secret" not in rendered
    assert "openai-secret" not in rendered
    assert payload["provider"] == "openai_compatible"
    assert payload["model"] == "Pro/zai-org/GLM-4.7"
    assert payload["base_url"] == "https://api.siliconflow.cn/v1"
    assert payload["anthropic_api_key_configured"] is True
    assert payload["openai_api_key_configured"] is True


def test_provider_environment_overrides_file_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mini_code_agent]
provider = "anthropic"
model = "claude-from-file"
base_url = "https://provider-from-file.example"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MINI_CODE_AGENT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("MINI_CODE_AGENT_MODEL", "Pro/zai-org/GLM-4.7")
    monkeypatch.setenv("MINI_CODE_AGENT_BASE_URL", "https://api.siliconflow.cn/v1")

    settings = load_settings(config_path=config_path)

    assert settings.provider is ProviderName.OPENAI_COMPATIBLE
    assert settings.model == "Pro/zai-org/GLM-4.7"
    assert settings.base_url == "https://api.siliconflow.cn/v1"


def test_invalid_toml_section_has_an_actionable_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("mini_code_agent = 42", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="must be a TOML table"):
        load_settings(config_path=config_path)


def test_validation_error_does_not_expose_secret_input(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[mini_code_agent]
openai_api_key = { value = "validation-secret" }
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as captured:
        load_settings(config_path=config_path)

    assert "validation-secret" not in str(captured.value)


def test_invalid_environment_value_raises_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINI_CODE_AGENT_LOG_LEVEL", "definitely-invalid")

    with pytest.raises(ConfigurationError, match="Invalid application configuration"):
        load_settings(config_path=tmp_path / "missing.toml")
