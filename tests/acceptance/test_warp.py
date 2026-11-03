from sessions_manager.catalog import Catalog
from sessions_manager.warp import deliver
from tests.integration.test_launch_ticket import setup


def test_delivered_is_not_claimed_and_config_retained(tmp_path, fake_executable):
    request = setup(tmp_path, fake_executable)
    calls = []

    def opener(argv, **kwargs):
        calls.append(argv)

        class Result:
            returncode = 0

        return Result()

    with Catalog(tmp_path / "data") as catalog:
        result = deliver(catalog, request, config_dir=tmp_path / "warp", opener=opener)
        assert result["state"] == "delivered"
        assert "Current terminal" in result["message"]
        assert calls[0][0] == "/usr/bin/open"
        assert calls[0][1].startswith("warp://tab_config/sessions_manager_")
        assert list((tmp_path / "warp").glob("*.toml"))
        assert catalog.connection.execute("SELECT state FROM launches").fetchone()[0] == "requested"
