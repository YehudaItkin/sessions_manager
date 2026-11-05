import json

from typer.testing import CliRunner

from sessions_manager.cli import app
from tests.integration.test_native_archive import archive_case


def test_archive_cli_preview_confirm_list_unarchive_and_retry(tmp_path, monkeypatch):
    import sessions_manager.cli as cli
    from sessions_manager.catalog import Catalog
    from sessions_manager.native_archive import ArchiveService

    with archive_case(tmp_path, monkeypatch) as (
        service,
        root,
        uid,
        flags,
        calls,
        behavior,
        client,
    ):

        def factory(options):
            return ArchiveService(
                service.config, Catalog(service.config.data_dir), client_factory=client
            )

        monkeypatch.setattr(cli, "archive_service", factory, raising=False)
        runner = CliRunner()
        base = ["--format", "json"]
        response = runner.invoke(app, [*base, "archive", uid])
        assert response.exit_code == 0, response.output
        plan = json.loads(response.stdout)["data"]
        token = plan["confirmation_token"]
        assert len(plan["members"]) == 3 and calls == []
        response = runner.invoke(app, [*base, "archive", uid, "--confirm", token])
        assert response.exit_code != 0 and calls == []
        behavior["lost"] = True
        response = runner.invoke(
            app, [*base, "archive", uid, "--confirm", token, "--assert-closed"]
        )
        assert response.exit_code == 3
        op = json.loads(response.stdout)["data"]["operation_id"]
        response = runner.invoke(app, [*base, "archive-retry", op, "--assert-closed"])
        assert response.exit_code == 0, response.output
        response = runner.invoke(app, [*base, "archives"])
        assert len(json.loads(response.stdout)["data"]["items"]) == 3
        response = runner.invoke(app, [*base, "unarchive", uid])
        plan = json.loads(response.stdout)["data"]
        response = runner.invoke(
            app,
            [*base, "unarchive", uid, "--confirm", plan["confirmation_token"], "--assert-closed"],
        )
        assert response.exit_code == 0, response.output
        assert flags() == dict(parent=0, child=0, prior=1, neighbor=0)
