import pytest

from spidal.config import Config, DEFAULTS


@pytest.mark.integration
class TestGetApisIntegration:
    def test_default_hifi_api_file_returns_apis(self):
        config = Config(hifi_api_file=DEFAULTS["hifi_api_file"])
        apis = config.get_apis()
        assert isinstance(apis, list)
        assert len(apis) > 0
        for api in apis:
            assert isinstance(api, str)
            assert api.startswith("https://")
