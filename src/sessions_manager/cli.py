"""Console entry point; help and version never open the catalog."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer._click.exceptions import ClickException
from typer.core import TyperGroup

from . import __version__
from .messages import explain, human_data, resume_guide
from .models import Failure, envelope


class SafeGroup(TyperGroup):
    def main(self, args=None, **kwargs):
        import sys

        arguments = list(sys.argv[1:] if args is None else args)
        standalone = kwargs.pop("standalone_mode", True)
        json_mode = "--format=json" in arguments or any(
            value == "--format" and arguments[index + 1 : index + 2] == ["json"]
            for index, value in enumerate(arguments)
        )
        try:
            result = super().main(args=arguments, standalone_mode=False, **kwargs)
        except ClickException:
            emit(
                Options(format="json" if json_mode else "table"),
                Failure("invalid_arguments", 2).envelope(),
            )
            result = 2
        except (KeyboardInterrupt, typer.Abort):
            emit(
                Options(format="json" if json_mode else "table"),
                Failure("cancelled", 130).envelope(),
            )
            result = 130
        except Exception:
            emit(
                Options(format="json" if json_mode else "table"),
                Failure("internal_error", 1).envelope(),
            )
            result = 1
        if standalone and isinstance(result, int):
            raise SystemExit(result)
        return result

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except Failure as failure:
            emit(ctx.obj or Options(), failure.envelope())
            raise typer.Exit(failure.exit_code) from None
        except OSError:
            emit(ctx.obj or Options(), Failure("io_error", 6).envelope())
            raise typer.Exit(6) from None
        except sqlite3.Error:
            emit(ctx.obj or Options(), Failure("catalog_io_error", 6).envelope())
            raise typer.Exit(6) from None


app = typer.Typer(
    cls=SafeGroup,
    no_args_is_help=False,
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)


@dataclass
class Options:
    config: Path | None = None
    data_dir: Path | None = None
    format: str = "table"


def version(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def callback(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option()] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    format: Annotated[str, typer.Option()] = "table",
    version_flag: Annotated[
        bool, typer.Option("--version", callback=version, is_eager=True)
    ] = False,
):
    if format not in ("table", "json"):
        raise typer.BadParameter("format must be table or json")
    ctx.obj = Options(config, data_dir, format)
    if ctx.invoked_subcommand is None:
        import sys

        if format == "table" and sys.stdin.isatty() and sys.stdout.isatty():
            from .ui.app import SessionsApp

            cfg, catalog = runtime(ctx.obj, initial_scan=False)
            try:
                SessionsApp(cfg, catalog).run()
            finally:
                catalog.close()
        else:
            list_command(ctx)


def emit(options, result):
    if options.format == "json":
        typer.echo(json.dumps(result, ensure_ascii=False))
    else:
        from rich.table import Table
        from rich.text import Text

        from .models import Session, display_time, safe_text, short_handles

        console = Console(markup=False, highlight=False)
        data = result["data"]
        if result["kind"] in ("list", "refresh"):
            rows = [Session.from_dict(row) for row in data["items"]]
            handles = data.get("handles") or short_handles(rows)
            table = Table(
                "Manager ID",
                "Native ID",
                "Source",
                "Title / preview",
                "Project",
                "Last activity",
                "Activity",
                "Actions",
                expand=True,
                box=None,
                padding=(0, 1),
                collapse_padding=True,
            )
            table.columns[0].min_width = 10
            table.columns[0].no_wrap = True
            table.columns[1].min_width = 10
            table.columns[1].no_wrap = True
            for row in rows:
                match = data.get("matches", {}).get(row.session_uid)
                preview = (
                    f"{match['field']}: {match['text']}" if match else row.title or row.preview
                )
                table.add_row(
                    handles[row.session_uid],
                    Text(safe_text(row.native_id), overflow="ellipsis", no_wrap=True),
                    row.provider,
                    Text(safe_text(preview), overflow="ellipsis", no_wrap=True),
                    Text(safe_text(row.cwd), overflow="ellipsis", no_wrap=True),
                    display_time(row.last_activity_at),
                    row.activity,
                    " ".join(
                        name
                        for name in ("history", "resume", "cleanup", "usage")
                        if row.capabilities[name].state == "supported"
                    )
                    or "none available",
                )
            console.print(table)
            for row in rows:
                match = data.get("matches", {}).get(row.session_uid)
                if match:
                    console.print(
                        f"Match {handles[row.session_uid]} ({match['field']}): {match['text']}"
                    )
            console.print(
                f"{len(rows)} shown / {data.get('total', len(rows))} sessions; offset {data.get('offset', 0)}"
            )
            if not rows:
                console.print("No sessions match. Use sources list, refresh, or clear filters.")
            for root in result.get("sources", []):
                console.print(
                    f"{root['provider']}: {root['state']}; as of {display_time(root.get('as_of'))}"
                )
        elif result["kind"] == "show":
            row = data["session"]
            console.print(
                f"Manager ID: {row['display_id']}\nNative ID: {safe_text(row['native_id'])}\nSource: {row['provider']}\nProject: {safe_text(row['cwd'])}\nCreated: {display_time(row['created_at'])}\nLast activity: {display_time(row['last_activity_at'])}\nHistory: {row['history_state']}"
            )
            console.print(
                f"History location: {safe_text(row['locator'])}\nModel: {safe_text(row['model'])}"
            )
            console.print("Capabilities:")
            for name, capability in row["capabilities"].items():
                console.print(
                    f"{name}: {capability['state']}"
                    + (" — " + explain(capability["reason"]) if capability.get("reason") else "")
                )
            for name, metric in data["usage"]["metrics"].items():
                console.print(
                    f"{name}: {metric['value'] if metric['value'] is not None else 'unknown'} ({explain(metric['reason']) if metric.get('reason') else 'complete'})"
                )
            print_context_metrics(console, data["usage"])
            for event in data["events"]:
                console.print(f"\n{event['role']}: {safe_text(event.get('text') or '[no text]')}")
            if data["next_offset"] is not None:
                console.print(f"Next: show ID --offset {data['next_offset']}")
        elif result["kind"] == "stats":
            console.print("Selected session lifetimes; period filters select by last activity")
            console.print(
                "Selection: " + safe_text(json.dumps(data["selection"], ensure_ascii=False))
            )
            activity = data["activity_range"]
            console.print(
                f"Known activity range: {display_time(activity['started_at'])} — "
                f"{display_time(activity['last_activity_at'])}; complete={activity['complete']}"
            )
            table = Table("Metric", "Known value", "Known / selected", "Status")
            for name, metric in data["metrics"].items():
                table.add_row(
                    name,
                    str(metric["value"]) if metric["value"] is not None else "unknown",
                    f"{metric['known_sessions']} / {metric['selected_sessions']}",
                    explain(metric["reason"]) if metric.get("reason") else "complete",
                )
            console.print(table)
            print_context_metrics(console, data)
            for group in data["groups"]:
                console.print(
                    safe_text(group["key"]) + ": " + str(group["metrics"]["total_tokens"]["value"])
                )
        elif result["kind"] == "error" and data.get("manual_resume_guide"):
            console.print(resume_guide(data["manual_resume_guide"]))
        elif result["kind"] != "error" or data:
            console.print(safe_text(json.dumps(human_data(data), ensure_ascii=False, indent=2)))
        if result.get("error"):
            console.print(explain(result["error"]["code"]))


def print_context_metrics(console, data):
    from .models import safe_text

    for context in data.get("context_metrics", []):
        used = context["used_tokens"]
        maximum = context["max_tokens"]
        console.print(
            safe_text(
                f"Context occupancy (separate from lifetime): "
                f"{used if used is not None else 'unknown'} / "
                f"{maximum if maximum is not None else 'unknown'} tokens"
            )
        )


def main():
    try:
        app()
    except Failure as failure:
        import sys

        if "--format" in sys.argv and sys.argv[sys.argv.index("--format") + 1 :][:1] == ["json"]:
            typer.echo(json.dumps(failure.envelope(), ensure_ascii=False))
        else:
            typer.echo(explain(failure.code), err=True)
        raise SystemExit(failure.exit_code) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except OSError:
        typer.echo(explain("io_error"), err=True)
        raise SystemExit(6) from None


def runtime(options, *, providers=None, initial_scan=True):
    from .catalog import Catalog
    from .config import Config
    from .discovery import refresh

    cfg = Config.load(options.config, options.data_dir)
    cfg.prepare()
    catalog = Catalog(cfg.data_dir)
    from .warp import cleanup_expired

    cleanup_expired(catalog)
    known = {r["root_id"] for r in catalog.root_states()}
    wanted = {
        r.root_id for r in cfg.roots if r.enabled and (not providers or r.provider in providers)
    }
    stale = not catalog.index_valid
    if stale and providers:
        marks = ",".join("?" for _ in providers)
        stale = (
            catalog.connection.execute(
                f"SELECT 1 FROM sessions WHERE presence IN ('present','source_unavailable') AND json_extract(payload,'$.search_state')='stale' AND json_extract(payload,'$.provider') IN ({marks}) LIMIT 1",
                providers,
            ).fetchone()
            is not None
        )
    if initial_scan and (not wanted <= known or stale):
        refresh(cfg, catalog, providers=providers)
    return cfg, catalog


def result_envelope(catalog, kind, data, *, selected=None, providers=None, root_ids=None):
    states = catalog.root_states()
    if providers:
        states = [r for r in states if json.loads(r["payload"])["provider"] in providers]
    if root_ids is not None:
        states = [r for r in states if r["root_id"] in root_ids]
    sources = [
        {
            "root_id": r["root_id"],
            "provider": json.loads(r["payload"])["provider"],
            "state": r["state"],
            "as_of": r["as_of"],
        }
        for r in states
    ]
    sessions = catalog.sessions() if selected is None else selected
    return envelope(
        kind,
        data,
        sources=sources,
        completeness={
            "enumeration": "partial"
            if any(r["state"] != "complete" for r in states)
            else "complete",
            "history": "complete"
            if all(s.history_state == "complete" for s in sessions)
            else "partial",
            "search": "complete"
            if all(s.search_state == "complete" for s in sessions)
            else "partial",
            "usage": "complete"
            if all(s.usage_state == "complete" for s in sessions)
            else "partial",
            "as_of": min((r["as_of"] for r in states), default=None)
            if all(r["as_of"] is not None for r in states)
            else None,
            "cached": True,
        },
    )


def finish(options, result, *, require_search=False):
    emit(options, result)
    completeness = result.get("completeness", {})
    if completeness.get("enumeration") == "partial" or (
        require_search and completeness.get("search") != "complete"
    ):
        raise typer.Exit(3)


def overview_data(catalog, rows, query=None):
    from .models import short_handles

    handles = short_handles(catalog.sessions(include_missing=True))
    return {
        "items": rows,
        "handles": {s.session_uid: handles[s.session_uid] for s in rows},
        "matches": {s.session_uid: catalog.match_context(s.session_uid, query) for s in rows}
        if query
        else {},
    }


@app.command("list")
def list_command(
    ctx: typer.Context,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    project: str | None = None,
    scope: str = "visible",
    sort: Annotated[
        str,
        typer.Option(
            help="Sort by updated, created, source, project, title, id, manager-id, model, activity or size; recent/oldest are aliases."
        ),
    ] = "recent",
    order: Annotated[
        str | None,
        typer.Option(help="asc or desc; defaults to descending dates/size and ascending text."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="Model name contains, ignoring case.")] = None,
    activity: Annotated[
        str | None, typer.Option(help="active, inactive or unknown; omission includes all states.")
    ] = None,
    query: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: Annotated[int, typer.Option(min=1)] = 50,
    offset: Annotated[int, typer.Option(min=0)] = 0,
):
    from .search import SORT_OPTIONS, QuerySpec

    if scope not in ("visible", "hidden", "all") or sort not in {
        "recent",
        "oldest",
        *(key for _, key in SORT_OPTIONS),
    }:
        raise typer.BadParameter("invalid scope or sort")
    spec = QuerySpec(
        providers=source,
        project=project,
        since=since,
        until=until,
        scope=scope,
        sort=sort,
        order=order,
        model=model,
        activity=activity,
    )
    spec.filter([])
    cfg, catalog = runtime(ctx.obj, providers=source)
    try:
        candidates = spec.filter(catalog.sessions(), catalog)
        rows = QuerySpec(scope="all", sort=sort, order=order, query=query).filter(
            candidates, catalog
        )
        result = result_envelope(
            catalog,
            "list",
            overview_data(catalog, rows[offset : offset + limit], query)
            | {
                "total": len(rows),
                "limit": limit,
                "offset": offset,
            },
            selected=candidates,
            providers=source,
        )
        finish(ctx.obj, result, require_search=query is not None)
    finally:
        catalog.close()


@app.command("refresh")
def refresh_command(
    ctx: typer.Context,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    project: str | None = None,
    since: str | None = None,
    until: str | None = None,
    model: Annotated[str | None, typer.Option(help="Model name contains, ignoring case.")] = None,
    activity: Annotated[
        str | None, typer.Option(help="active, inactive or unknown; omission includes all states.")
    ] = None,
    scope: str = "visible",
    sort: Annotated[
        str,
        typer.Option(
            help="Sort by updated, created, source, project, title, id, manager-id, model, activity or size; recent/oldest are aliases."
        ),
    ] = "recent",
    order: Annotated[
        str | None,
        typer.Option(help="asc or desc; defaults to descending dates/size and ascending text."),
    ] = None,
    query: str | None = None,
):
    from .discovery import refresh
    from .search import QuerySpec

    spec = QuerySpec(
        providers=source,
        project=project,
        since=since,
        until=until,
        model=model,
        activity=activity,
        scope=scope,
        sort=sort,
        order=order,
    )
    spec.filter([])
    cfg, catalog = runtime(ctx.obj, initial_scan=False)
    try:
        scans = refresh(cfg, catalog, providers=source)
        candidates = spec.filter(catalog.sessions(), catalog)
        rows = QuerySpec(scope="all", sort=sort, order=order, query=query).filter(
            candidates, catalog
        )
        finish(
            ctx.obj,
            result_envelope(
                catalog,
                "refresh",
                overview_data(catalog, rows, query)
                | {
                    "scans": scans,
                    "complete": all(r["state"] == "complete" for r in scans),
                    "state": "finished",
                },
                selected=candidates,
                providers=source,
            ),
            require_search=query is not None,
        )
    finally:
        catalog.close()


sources_app = typer.Typer()
app.add_typer(sources_app, name="sources")


@sources_app.command("list")
def sources_list(ctx: typer.Context):
    from .models import public

    cfg, catalog = runtime(ctx.obj)
    try:
        finish(ctx.obj, result_envelope(catalog, "sources", {"items": public(cfg.roots)}))
    finally:
        catalog.close()


@sources_app.command("add")
def sources_add(
    ctx: typer.Context,
    provider: str,
    path: Annotated[Path, typer.Option()],
    namespace: str = "default",
):
    from .config import Config

    cfg = Config.load(ctx.obj.config, ctx.obj.data_dir)
    cfg.prepare()
    cfg.add_source(provider, path, namespace)
    emit(
        ctx.obj,
        envelope(
            "sources",
            {"items": [{"provider": provider, "namespace": namespace, "state": "view_only"}]},
        ),
    )


@app.command("doctor")
def doctor(ctx: typer.Context):
    cfg, catalog = runtime(ctx.obj)
    try:
        emit(
            ctx.obj,
            result_envelope(
                catalog,
                "doctor",
                {
                    "items": [
                        {"code": "private_catalog_ok", "state": "complete"},
                        *[
                            {
                                "provider": r.provider,
                                "root_id": r.root_id,
                                "executable_available": bool(
                                    r.executable_path and r.executable_path.is_file()
                                ),
                                "resume_context": r.resume_context,
                            }
                            for r in cfg.roots
                        ],
                    ]
                },
            ),
        )
    finally:
        catalog.close()


@app.command("show")
def show_command(
    ctx: typer.Context,
    id: str,
    offset: Annotated[int, typer.Option(min=0)] = 0,
    limit: Annotated[int, typer.Option(min=1)] = 100,
):
    cfg, catalog = runtime(ctx.obj)
    try:
        session = catalog.get(id)
        from .statistics import summarize

        events = catalog.events(session.session_uid, offset, limit + 1)
        result = result_envelope(
            catalog,
            "show",
            {
                "session": session,
                "events": events[:limit],
                "next_offset": offset + limit if len(events) > limit else None,
                "usage": summarize(catalog, [session]),
            },
            selected=[session],
            root_ids={session.root_id},
        )
        finish(ctx.obj, result)
    finally:
        catalog.close()


@app.command("resume")
def resume_command(
    ctx: typer.Context,
    id: str,
    terminal: str = "current",
    cwd: Path | None = None,
    dry_run: bool = False,
):
    from .launch import build_request, launch_current
    from .warp import deliver

    if terminal not in ("current", "warp"):
        raise Failure("invalid_terminal", 2)
    cfg, catalog = runtime(ctx.obj)
    try:
        session = catalog.get(id)
        root = next((r for r in cfg.roots if r.root_id == session.root_id and r.enabled), None)
        if root is None:
            raise Failure("resume_binding_unverified", 4)
        request = build_request(root, session, cfg.data_dir, cwd=cwd, target=terminal)
        if dry_run:
            emit(ctx.obj, envelope("launch_plan", request))
            return
        result = (
            deliver(catalog, request)
            if terminal == "warp"
            else launch_current(request, output_to_stderr=ctx.obj.format == "json")
        )
        emit(ctx.obj, envelope("launch_result", result))
        if result.get("child_exit_code", 0):
            raise typer.Exit(130 if result["child_exit_code"] == 130 else 8)
    finally:
        catalog.close()


@app.command("_launch", hidden=True)
def launch_helper(ctx: typer.Context, ticket: str):
    from .catalog import Catalog
    from .config import DEFAULT_DATA, ensure_private
    from .warp import execute_ticket

    data = Path(ctx.obj.data_dir or DEFAULT_DATA).absolute()
    if not data.is_dir() or not (data / "catalog.sqlite3").is_file():
        raise Failure("launch_registry_unavailable", 8)
    ensure_private(data)
    with Catalog(data) as catalog:
        result = execute_ticket(catalog, ticket)
        emit(ctx.obj, envelope("launch_result", result))
        if result.get("child_exit_code", 0):
            raise typer.Exit(130 if result["child_exit_code"] == 130 else 8)


def cleanup_service(options):
    from .cleanup import CleanupService

    cfg, catalog = runtime(options)
    return CleanupService(cfg, catalog)


def hide_action(ctx, ids, hidden):
    cfg, catalog = runtime(ctx.obj)
    try:
        sessions = [catalog.get(value) for value in ids]
        catalog.hide([s.session_uid for s in sessions], hidden)
        emit(
            ctx.obj,
            result_envelope(
                catalog,
                "visibility",
                {"items": [{"session_id": s.display_id, "hidden": hidden} for s in sessions]},
            ),
        )
    finally:
        catalog.close()


@app.command("hide")
def hide_command(ctx: typer.Context, ids: Annotated[list[str], typer.Argument()]):
    hide_action(ctx, ids, True)


@app.command("unhide")
def unhide_command(ctx: typer.Context, ids: Annotated[list[str], typer.Argument()]):
    hide_action(ctx, ids, False)


def cleanup_action(ctx, action, ids, confirm, assert_closed=False):
    service = cleanup_service(ctx.obj)
    try:
        if not confirm:
            emit(ctx.obj, envelope("operation_plan", service.preview(action, ids)))
            return
        result = service.commit(action, ids, confirm, assert_closed=assert_closed)
        emit(ctx.obj, envelope("operation_result", result))
        failed = [
            item
            for item in result["items"]
            if item["state"] not in ("trashed", "restored", "purged")
        ]
        if failed:
            if len(failed) < len(result["items"]):
                raise typer.Exit(3)
            raise typer.Exit(
                6
                if any(
                    item["state"] == "recovery_required"
                    or item["error"] in ("io_error", "insufficient_space")
                    for item in failed
                )
                else 5
            )
    finally:
        service.catalog.close()


@app.command("delete")
def delete_command(
    ctx: typer.Context,
    ids: Annotated[list[str], typer.Argument()],
    confirm: str | None = None,
    assert_closed: bool = False,
):
    cleanup_action(ctx, "trash", ids, confirm, assert_closed)


trash_app = typer.Typer()
app.add_typer(trash_app, name="trash")


@trash_app.command("list")
def trash_list(ctx: typer.Context):
    service = cleanup_service(ctx.obj)
    try:
        emit(ctx.obj, envelope("trash_list", {"items": service.trash_list()}))
    finally:
        service.catalog.close()


@trash_app.command("restore")
def trash_restore(
    ctx: typer.Context, ids: Annotated[list[str], typer.Argument()], confirm: str | None = None
):
    cleanup_action(ctx, "restore", ids, confirm)


@trash_app.command("purge")
def trash_purge(
    ctx: typer.Context, ids: Annotated[list[str], typer.Argument()], confirm: str | None = None
):
    cleanup_action(ctx, "purge", ids, confirm)


@trash_app.command("retry")
def trash_retry(ctx: typer.Context, operation_id: str, assert_closed: bool = False):
    service = cleanup_service(ctx.obj)
    try:
        result = service.retry(operation_id, assert_closed=assert_closed)
        emit(ctx.obj, envelope("operation_result", result))
        if any(i["state"] not in ("trashed", "restored", "purged") for i in result["items"]):
            raise typer.Exit(3)
    finally:
        service.catalog.close()


@app.command("stats")
def stats_command(
    ctx: typer.Context,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    project: str | None = None,
    since: str | None = None,
    until: str | None = None,
    query: str | None = None,
    scope: str = "all",
    session: str | None = None,
    group_by: str | None = None,
    model: Annotated[str | None, typer.Option(help="Model name contains, ignoring case.")] = None,
    activity: Annotated[
        str | None, typer.Option(help="active, inactive or unknown; omission includes all states.")
    ] = None,
):
    from .search import QuerySpec
    from .statistics import summarize

    spec = QuerySpec(
        providers=source,
        project=project,
        since=since,
        until=until,
        scope=scope,
        model=model,
        activity=activity,
    )
    spec.filter([])
    cfg, catalog = runtime(ctx.obj, providers=source)
    try:
        candidates = spec.filter(catalog.sessions(), catalog)
        if session:
            selected = catalog.get(session)
            candidates = [s for s in candidates if s.session_uid == selected.session_uid]
        rows = QuerySpec(scope="all", query=query).filter(candidates, catalog)
        finish(
            ctx.obj,
            result_envelope(
                catalog,
                "stats",
                summarize(
                    catalog,
                    rows,
                    group_by=group_by,
                    selection=spec.selection([selected.display_id] if session else None)
                    | {"query": query},
                ),
                selected=candidates,
                providers=source,
            ),
            require_search=query is not None,
        )
    finally:
        catalog.close()
