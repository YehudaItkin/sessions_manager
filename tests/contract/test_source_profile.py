from sessions_manager.models import Capability
from sessions_manager.sources.base import SourceProfile


def test_capabilities_independent():
    profile = SourceProfile(
        "test",
        {"id"},
        {
            "metadata": Capability("supported"),
            "history": Capability("unavailable", "unknown_codec"),
        },
    )
    assert profile.accepts({"id", "extra"})
    assert not profile.accepts({"extra"})
    assert profile.capability("metadata").state == "supported"
    assert profile.capability("history").reason == "unknown_codec"
    assert profile.capability("cleanup").state == "unavailable"
