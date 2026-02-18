"""Tests for commands/config.py — config get, set, list."""
from __future__ import annotations

from typer.testing import CliRunner

from spidal.cli import app

runner = CliRunner()


class TestConfigSet:
    def test_sets_known_key(self, mocker):
        mock_save = mocker.patch("spidal.config.save_config_file")
        mocker.patch("spidal.config.load_config_file", return_value={})

        result = runner.invoke(app, ["config", "set", "download-dir", "/tmp/music"])
        assert result.exit_code == 0
        assert "download-dir" in result.output
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["download-dir"] == "/tmp/music"

    def test_rejects_unknown_key(self):
        result = runner.invoke(app, ["config", "set", "nonexistent-key", "value"])
        assert result.exit_code != 0
        assert "Unknown key" in result.output

    def test_accepts_underscore_key(self, mocker):
        mock_save = mocker.patch("spidal.config.save_config_file")
        mocker.patch("spidal.config.load_config_file", return_value={})

        result = runner.invoke(app, ["config", "set", "download_dir", "/tmp/music"])
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert saved["download-dir"] == "/tmp/music"

    def test_merges_with_existing_config(self, mocker):
        existing = {"spotify-token": "old-token", "download-dir": "/old"}
        mock_save = mocker.patch("spidal.config.save_config_file")
        mocker.patch("spidal.config.load_config_file", return_value=existing)

        runner.invoke(app, ["config", "set", "download-dir", "/new"])
        saved = mock_save.call_args[0][0]
        assert saved["spotify-token"] == "old-token"
        assert saved["download-dir"] == "/new"


class TestConfigGet:
    def test_gets_known_key(self):
        result = runner.invoke(app, ["config", "get", "download-dir"])
        assert result.exit_code == 0
        assert "download-dir" in result.output

    def test_shows_source_default(self):
        result = runner.invoke(app, ["config", "get", "download-dir"])
        assert "default" in result.output

    def test_shows_source_file(self, mocker):
        mocker.patch(
            "spidal.config.load_config_file",
            return_value={"download-dir": "/from-file"},
        )
        result = runner.invoke(app, ["config", "get", "download-dir"])
        assert result.exit_code == 0
        assert "file" in result.output

    def test_rejects_unknown_key(self):
        result = runner.invoke(app, ["config", "get", "nonexistent-key"])
        assert result.exit_code != 0
        assert "Unknown key" in result.output

    def test_shows_not_set_for_none_values(self):
        result = runner.invoke(app, ["config", "get", "spotify-token"])
        assert result.exit_code == 0
        assert "(not set)" in result.output or "spotify-token" in result.output


class TestConfigList:
    def test_lists_all_keys(self):
        result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "download-dir" in result.output
        assert "audio-quality" in result.output
        assert "spotify-token" in result.output

    def test_shows_config_file_path(self):
        result = runner.invoke(app, ["config", "list"])
        assert "Config file:" in result.output

    def test_shows_source_for_each_key(self):
        result = runner.invoke(app, ["config", "list"])
        assert "[default]" in result.output or "[file]" in result.output
