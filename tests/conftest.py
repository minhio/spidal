import pytest


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, mocker):
    """Redirect the database to a temp directory so tests never touch the real db."""
    mocker.patch("spidal.persistence.DB_PATH", tmp_path / "db.json")
