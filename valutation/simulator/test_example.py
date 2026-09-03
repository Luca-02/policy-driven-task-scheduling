"""Reference test: the worked example of Section 3.10 of the thesis.

Reproduces the recurring example end to end and checks every intermediate
value the thesis states explicitly. This is the only correctness test the
reference implementation needs: if the pipeline agrees with the worked
example at each stage, it agrees with the model.

Run with: python3 test_example.py
"""

from __future__ import annotations

import random

from model import ConflictSet, Dataset, GeoGroup, Node
from policies import filter_nodes, resolve_geo, select, translate, Cause

MAX_LEVELS = {"S": 3, "C": 3}


def build() -> tuple[list[Node], dict[str, Dataset], dict[str, GeoGroup], ConflictSet]:
    # Table 3: property classes of the example nodes, as [S, C].
    nodes = [
        Node("n1", {"S": 3, "C": 3}, "eu-west"),
        Node("n2", {"S": 2, "C": 2}, "eu-north"),
        Node("n3", {"S": 1, "C": 1}, "eu-south"),
        Node("n4", {"S": 2, "C": 3}, "eu-east"),
        Node("n5", {"S": 3, "C": 1}, "us-west"),
    ]

    groups = {
        "EU": GeoGroup("EU", {"eu-north", "eu-south", "eu-east", "eu-west"}),
        "US": GeoGroup("US", {"us-north", "us-south", "us-east", "us-west"}),
        "OECD": GeoGroup("OECD", includes=["EU", "US"]),
        "OMEGA": GeoGroup("OMEGA", includes=["EU", "US"]),
    }

    datasets = {
        "d5": Dataset(
            name="d5",
            props={"S": 2, "C": 0},
            geo="EU",
            contexts={"Ford"},
            size=500.0,
            is_static=True,
            local_nodes={"n1", "n4"},
        ),
        "d6": Dataset(
            name="d6",
            props={"S": 0, "C": 2},
            geo="OMEGA",
            contexts=set(),
            size=1500.0,
            is_static=False,
            local_nodes={"n4"},
        ),
    }

    conflicts = ConflictSet()
    for a, b in (("Ferrari", "Ford"), ("Ferrari", "Mercedes"), ("BMW", "Mercedes")):
        conflicts.add(a, b)

    # Equation 106: initial contextual footprints.
    nodes[0].deposit({"Ford"})
    nodes[1].deposit({"Ferrari", "Finance"})

    return nodes, datasets, groups, conflicts


def check(label: str, got, expected) -> bool:
    ok = got == expected
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {label}: {got}" + ("" if ok else f"  (atteso {expected})"))
    return ok


def main() -> int:
    nodes, datasets, groups, conflicts = build()
    req = [datasets["d5"], datasets["d6"]]
    auth_i2 = {"Ford"}

    results: list[bool] = []
    print("\nEsempio applicativo\n" + "-" * 52)

    print("Gruppi geografici")
    results.append(
        check("OECD", sorted(resolve_geo("OECD", groups)),
              sorted({"eu-north", "eu-south", "eu-east", "eu-west",
                      "us-north", "us-south", "us-east", "us-west"}))
    )

    print("Traduzione")
    tr = translate(
        task_props={"S": 1, "C": 1},
        task_geo="OECD",
        datasets=req,
        groups=groups,
        max_levels=MAX_LEVELS,
        issuer_auth=auth_i2,
    )
    results.append(check("c_auth soddisfatta", tr.cause, Cause.NONE))
    results.append(check("beta*(t3)", tr.beta_star, {"S": 2, "C": 2}))
    results.append(check("geo*(t3) = EU", sorted(tr.geo_star), sorted(groups["EU"].locations)))
    results.append(check("ctx*(t3)", tr.ctx, {"Ford"}))
    results.append(check("F_cstatic(t3)", tr.static, {"n1", "n4"}))

    print("Filtraggio")
    out = filter_nodes(
        nodes=nodes,
        beta_star=tr.beta_star,
        geo_star=tr.geo_star,
        static=tr.static,
        issuer_auth=auth_i2,
        conflicts=conflicts,
        check_state=False,
    )
    results.append(check("sopravvivono a c_prop", out.funnel[Cause.PROP], 3))
    results.append(check("sopravvivono a +c_geo", out.funnel[Cause.GEO], 3))
    results.append(check("sopravvivono a +c_static", out.funnel[Cause.STATIC], 2))
    results.append(check("F_C(t3)", sorted(n.name for n in out.admissible), ["n1", "n4"]))
    results.append(check("n3 escluso da", out.causes.get("n3"), Cause.PROP))
    results.append(check("n5 escluso da", out.causes.get("n5"), Cause.PROP))
    results.append(check("n2 escluso da", out.causes.get("n2"), Cause.STATIC))

    print("Scoring")
    from policies import score_node

    s1 = score_node(nodes[0], tr.beta_star, req, MAX_LEVELS, 1.0, 1.0)
    s4 = score_node(nodes[3], tr.beta_star, req, MAX_LEVELS, 1.0, 1.0)
    results.append(check("phi_prop(n1)", s1.phi_prop, 0.0))
    results.append(check("phi_prop(n4)", s4.phi_prop, 0.5))
    results.append(check("phi_transfer(n1)", s1.phi_transfer, 0.25))
    results.append(check("phi_transfer(n4)", s4.phi_transfer, 1.0))
    results.append(check("score(n1)", s1.total, 0.25))
    results.append(check("score(n4)", s4.total, 1.5))

    chosen, ideal = select(
        out.admissible, tr.beta_star, req, MAX_LEVELS, 1.0, 1.0, random.Random(0)
    )
    results.append(check("f(t3)", chosen.node, "n4"))
    results.append(check("nodo ideale presente", ideal, False))

    print("Aggiornamento dello stato")
    target = next(n for n in nodes if n.name == chosen.node)
    target.deposit(tr.ctx)
    results.append(check("Lambda(n4)", target.lambda_ctx, {"Ford"}))

    # A conflicting issuer is now barred from n4, as the thesis notes.
    blocked = filter_nodes(
        nodes=[target],
        beta_star=tr.beta_star,
        geo_star=tr.geo_star,
        static=tr.static,
        issuer_auth={"Ferrari"},
        conflicts=conflicts,
        check_state=False,
    )
    results.append(check("issuer Ferrari su n4", blocked.causes.get("n4"), Cause.WALL))

    print("-" * 52)
    passed = sum(results)
    print(f"{passed}/{len(results)} controlli superati\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())