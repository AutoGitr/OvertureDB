"""Versioned queue state; every mutation uses an exact remote-head lease."""

lazy from typing import Any

lazy from . import github
lazy from .changes import digest

BRANCH = "state/contributions"
TERMINAL = {"merged", "already satisfied", "cancelled", "superseded"}


class Store:
    state: dict[str, Any]

    def __init__(self) -> None:
        self.state, self.parent = github.load_state(BRANCH)
        if not self.state:
            self.state = {"version": 1, "sequence": 0, "issues": {}, "requests": []}
        if self.state.get("version") != 1:
            raise ValueError("Unsupported contribution queue version")

    def save(self) -> None:
        github.save_state(BRANCH, self.state, self.parent, "Update contribution queue")
        # Read our committed value, refusing to continue if a competing writer won.
        state, parent = github.load_state(BRANCH)
        if state != self.state:
            raise RuntimeError("Queue changed concurrently; retry on the next wake-up")
        self.parent = parent

    def enqueue(self, source: str, record: dict[str, Any]) -> dict[str, Any]:
        identity = digest({"source": source, "record": record})
        for request in self.state["requests"]:
            if request["id"] == identity:
                return request
        if source == "import":
            for request in self.state["requests"]:
                if request["source"] == source and request["status"] == "queued":
                    request["status"] = "superseded"
        self.state["sequence"] += 1
        request = {
            "version": 1,
            "id": identity,
            "sequence": self.state["sequence"],
            "source": source,
            "record": record,
            "status": "queued",
            "generation": 0,
        }
        self.state["requests"].append(request)
        self.save()
        return request

    def next(self) -> dict[str, Any] | None:
        requests = sorted(self.state["requests"], key=lambda item: item["sequence"])
        active = [r for r in requests if r["status"] == "checking"]
        if len(active) > 1:
            raise ValueError("More than one active dataset request")
        return next(iter(active), None) or next(
            (r for r in requests if r["status"] == "queued"), None
        )
