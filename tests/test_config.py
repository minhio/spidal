import json
import os

import pytest
from pytest_mock import MockerFixture

from spidal.config import Config


@pytest.fixture(autouse=True)
def _isolate_config_file(mocker: MockerFixture, tmp_path):
    """Prevent tests from reading/writing the real config file."""
    config_file = tmp_path / "spidal" / "config.json"
    mocker.patch("spidal.config.CONFIG_DIR", tmp_path / "spidal")
    mocker.patch("spidal.config.CONFIG_FILE", config_file)


class TestLoad:
    def test_defaults(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {}, clear=True)
        config = Config.load()
        assert config.spotify_token is None
        assert config.hifi_api is None
        assert (
            config.hifi_api_file
            == "https://raw.githubusercontent.com/monochrome-music/monochrome/main/public/instances.json"
        )

    def test_download_dir_default(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {}, clear=True)
        config = Config.load()
        assert config.download_dir is not None
        assert "spidal" in config.download_dir

    def test_overrides_take_priority(self):
        config = Config.load(spotify_token="tok123")
        assert config.spotify_token == "tok123"

    def test_env_vars(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"SPIDAL_SPOTIFY_TOKEN": "env_tok"})
        config = Config.load()
        assert config.spotify_token == "env_tok"

    def test_overrides_beat_env_vars(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"SPIDAL_SPOTIFY_TOKEN": "env_tok"})
        config = Config.load(spotify_token="cli_tok")
        assert config.spotify_token == "cli_tok"

    def test_env_vars_beat_defaults(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"SPIDAL_HIFI_API_FILE": "/some/path.json"})
        config = Config.load()
        assert config.hifi_api_file == "/some/path.json"

    def test_cannot_set_both_hifi_api_and_hifi_api_file(self):
        with pytest.raises(ValueError, match="Cannot set both"):
            Config.load(hifi_api="https://api.example.com", hifi_api_file="/path.json")

    def test_audio_quality_default(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {}, clear=True)
        config = Config.load()
        assert config.audio_quality == "HI_RES_LOSSLESS"

    def test_audio_quality_env_var(self, mocker: MockerFixture):
        mocker.patch.dict(os.environ, {"SPIDAL_AUDIO_QUALITY": "LOSSLESS"})
        config = Config.load()
        assert config.audio_quality == "LOSSLESS"

    def test_audio_quality_override(self):
        config = Config.load(audio_quality="HIGH")
        assert config.audio_quality == "HIGH"

    def test_audio_quality_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid audio-quality"):
            Config.load(audio_quality="INVALID")


class TestGetApis:
    def test_hifi_api_returns_single_item(self):
        config = Config(hifi_api="https://api.example.com")
        assert config.get_apis() == ["https://api.example.com"]

    def test_neither_set_returns_empty(self):
        config = Config()
        assert config.get_apis() == []

    def test_hifi_api_file_local(self, tmp_path):
        api_file = tmp_path / "instances.json"
        api_file.write_text(json.dumps({"api": ["https://a.com", "https://b.com"]}))
        config = Config(hifi_api_file=str(api_file))
        assert config.get_apis() == ["https://a.com", "https://b.com"]

    def test_hifi_api_file_url(self, mocker: MockerFixture):

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"api": ["https://a.com"]}
        mock_get = mocker.patch("spidal.config.requests.get", return_value=mock_resp)
        config = Config(hifi_api_file="https://example.com/instances.json")
        assert config.get_apis() == ["https://a.com"]
        mock_get.assert_called_once_with("https://example.com/instances.json")

    def test_result_is_cached(self, mocker: MockerFixture):

        mock_resp = mocker.Mock()
        mock_resp.json.return_value = {"api": ["https://a.com"]}
        mock_get = mocker.patch("spidal.config.requests.get", return_value=mock_resp)
        config = Config(hifi_api_file="https://example.com/instances.json")
        config.get_apis()
        config.get_apis()
        mock_get.assert_called_once()

    def test_returns_all_apis(self, tmp_path):
        api_file = tmp_path / "instances.json"
        api_file.write_text(
            json.dumps({"api": ["https://a.com", "https://b.com", "https://c.com"]})
        )
        config = Config(hifi_api_file=str(api_file))
        assert config.get_apis() == ["https://a.com", "https://b.com", "https://c.com"]

    def test_invalid_json_missing_api_key(self, tmp_path):
        api_file = tmp_path / "bad.json"
        api_file.write_text(json.dumps({"other": "data"}))
        config = Config(hifi_api_file=str(api_file))
        with pytest.raises(ValueError, match="Expected JSON object with an 'api' key"):
            config.get_apis()

    def test_invalid_json_api_not_list(self, tmp_path):
        api_file = tmp_path / "bad.json"
        api_file.write_text(json.dumps({"api": "not-a-list"}))
        config = Config(hifi_api_file=str(api_file))
        with pytest.raises(ValueError, match="Expected 'api' to be a list"):
            config.get_apis()


class TestConfigFile:
    def test_cli_overrides_not_persisted(self, tmp_path):
        Config.load(spotify_token="tok123")
        assert not (tmp_path / "spidal" / "config.json").exists()

    def test_loads_from_config_file(self, mocker: MockerFixture, tmp_path):
        config_dir = tmp_path / "spidal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"spotify-token": "saved_tok"})
        )
        mocker.patch.dict(os.environ, {}, clear=True)
        config = Config.load()
        assert config.spotify_token == "saved_tok"

    def test_cli_overrides_beat_config_file(self, tmp_path):
        config_dir = tmp_path / "spidal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"spotify-token": "saved_tok"})
        )
        config = Config.load(spotify_token="cli_tok")
        assert config.spotify_token == "cli_tok"

    def test_config_file_beats_env_vars(self, mocker: MockerFixture, tmp_path):
        config_dir = tmp_path / "spidal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"spotify-token": "saved_tok"})
        )
        mocker.patch.dict(os.environ, {"SPIDAL_SPOTIFY_TOKEN": "env_tok"})
        config = Config.load()
        assert config.spotify_token == "saved_tok"

    def test_cli_overrides_dont_modify_existing_config_file(self, tmp_path):
        config_dir = tmp_path / "spidal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"spotify-token": "saved_tok"})
        )
        Config.load(hifi_api_file="/new/path.json")
        saved = json.loads((config_dir / "config.json").read_text())
        assert saved.get("hifi-api-file") is None
        assert saved["spotify-token"] == "saved_tok"

    def test_audio_quality_from_config_file(self, mocker: MockerFixture, tmp_path):
        config_dir = tmp_path / "spidal"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(json.dumps({"audio-quality": "LOW"}))
        mocker.patch.dict(os.environ, {}, clear=True)
        config = Config.load()
        assert config.audio_quality == "LOW"
