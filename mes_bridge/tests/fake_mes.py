"""A fake MES for the bridge's tests: the endpoints it calls, the token checked, the PUT bodies validated."""

from urllib.parse import parse_qs
from uuid import UUID, uuid4

from mes_bridge.api import ScheduleIn


class FakeMes:
    """The endpoints the bridge calls; the token is checked, the PUT bodies validated like the MES does."""

    def __init__(self, problem: dict, password: str = "pw"):
        self.problem, self.password, self.token = problem, password, "tok"
        self.published: list[ScheduleIn] = []
        self.outs: list[dict] = []  # the stored publications, as GET /planning/schedule serves them
        self.logins = 0
        self.stale_minutes = 30  # scheduler_stale_minutes of GET /planning/settings
        self.settings_status = 200
        self.problem_status = 200  # set to e.g. 500 to make the problem fail
        # proposals (task 7.3): id -> {id, status, order_ids}, oldest first; their schedules; the what-if problem
        self.proposals: dict[str, dict] = {}
        self.proposal_schedules: dict[str, ScheduleIn] = {}
        self.whatif: dict | None = None  # GET .../problem; None: the live problem

    # --- the planner's side, as the MES does it ---

    def request(self, order_ids=()) -> str:
        for p in self.proposals.values():
            if p["status"] in ("REQUESTED", "SOLVING", "READY"):
                p["status"] = "DISCARDED"
        pid = str(uuid4())
        self.proposals[pid] = {"id": pid, "status": "REQUESTED", "order_ids": [str(o) for o in order_ids]}
        return pid

    def apply(self, pid: str) -> None:
        """The proposal's schedule becomes the current BOUND one."""
        assert self.proposals[pid]["status"] == "READY"
        self.proposals[pid]["status"] = "APPLIED"
        s = self.proposal_schedules[pid]
        self.outs.append({"id": str(uuid4()), "created_at": None, **s.model_dump(mode="json")})

    def discard(self, pid: str) -> None:
        self.proposals[pid]["status"] = "DISCARDED"

    def _proposal(self, method, path, body):
        rest = path.removeprefix("/api/v1/planning/proposals")
        if method == "GET" and (rest == "" or rest.startswith("?status=")):
            status = rest.removeprefix("?status=") or None
            out = [p for p in self.proposals.values() if status is None or p["status"] == status]
            return 200, [dict(p) for p in reversed(out)]  # newest first
        rest, _, query = rest.partition("?")
        pid, _, what = rest.strip("/").partition("/")
        p = self.proposals.get(str(UUID(pid)))
        if p is None:
            return 404, {"detail": "Proposal not found"}
        if (method, what) == ("GET", ""):  # the MES sends more (the comparison): the bridge ignores it
            return 200, dict(p, message=None, created_at=None, finished_at=None, schedule=None, extra="ignored")
        if (method, what) == ("GET", "problem"):
            if p["status"] not in ("REQUESTED", "SOLVING"):
                return 409, {"detail": f"The proposal is {p['status']}"}
            return 200, self.whatif or self.problem
        if (method, what) == ("PUT", "status"):
            allowed = {"SOLVING": {"REQUESTED"}, "FAILED": {"REQUESTED", "SOLVING"}}[body["status"]]
            if p["status"] not in allowed:
                return 409, {"detail": f"The proposal is {p['status']}"}
            p["status"], p["message"] = body["status"], body.get("message")
            return 200, dict(p)
        if (method, what) == ("PUT", "schedule"):
            if p["status"] not in ("REQUESTED", "SOLVING"):
                return 409, {"detail": f"The proposal is {p['status']}"}
            self.proposal_schedules[p["id"]] = ScheduleIn.model_validate(body)
            p["status"], p["message"] = "READY", parse_qs(query).get("note", [None])[0]
            return 200, dict(p)
        return 404, {"detail": "Not Found"}

    def __call__(self, method, path, body, headers):
        if (method, path) == ("POST", "/api/v1/auth/login"):
            ok = body == {"username": "scheduler", "password": self.password}
            self.logins += ok
            return (200, {"access_token": self.token, "token_type": "bearer"}) if ok else (401, {"detail": "no"})
        if headers.get("Authorization") != f"Bearer {self.token}":
            return 401, {"detail": "Not authenticated"}
        if path.startswith("/api/v1/planning/proposals"):
            return self._proposal(method, path, body)
        if (method, path) == ("GET", "/api/v1/planning/problem"):
            return (200, self.problem) if self.problem_status == 200 else (self.problem_status, {"detail": "down"})
        if (method, path) == ("GET", "/api/v1/planning/settings"):
            if self.settings_status != 200:
                return self.settings_status, {"detail": "down"}
            return 200, {"scheduler_stale_minutes": self.stale_minutes, "break_start": "12:00", "day_start": "07:00"}
        if (method, path) == ("PUT", "/api/v1/planning/schedule"):
            s = ScheduleIn.model_validate(body)
            self.published.append(s)
            out = {"id": str(uuid4()), "created_at": None, **s.model_dump(mode="json")}
            out["steps"] = [dict(st) for st in out["steps"]]
            self.outs.append(out)
            return 201, out
        if (method, path) == ("GET", "/api/v1/planning/schedule"):
            latest = {}
            for o in self.outs:
                latest[o["variant"]] = o
            return 200, list(latest.values())
        return 404, {"detail": "Not Found"}
