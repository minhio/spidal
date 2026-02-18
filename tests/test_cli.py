from typer.testing import CliRunner

from spidal.cli import app
from spidal.commands import ensure_token, refresh_token
from spidal.config import Config

runner = CliRunner()


class TestEnsureToken:
    def test_returns_if_token_exists(self):
        config = Config(spotify_token="existing-token")
        ensure_token(config)
        assert config.spotify_token == "existing-token"

    def test_prompts_and_persists(self, mocker):
        config = Config(spotify_token=None)

        mocker.patch("spidal.commands.webbrowser.open")
        mocker.patch("spidal.commands.input", return_value="  new-token  ")
        mock_set = mocker.patch.object(Config, "set_spotify_token")

        ensure_token(config)

        mock_set.assert_called_once_with("new-token")


class TestRefreshToken:
    def test_prompts_for_new_token(self, mocker):
        config = Config(spotify_token="expired-token")

        mocker.patch("spidal.commands.webbrowser.open")
        mocker.patch("spidal.commands.input", return_value="fresh-token")
        mock_set = mocker.patch.object(Config, "set_spotify_token")

        refresh_token(config)

        mock_set.assert_called_once_with("fresh-token")


class TestGetSubcommand:
    def test_get_without_arg_shows_help(self):
        result = runner.invoke(app, ["get"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_get_invalid_url(self):
        result = runner.invoke(app, ["get", "https://example.com/something"])
        assert result.exit_code != 0
        assert "Unsupported URL" in result.output
