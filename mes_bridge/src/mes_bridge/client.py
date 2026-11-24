"""The MES API as the bridge uses it (decision 1: API only, never the database). Standard library HTTP.

The bridge logs in as its own service user (decision 16, `settings.SCHEDULER_USERNAME` in the MES) with a bearer
token; credentials come from the caller (the environment), never from a file in the repository.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from uuid import UUID

from mes_bridge.api import PlanningSettingsOut, ProblemOut, ProposalOut, ProposalStatusIn, ScheduleIn, ScheduleOut

# method, path, JSON body, headers -> (status, parsed JSON body); swapped for a fake in tests
Send = Callable[[str, str, dict | None, dict[str, str]], tuple[int, object]]


class MesError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: object):
        super().__init__(f"{method} {path}: HTTP {status}: {body}")
        self.status = status


def http(base_url: str, timeout: float = 60) -> Send:
    def send(method: str, path: str, body: dict | None, headers: dict[str, str]) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")

    return send


class MesClient:
    PREFIX = "/api/v1"

    def __init__(self, send: Send):
        self._send = send
        self._token: str | None = None
        self._login: tuple[str, str] | None = None

    def _call(self, method: str, path: str, body: dict | None = None, ok: int = 200) -> object:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        status, out = self._send(method, self.PREFIX + path, body, headers)
        if status == 401 and self._login is not None and path != "/auth/login":
            self.login(*self._login)  # the token expired (8 h): log in again once
            headers = {"Authorization": f"Bearer {self._token}"}
            status, out = self._send(method, self.PREFIX + path, body, headers)
        if status != ok:
            raise MesError(method, path, status, out)
        return out

    def login(self, username: str, password: str) -> None:
        out = self._call("POST", "/auth/login", {"username": username, "password": password})
        assert isinstance(out, dict)
        self._token, self._login = out["access_token"], (username, password)

    def problem(self) -> ProblemOut:
        return ProblemOut.model_validate(self._call("GET", "/planning/problem"))

    def settings(self) -> PlanningSettingsOut:
        return PlanningSettingsOut.model_validate(self._call("GET", "/planning/settings"))

    def publish(self, schedule: ScheduleIn) -> ScheduleOut:
        return ScheduleOut.model_validate(
            self._call("PUT", "/planning/schedule", schedule.model_dump(mode="json"), ok=201)
        )

    def schedules(self) -> list[ScheduleOut]:
        out = self._call("GET", "/planning/schedule")
        assert isinstance(out, list)
        return [ScheduleOut.model_validate(s) for s in out]

    # --- proposals (task 7.3) ---

    def proposals(self, status: str | None = None) -> list[ProposalOut]:
        """The newest first, optionally of one status."""
        out = self._call("GET", "/planning/proposals" + (f"?status={status}" if status else ""))
        assert isinstance(out, list)
        return [ProposalOut.model_validate(p) for p in out]

    def proposal(self, proposal_id: UUID) -> ProposalOut:
        return ProposalOut.model_validate(self._call("GET", f"/planning/proposals/{proposal_id}"))

    def proposal_problem(self, proposal_id: UUID) -> ProblemOut:
        """The what-if problem: the proposal's orders planned (the MES keeps nothing)."""
        return ProblemOut.model_validate(self._call("GET", f"/planning/proposals/{proposal_id}/problem"))

    def proposal_status(self, proposal_id: UUID, status: str, message: str | None = None) -> ProposalOut:
        body = ProposalStatusIn(status=status, message=message).model_dump(mode="json")
        return ProposalOut.model_validate(self._call("PUT", f"/planning/proposals/{proposal_id}/status", body))

    def publish_proposal(self, proposal_id: UUID, schedule: ScheduleIn) -> ProposalOut:
        body = schedule.model_dump(mode="json")
        return ProposalOut.model_validate(self._call("PUT", f"/planning/proposals/{proposal_id}/schedule", body))
