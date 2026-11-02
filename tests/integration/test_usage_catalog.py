from sessions_manager.models import UsageFact, UsageMembership, UsageResult, UsageSnapshot
from tests.support.cleanup_case import case


def test_shared_facts_and_snapshot_replacement(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        catalog = service.catalog
        sessions = catalog.sessions()
        fact = UsageFact(
            "shared",
            "claude",
            root.namespace_id,
            "api",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )
        for session in sessions:
            result = UsageResult([fact], [], [UsageMembership(session.session_uid, "shared")])
            catalog.replace_usage(session, result)
        facts, members, snapshots = catalog.usage([s.session_uid for s in sessions])
        assert len(facts) == 1 and len(members["shared"]) == 2
        session = sessions[0]
        for value in (10, 20):
            catalog.replace_usage(
                session,
                UsageResult(
                    [],
                    [
                        UsageSnapshot(
                            session.session_uid, "lifetime", "one", {"total_tokens": value}
                        )
                    ],
                    [],
                ),
            )
        facts, members, snapshots = catalog.usage([session.session_uid])
        assert len(snapshots) == 1 and snapshots[0].values["total_tokens"] == 20
