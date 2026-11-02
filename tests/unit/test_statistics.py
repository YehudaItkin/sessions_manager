from sessions_manager.models import UsageFact, UsageMembership, UsageResult, UsageSnapshot
from sessions_manager.statistics import summarize
from tests.support.cleanup_case import case


def test_unique_fact_union_shared_bucket_and_hidden_default(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        catalog = service.catalog
        sessions = catalog.sessions()
        catalog.hide([sessions[0].session_uid], True)
        fact = UsageFact(
            "shared",
            "claude",
            root.namespace_id,
            "api",
            input_tokens=0,
            output_tokens=5,
            total_tokens=5,
        )
        for session in sessions:
            catalog.replace_usage(
                session, UsageResult([fact], [], [UsageMembership(session.session_uid, "shared")])
            )
        result = summarize(catalog, catalog.sessions(), group_by="project")
        assert result["metrics"]["total_tokens"]["value"] == 5
        assert result["metrics"]["input_tokens"]["value"] == 0
        assert result["scope"] == "selected_session_lifetimes"
        assert result["accounting_mode"] == "unique_fact_union"
        assert result["metrics"]["total_tokens"]["selected_sessions"] == 2


def test_unknown_snapshot_scopes_excluded_from_multi_session_sum(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        catalog = service.catalog
        sessions = catalog.sessions()
        for session in sessions:
            catalog.replace_usage(
                session,
                UsageResult(
                    [],
                    [
                        UsageSnapshot(
                            session.session_uid,
                            "lifetime-" + session.session_uid,
                            "one",
                            {"total_tokens": 10},
                        )
                    ],
                    [],
                ),
            )
        result = summarize(catalog, sessions)
        metric = result["metrics"]["total_tokens"]
        assert metric["value"] is None
        assert metric["known_sessions"] == 2
        assert len(metric["excluded_snapshot_scopes"]) == 2
        single = summarize(catalog, [sessions[0]])
        assert single["metrics"]["total_tokens"]["value"] == 10


def test_cross_group_fact_is_only_in_shared_bucket(tmp_path):
    with case(tmp_path) as (service, root, uid, path, neighbor):
        catalog = service.catalog
        sessions = catalog.sessions()
        sessions[0].cwd = "/project/alpha"
        sessions[1].cwd = "/project/beta"
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
            catalog.replace_usage(
                session, UsageResult([fact], [], [UsageMembership(session.session_uid, "shared")])
            )
        result = summarize(catalog, sessions, group_by="project")
        groups = {group["key"]: group for group in result["groups"]}
        assert groups["shared_usage"]["metrics"]["total_tokens"]["value"] == 15
        assert groups["/project/alpha"]["metrics"]["total_tokens"]["value"] == 0
        assert groups["/project/beta"]["metrics"]["total_tokens"]["value"] == 0
        assert result["metrics"]["total_tokens"]["value"] == 15
