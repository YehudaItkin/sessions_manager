import pytest

from sessions_manager.models import SourceRoot
from sessions_manager.sources.native_version import resolve_cleanup_version
from tests.support.cleanup_case import version_cli


@pytest.mark.parametrize(
    "provider,version", [("grok", "1.0.70"), ("cursor", "2026.10.22-27dcf5f"), ("codex", "0.166.0")]
)
def test_supported_native_versions_are_detected_without_toml(tmp_path, provider, version):
    root = SourceRoot.create(
        provider, tmp_path / "native", executable_path=version_cli(tmp_path, version, provider)
    )
    assert resolve_cleanup_version(root) == version


def test_detected_version_is_rechecked_after_executable_changes(tmp_path):
    executable = version_cli(tmp_path)
    root = SourceRoot.create("claude", tmp_path / "native", executable_path=executable)
    assert resolve_cleanup_version(root) == "2.1.299"
    version_cli(tmp_path, "2.1.300")
    assert resolve_cleanup_version(root) == "2.1.300"


def test_untrusted_executable_and_unrecognized_output_are_not_versions(tmp_path):
    executable = version_cli(tmp_path)
    executable.chmod(0o722)
    root = SourceRoot.create("claude", tmp_path / "native", executable_path=executable)
    assert resolve_cleanup_version(root) is None
    version_cli(tmp_path, "SYNTHETIC-PRIVATE-NOT-A-VERSION")
    assert resolve_cleanup_version(root) is None


def test_explicit_unsupported_version_is_not_overridden_by_probe(tmp_path):
    root = SourceRoot.create(
        "claude",
        tmp_path / "native",
        executable_path=version_cli(tmp_path),
        executable_version="future-version",
    )
    assert resolve_cleanup_version(root) == "future-version"
