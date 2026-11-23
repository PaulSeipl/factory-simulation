"""A fake MES for the bridge's tests: the four endpoints it calls, the token checked, the PUT body validated."""

from uuid import uuid4

from mes_bridge.api import ScheduleIn


class FakeMes:
    """The four endpoints the bridge calls; the token is checked, the PUT body validated like the MES does."""

    def __init__(self, problem: dict, password: str = "pw"):
        self.problem, self.password, self.token = problem, password, "tok"
        self.published: list[ScheduleIn] = []
        self.logins = 0
        self.problem_status = 200  # set to e.g. 500 to make the problem fail

    def __call__(self, method, path, body, headers):
        if (method, path) == ("POST", "/api/v1/auth/login"):
            ok = body == {"username": "scheduler", "password": self.password}
            self.logins += ok
            return (200, {"access_token": self.token, "token_type": "bearer"}) if ok else (401, {"detail": "no"})
        if headers.get("Authorization") != f"Bearer {self.token}":
            return 401, {"detail": "Not authenticated"}
        if (method, path) == ("GET", "/api/v1/planning/problem"):
            return (200, self.problem) if self.problem_status == 200 else (self.problem_status, {"detail": "down"})
        if (method, path) == ("PUT", "/api/v1/planning/schedule"):
            s = ScheduleIn.model_validate(body)
            self.published.append(s)
            out = {"id": str(uuid4()), "created_at": None, **s.model_dump(mode="json")}
            out["steps"] = [dict(st) for st in out["steps"]]
            return 201, out
        return 404, {"detail": "Not Found"}
