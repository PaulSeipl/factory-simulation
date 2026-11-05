"""Toy instance for 01_basic-fjsp, solved with the CP-SAT mapping from section 5.
Illustration only (not the project code)."""
import json
from ortools.sat.python import cp_model

machines = ["M1", "M2", "M3", "M4"]
# order -> (release, {op: {machine: p}}, precedence pairs P)
orders = {
    "A": (0, {"a1": {"M1": 3, "M2": 5}, "a2": {"M2": 4, "M3": 3}, "a3": {"M4": 2}},
          [("a1", "a2"), ("a2", "a3")]),
    "B": (2, {"b1": {"M1": 2, "M3": 4}, "b2": {"M2": 3, "M3": 3},
              "b3": {"M1": 4, "M4": 3}, "b4": {"M4": 2, "M2": 3}},
          [("b1", "b2"), ("b1", "b3"), ("b2", "b4"), ("b3", "b4")]),
    "C": (4, {"c1": {"M1": 3, "M3": 2}, "c2": {"M2": 2, "M4": 4}},
          [("c1", "c2")]),
}

def solve(orders):
    H = sum(max(opts.values()) for _, ops, _ in orders.values() for opts in ops.values()) \
        + max(r for r, _, _ in orders.values())          # trivial horizon
    mdl = cp_model.CpModel()
    S, C, x, per_machine = {}, {}, {}, {m: [] for m in machines}
    for k, (r, ops, P) in orders.items():
        for o, opts in ops.items():
            S[o] = mdl.NewIntVar(r, H, f"S_{o}")          # C4: lower bound r_k(o)
            C[o] = mdl.NewIntVar(0, H, f"C_{o}")
            for m, p in opts.items():
                x[o, m] = mdl.NewBoolVar(f"x_{o}_{m}")
                # optional interval sharing the master start S_o
                iv = mdl.NewOptionalFixedSizeIntervalVar(S[o], p, x[o, m], f"a_{o}_{m}")
                per_machine[m].append(iv)
            mdl.AddExactlyOne(x[o, m] for m in opts)                      # C1
            mdl.Add(C[o] == S[o] + sum(p * x[o, m] for m, p in opts.items()))  # C2
        for o, o2 in P:
            mdl.Add(S[o2] >= C[o])                                         # C3
    for m in machines:
        mdl.AddNoOverlap(per_machine[m])                                   # C5
    cmax = mdl.NewIntVar(0, H, "Cmax")
    mdl.AddMaxEquality(cmax, list(C.values()))
    mdl.Minimize(cmax)
    sol = cp_model.CpSolver()
    sol.parameters.num_workers = 8
    st = sol.Solve(mdl)
    out = []
    for k, (r, ops, P) in orders.items():
        for o, opts in ops.items():
            m = next(m for m in opts if sol.Value(x[o, m]))
            out.append(dict(order=k, op=o, machine=m, start=sol.Value(S[o]), end=sol.Value(C[o])))
    return sol.StatusName(st), sol.Value(cmax), out

if __name__ == "__main__":
    status, cmax, sched = solve(orders)
    print(status, cmax)
    print(json.dumps(sched))
    # lower bounds for context
    # LB1: longest path with min processing times per order incl. release
