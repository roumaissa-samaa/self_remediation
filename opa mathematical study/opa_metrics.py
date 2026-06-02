import os
import sys
import json
import math
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()


def get_es_client():
    try:
        from elasticsearch import Elasticsearch
        url = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
        es = Elasticsearch(url)
        if es.ping():
            return es
        print("[WARN] Elasticsearch unreachable — no data available")
        return None
    except ImportError:
        print("[WARN] elasticsearch package not installed — no data available")
        return None


def fetch_docs(es) -> list[dict]:
    try:
        resp = es.search(
            index="audit_trail",
            body={
                "query":   {"match_all": {}},
                "_source": ["retry_count", "opa_approved", "opa_reason", "incident_id"],
                "size":    1000,
            }
        )
        docs = [h["_source"] for h in resp["hits"]["hits"]]
        print(f"[ES] {len(docs)} documents retrieved from audit_trail")
        return docs
    except Exception as e:
        print(f"[ES] Error: {e}")
        return []


def compute_metrics(docs: list[dict]) -> dict:
    rounds = {}
    for doc in docs:
        rc       = doc.get("retry_count", 0)
        approved = doc.get("opa_approved", False)
        rnd = (rc + 1) if approved else max(rc, 1)
        if rnd not in rounds:
            rounds[rnd] = {"total": 0, "success": 0}
        rounds[rnd]["total"] += 1
        if approved:
            rounds[rnd]["success"] += 1

    total      = len(docs)
    n_approved = sum(1 for d in docs if d.get("opa_approved"))
    n_blocked  = total - n_approved

    rev_total   = sum(v["total"]   for k, v in rounds.items() if k >= 2)
    rev_success = sum(v["success"] for k, v in rounds.items() if k >= 2)
    p_revision  = rev_success / rev_total if rev_total > 0 else None

    r1      = rounds.get(1, {"total": 0, "success": 0})
    p_first = r1["success"] / r1["total"] if r1["total"] > 0 else None

    # p_global: OPA approvals / total OPA calls (all rounds combined)
    # approved=True  → calls = retry_count + 1  (last call was a success)
    # approved=False → calls = retry_count       (all calls were refusals)
    total_calls = sum(
        (d.get("retry_count", 0) + 1) if d.get("opa_approved")
        else d.get("retry_count", 0)
        for d in docs
    )
    p_global = n_approved / total_calls if total_calls > 0 else None

    p_est = p_global if p_global is not None else (p_revision or p_first or 0.65)

    return {
        "total_incidents":    total,
        "total_approved":     n_approved,
        "total_blocked":      n_blocked,
        "approval_rate":      n_approved / total if total > 0 else 0,
        "attempts_per_round": rounds,
        "p_first":            p_first,
        "p_revision":         p_revision,
        "p_global":           p_global,
        "p_estimated":        p_est,
    }


def compute_optimal_n(p: float, c_ratio: float = 500.0) -> dict:
    # Clamp p to avoid log(0) or log(1) with insufficient data
    p = min(max(p, 0.01), 0.99)

    n_raw  = math.log(c_ratio * p) / math.log(1.0 / (1.0 - p))
    n_star = max(1, math.floor(n_raw) + 1)

    def ecost(n):
        return (1 - (1-p)**n) / p + c_ratio * (1-p)**n

    table = {
        n: {
            "P_success":     round(1 - (1-p)**n, 4),
            "P_block":       round((1-p)**n, 4),
            "expected_cost": round(ecost(n), 2),
        }
        for n in range(1, 8)
    }

    return {
        "n_star_raw":   round(n_raw, 2),
        "n_star":       n_star,
        "p":            p,
        "c_ratio":      c_ratio,
        "cost_table":   table,
    }


def print_report(m: dict, o: dict):
    S = "═" * 60
    print(f"\n{S}\n  OPA METRICS\n{S}")
    print(f"  Incidents       : {m['total_incidents']}")
    print(f"  Approved        : {m['total_approved']} ({m['approval_rate']*100:.1f}%)")
    print(f"  Blocked         : {m['total_blocked']}")
    print()
    for rnd, v in sorted(m["attempts_per_round"].items()):
        lbl  = "initial   " if rnd == 1 else f"revision {rnd-1}"
        rate = v["success"] / v["total"] * 100 if v["total"] > 0 else 0
        print(f"    Round {rnd} ({lbl}) : {v['success']}/{v['total']}  ({rate:.1f}%)")
    print()
    p1 = f"{m['p_first']*100:.1f}%"    if m["p_first"]    is not None else "N/A"
    pr = f"{m['p_revision']*100:.1f}%" if m["p_revision"] is not None else "N/A"
    pg = f"{m['p_global']*100:.1f}%"   if m["p_global"]   is not None else "N/A"
    print(f"  p (first call)  : {p1}")
    print(f"  p (revision)    : {pr}")
    print(f"  p (global)      : {pg}  ← approvals / total OPA calls")
    print(f"  p used          : {m['p_estimated']*100:.1f}%")

    print(f"\n{S}\n  OPTIMAL n*\n{S}")
    print(f"  p = {o['p']:.2f}  |  c_esc/c_iter = {o['c_ratio']:.0f}")
    print(f"  n* (raw) = {o['n_star_raw']}  →  n* = {o['n_star']}")
    print()
    print(f"  {'n':>3}  {'P(success)':>10}  {'P(blocked)':>10}  {'E[cost]':>10}")
    print(f"  {'─'*3}  {'─'*10}  {'─'*10}  {'─'*10}")
    for n, r in o["cost_table"].items():
        mk = "  ← OPTIMAL" if n == o["n_star"] else ("  ← current" if n == 2 else "")
        print(f"  {n:>3}  {r['P_success']:>10.4f}  {r['P_block']:>10.4f}  {r['expected_cost']:>10.2f}{mk}")
    print(S)


def main():
    es   = get_es_client()
    docs = fetch_docs(es) if es else []
    if not docs:
        print("[ERROR] No data available — check your Elasticsearch connection.")
        return

    metrics = compute_metrics(docs)
    optim   = compute_optimal_n(metrics["p_estimated"])
    print_report(metrics, optim)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opa_metrics_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "optimisation": optim}, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to {out}")
    print("  Next: python \"opa mathematical study/opa_diagrams.py\"")


if __name__ == "__main__":
    main()
