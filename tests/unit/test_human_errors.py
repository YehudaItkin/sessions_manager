from sessions_manager.messages import explain, resume_guide


def test_failures_explain_recovery_without_disclosing_exception_payload():
    assert "F5" in explain("source_changed")
    assert "Hide" in explain("native_cascade_unbounded")
    assert "index" in explain("shared_dependency_unverified")
    assert "record" in explain("not_recorded")
    assert "unknown-future-code" in explain("unknown-future-code")


def test_resume_guide_has_reason_and_known_help_without_inventing_resume():
    text = resume_guide(
        {
            "provider": "codex",
            "native_id": "synthetic-id",
            "original_cwd": "/old",
            "requested_cwd": "/new",
            "reason": "resume_cwd_unsupported",
            "help_argv": ["/trusted/codex", "--help"],
        }
    )
    assert "synthetic-id" in text and "/old" in text and "/new" in text
    assert "directory" in text and "/trusted/codex --help" in text
    assert "resume synthetic-id" not in text


def test_cli_human_explanation_and_json_code_are_separate(isolated):
    import json

    from typer.testing import CliRunner

    from sessions_manager.cli import app

    config, data = isolated
    args = ["--config", str(config), "--data-dir", str(data), "--invalid-option"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 2
    assert "sessions --help" in result.stdout
    result = CliRunner().invoke(app, ["--format", "json", *args])
    assert json.loads(result.stdout)["error"]["code"] == "invalid_arguments"


def test_cleanup_recovery_and_activity_reasons_are_actionable():
    assert "Close" in explain("session_active")
    assert "confirm" in explain("closed_assertion_required")
    assert "overwritten" in explain("destination_conflict")
    assert "space" in explain("insufficient_space")
    assert "Close" in explain("observed_open_handle")


def test_human_operation_errors_have_recovery_text():
    from sessions_manager.messages import human_data

    value = {"items": [{"error": "source_changed", "state": "failed_no_change"}]}
    rendered = human_data(value)
    assert "F5" in rendered["items"][0]["error"]
    assert value["items"][0]["error"] == "source_changed"


def test_invalid_filter_explanations_say_how_to_correct_input():
    assert "YYYY-MM-DD" in explain("invalid_date")
    assert "after" in explain("invalid_date_range")
    assert "sort" in explain("invalid_query")
