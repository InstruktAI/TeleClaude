"""Read an (ok, error) outcome from a command handler's typed result."""


def command_result_outcome(result: object) -> tuple[bool | None, str | None]:
    """Read an ``(ok, error)`` outcome from a command handler's typed result.

    ``(None, None)`` means the result carries no ok/error discriminator — a
    normal return (``None``, a plain dict, a handoff's ``None``) is success by
    virtue of not having raised. Covers the tuple shape (``restart_agent``)
    and the TypedDict shape (present for forward compatibility; no current
    handler returns it) without inventing a third result convention.
    """
    if isinstance(result, dict) and "ok" in result:
        raw_error = result.get("error")
        return result.get("ok"), (str(raw_error) if raw_error else None)
    if isinstance(result, tuple | list) and len(result) >= 1 and isinstance(result[0], bool):
        raw_error = result[1] if len(result) > 1 else None
        return result[0], (str(raw_error) if raw_error else None)
    return None, None
