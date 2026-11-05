"""Bounded projection of verified Cursor CLI protobuf namespaces."""

from ..models import Failure, HistoryEvent, HistoryResult, identity

MAX_BLOB = 32 * 1024 * 1024


def context_details(blob):
    # agent.v1.ConversationStateStructure field 5 -> ConversationTokenDetails;
    # fields 1/2 are uint32 used_tokens/max_tokens in the installed descriptor.
    root = fields(blob)
    if 8 not in root:
        raise Failure("cursor_context_unknown_shape", 4)
    if 5 not in root:
        return None
    if len(root[5]) != 1:
        raise Failure("cursor_context_unknown_shape", 4)
    details = fields(root[5][0])
    values = []
    for number in (1, 2):
        if number not in details:
            values.append(None)
            continue
        if (
            len(details[number]) != 1
            or type(details[number][0]) is not int
            or not (0 <= details[number][0] <= 0xFFFFFFFF)
        ):
            raise Failure("cursor_context_unknown_shape", 4)
        values.append(details[number][0])
    return values if any(value is not None for value in values) else None


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

    def reference(value):
        # Native blob references are 32-byte hashes stored as hex SQLite keys.
        # Older textual-key projections remain readable.
        if isinstance(value, bytes) and len(value) == 32:
            binary_key = value.hex()
            if load(binary_key) is not None:
                return binary_key
            # Resolve textual legacy keys only when that exact blob exists.
            legacy_key = text(value)
            return legacy_key if load(legacy_key) is not None else binary_key
        return text(value)

    def append_event(key, role, body, *, completeness="complete"):
        events.append(
            HistoryEvent(
                identity(namespace, key),
                role,
                len(events),
                text=body,
                native_id=key,
                completeness=completeness,
            )
        )

    def agent_turn(agent):
        incomplete = False
        if 1 in agent:
            key = reference(agent[1][0])
            try:
                user = node(key, 2)
                body = text(user.get(1, [b""])[0])
                if not body and 18 in user:
                    raw = load(reference(user[18][0]))
                    if raw is None:
                        raise Failure("cursor_graph_missing", 4)
                    body = text(raw)
                append_event(key, "user", body)
            except (Failure, KeyError, IndexError):
                incomplete = True
        for step_ref in agent.get(2, []):
            try:
                key = reference(step_ref)
                step = node(key, 2)
                if 1 in step:
                    message = fields(step[1][0])
                    append_event(key, "assistant", text(message.get(1, [b""])[0]))
                elif 2 in step:
                    append_event(key, "tool_call", None, completeness="partial")
                    incomplete = True
                elif 3 not in step:
                    incomplete = True
            except (Failure, KeyError, IndexError):
                incomplete = True
        return incomplete

    try:
        root = node(root_id, 0)
        if 8 not in root or len(root[8]) > 100000:
            raise Failure("cursor_graph_unknown", 4)
        incomplete = False
        for turn_ref in root[8]:
            try:
                turn = node(reference(turn_ref), 1)
                if 1 in turn:
                    incomplete = agent_turn(fields(turn[1][0])) or incomplete
                elif 2 in turn:
                    shell = fields(turn[2][0])
                    key = reference(shell[1][0])
                    command = node(key, 2)
                    append_event(key, "tool_call", text(command.get(1, [b""])[0]))
                    if 2 in shell:
                        key = reference(shell[2][0])
                        output = node(key, 2)
                        append_event(
                            key,
                            "tool_result",
                            "\n".join(
                                text(output[number][0]) for number in (1, 2) if number in output
                            ),
                        )
                else:
                    incomplete = True
            except (Failure, KeyError, IndexError):
                incomplete = True
        return HistoryResult(
            events,
            "partial" if incomplete else "complete",
            "cursor_graph_incomplete" if incomplete else None,
        )
    except (Failure, KeyError, IndexError):
        return HistoryResult(events, "partial", "cursor_graph_incomplete")
