"""Bounded projection of verified Cursor CLI protobuf namespaces."""

from ..models import Failure, HistoryEvent, HistoryResult, identity

MAX_BLOB = 32 * 1024 * 1024


def fields(blob):
    if not isinstance(blob, bytes) or len(blob) > MAX_BLOB:
        raise Failure("cursor_wire_limit", 4)
    offset = 0

    def varint():
        nonlocal offset
        value = 0
        for index in range(10):
            if offset >= len(blob):
                raise Failure("cursor_wire_truncated", 4)
            byte = blob[offset]
            offset += 1
            if index == 9 and byte > 1:
                raise Failure("cursor_wire_varint", 4)
            value |= (byte & 127) << (index * 7)
            if byte < 128:
                return value
        raise Failure("cursor_wire_varint", 4)

    result = {}
    while offset < len(blob):
        tag = varint()
        number, kind = tag >> 3, tag & 7
        if not number:
            raise Failure("cursor_wire_tag", 4)
        if kind == 0:
            value = varint()
        elif kind in (1, 2, 5):
            length = varint() if kind == 2 else 8 if kind == 1 else 4
            if length > MAX_BLOB or offset + length > len(blob):
                raise Failure("cursor_wire_truncated", 4)
            value = blob[offset : offset + length]
            offset += length
        else:
            raise Failure("cursor_wire_type", 4)
        result.setdefault(number, []).append(value)
    return result


def graph(root_id, load, namespace):
    events = []
    visited = set()

    def node(key, depth):
        if depth > 64 or len(visited) >= 100000 or key in visited:
            raise Failure("cursor_graph_limit_or_cycle", 4)
        visited.add(key)
        value = load(key)
        if value is None:
            raise Failure("cursor_graph_missing", 4)
        return fields(value)

    def text(value):
        try:
            return value.decode("utf-8")
        except (UnicodeError, AttributeError):
            raise Failure("cursor_wire_utf8", 4) from None

    try:
        root = node(root_id, 0)
        if 8 not in root:
            raise Failure("cursor_graph_unknown", 4)
        for turn_ref in root[8]:
            turn = node(text(turn_ref), 1)
            agent = fields(turn[1][0])
            if 1 in agent:
                key = text(agent[1][0])
                user = node(key, 2)
                body = text(user.get(1, [b""])[0])
                if not body and 18 in user:
                    raw = load(text(user[18][0]))
                    if raw is None:
                        raise Failure("cursor_graph_missing", 4)
                    body = text(raw)
                events.append(
                    HistoryEvent(
                        identity(namespace, key), "user", len(events), text=body, native_id=key
                    )
                )
            for step_ref in agent.get(2, []):
                key = text(step_ref)
                step = node(key, 2)
                if 1 in step:
                    message = fields(step[1][0])
                    events.append(
                        HistoryEvent(
                            identity(namespace, key),
                            "assistant",
                            len(events),
                            text=text(message.get(1, [b""])[0]),
                            native_id=key,
                        )
                    )
                elif 2 in step:
                    events.append(
                        HistoryEvent(
                            identity(namespace, key),
                            "tool_call",
                            len(events),
                            text=None,
                            native_id=key,
                            completeness="partial",
                        )
                    )
                elif 3 in step:
                    continue
                else:
                    raise Failure("cursor_graph_unknown_step", 4)
        state = "partial" if any(e.completeness != "complete" for e in events) else "complete"
        return HistoryResult(events, state)
    except (Failure, KeyError, IndexError):
        return HistoryResult(events, "partial", "cursor_graph_incomplete")
