import pytest

from sessions_manager.catalog import Catalog
from sessions_manager.models import Failure
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


@pytest.mark.parametrize("unsafe", ["directory", "ancestor", "symlink"])
def test_unsafe_launcher_path_rejected_before_ticket_or_handoff(tmp_path, fake_executable, unsafe):
    request = setup(tmp_path, fake_executable)
    parent = tmp_path / "launcher-parent"
    parent.mkdir(mode=0o700)
    directory = parent / "configs"
    if unsafe == "directory":
        directory.mkdir(mode=0o777)
        directory.chmod(0o777)
    elif unsafe == "ancestor":
        parent.chmod(0o777)
    else:
        target = tmp_path / "real-configs"
        target.mkdir(mode=0o700)
        parent.rmdir()
        parent.symlink_to(target, target_is_directory=True)
    calls = []
    with Catalog(tmp_path / "data") as catalog:
        with pytest.raises(Failure, match="unsafe_warp_config_dir"):
            deliver(catalog, request, config_dir=directory, opener=lambda *a, **k: calls.append(a))
        assert not calls
        assert not list((tmp_path / "data").glob("launches/*.json"))
        assert not list(tmp_path.rglob("sessions_manager_*.toml"))
        assert not catalog.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='launches'"
        ).fetchone()
    if unsafe == "directory":
        assert directory.stat().st_mode & 0o777 == 0o777
    elif unsafe == "ancestor":
        assert not directory.exists()
        assert parent.stat().st_mode & 0o777 == 0o777
