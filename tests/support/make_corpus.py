"""Generate synthetic native stores, never import or inspect production histories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import tomli_w

from sessions_manager.models import identity
from tests.support import claude_factory, codex_factory, cursor_factory, grok_factory


def generate(output, sessions=40, history_bytes=10485760, profile="mixed"):
    output = Path(output).absolute()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    factories = {
        "codex": codex_factory,
        "claude": claude_factory,
        "grok": grok_factory,
        "cursor": cursor_factory,
    }
    source_rows = []
    ids = []
    counts = dict.fromkeys(factories, 0)
    padding = " synthetic history" * max(1, history_bytes // max(1, sessions) // 18)
    for provider in factories:
        root = output / provider
        root.mkdir()
        fake = output / ("fake-" + provider)
        fake.write_text(
            f"#!{sys.executable}\nimport json,sys,os\nprint(json.dumps({{'argv':sys.argv[1:],'cwd':os.getcwd()}}))\n"
        )
        fake.chmod(0o700)
        source_rows.append(
            {
                "provider": provider,
                "path": str(root),
                "executable": str(fake),
                "resume_context": "native",
                "executable_version": "synthetic",
            }
        )
    for index in range(sessions):
        provider = list(factories)[index % 4]
        counts[provider] += 1
        native = f"synthetic-{provider}-{index:05d}"
        root = output / provider
        factories[provider].make(
            root,
            native,
            cwd=output / "projects" / str(index % 10),
            text=f"needle-{index:05d} " + padding,
            **({"message_id": native + "-assistant"} if provider == "claude" else {}),
        )
        ids.append(identity(provider + ":default", native))
    (output / "fixture.toml").write_text(
        tomli_w.dumps({"discovery_roots_mode": "replace", "sources": source_rows})
    )
    (output / "expected.json").write_text(
        json.dumps(
            {
                "seed": 1,
                "sessions": sessions,
                "session_ids": ids,
                "requested_history_bytes": history_bytes,
                "native_bytes": sum(
                    p.stat().st_size
                    for name in factories
                    for p in (output / name).rglob("*")
                    if p.is_file()
                ),
                "provider_counts": counts,
                "metrics": {
                    "messages": counts["codex"] + 2 * (sessions - counts["codex"]),
                    "known_total_tokens": 20 * counts["claude"],
                    "notes": "Grok snapshots have unknown independence; multiple selected histories do not sum them. Codex/Cursor lifetime totals are not recorded in this corpus.",
                },
            }
        )
    )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", choices=["mixed"], default="mixed")
    parser.add_argument("--sessions", type=int, default=40)
    parser.add_argument("--history-bytes", type=int, default=10485760)
    args = parser.parse_args()
    generate(args.output, args.sessions, args.history_bytes, args.profile)


if __name__ == "__main__":
    main()
