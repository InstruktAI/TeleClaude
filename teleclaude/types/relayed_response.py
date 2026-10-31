"""The complete response a computer gave to a request relayed to it."""

from dataclasses import dataclass, field

from teleclaude.core.models._types import JsonDict, JsonValue


@dataclass(frozen=True, kw_only=True)
class RelayedResponse:
    """The complete response a computer gave to a relayed request: status, end-to-end headers and body, as produced."""

    status_code: int
    body_b64: str
    headers: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        """Serialize as the data block of the relay command's wire response."""
        return {
            "status_code": self.status_code,
            "body_b64": self.body_b64,
            "headers": [list(pair) for pair in self.headers],
        }

    @staticmethod
    def from_wire(data: JsonValue | None) -> "RelayedResponse":
        """Rebuild from the data block of the relay command's wire response."""
        if not isinstance(data, dict):
            raise ValueError("relayed response must be a JSON object")
        status_code = data.get("status_code")
        body_b64 = data.get("body_b64")
        raw_headers = data.get("headers", [])
        if not isinstance(status_code, int) or isinstance(status_code, bool) or not isinstance(body_b64, str):
            raise ValueError("relayed response must carry a status code and a body")
        if not isinstance(raw_headers, list):
            raise ValueError("relayed response headers must be a list of name and value pairs")
        headers: list[list[str]] = []
        for pair in raw_headers:
            if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
                raise ValueError("relayed response headers must be a list of name and value pairs")
            headers.append([str(pair[0]), str(pair[1])])
        return RelayedResponse(status_code=status_code, body_b64=body_b64, headers=headers)
