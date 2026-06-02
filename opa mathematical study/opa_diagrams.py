import os
import sys
import math
import json
import numpy as np
import matplotlib

sys.stdout.reconfigure(encoding="utf-8")
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

OUT_DIR     = os.path.dirname(os.path.abspath(__file__))
MAX_RETRIES = 2      # current OPA_MAX_RETRIES 
C_RATIO     = 500.0  # c_esc / c_iter


# ════════════════════════════════════════════════════════════════
#  Load p from opa_metrics_result.json (if available)
# ════════════════════════════════════════════════════════════════

def load_p() -> float:
    path = os.path.join(OUT_DIR, "opa_metrics_result.json")
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        p = data.get("metrics", {}).get("p_estimated", 0.65)
        print(f"[INFO] p loaded from opa_metrics_result.json: {p:.2f}")
        return p
    print("[INFO] opa_metrics_result.json not found — using default p = 0.65")
    return 0.65


# ════════════════════════════════════════════════════════════════
#  1. MARKOV CHAIN DIAGRAM
# ════════════════════════════════════════════════════════════════

def draw_markov(p: float, n: int = MAX_RETRIES):
    fig, ax = plt.subplots(figsize=(13, 6))
    ax.set_xlim(-0.8, (n + 1) * 2.4)
    ax.set_ylim(-2.8, 2.8)
    ax.axis("off")

    C_BLUE  = "#2E86AB"
    C_GREEN = "#27AE60"
    C_RED   = "#E74C3C"
    C_GRAY  = "#7F8C8D"
    R = 0.45

    # ── node positions ───────────────────────────────────────────
    s_pos = [(i * 2.4, 0.0) for i in range(n)]
    a_pos = (n * 2.4 + 0.5,  1.7)
    b_pos = (n * 2.4 + 0.5, -1.7)

    def node(cx, cy, label, color, sub=""):
        ax.add_patch(plt.Circle((cx, cy), R, color=color, zorder=3, ec="white", lw=2))
        ax.text(cx, cy, label, ha="center", va="center",
                fontsize=13, fontweight="bold", color="white", zorder=4)
        if sub:
            ax.text(cx, cy - R - 0.25, sub, ha="center", va="top",
                    fontsize=7.5, color="#555", style="italic")

    def arc_arrow(x1, y1, x2, y2, color, label="", rad=0.0, lbl_off=(0, 0.22)):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8,
                                    connectionstyle=f"arc3,rad={rad}"), zorder=2)
        if label:
            mx, my = (x1+x2)/2 + lbl_off[0], (y1+y2)/2 + lbl_off[1]
            ax.text(mx, my, label, ha="center", va="center", fontsize=9,
                    color=color, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=color, lw=0.8, alpha=0.92),
                    zorder=5)

    # ── transient nodes S0…S(n-1) ────────────────────────────────
    for i, (cx, cy) in enumerate(s_pos):
        lbl = "Initial\nattempt" if i == 0 else f"Revision {i}"
        node(cx, cy, f"S{i}", C_BLUE, sub=lbl)

    # ── absorbing nodes ──────────────────────────────────────────
    node(*a_pos, "A", C_GREEN)
    ax.text(a_pos[0], a_pos[1] + R + 0.2, "Approved\n(execution)",
            ha="center", va="bottom", fontsize=8, color=C_GREEN, fontweight="bold")
    node(*b_pos, "B", C_RED)
    ax.text(b_pos[0], b_pos[1] - R - 0.2, "Blocked\n(human escalation)",
            ha="center", va="top", fontsize=8, color=C_RED, fontweight="bold")

    # ── arrows Si → S(i+1) ───────────────────────────────────────
    for i in range(n - 1):
        x1, y1 = s_pos[i][0] + R, s_pos[i][1]
        x2, y2 = s_pos[i+1][0] - R, s_pos[i+1][1]
        arc_arrow(x1, y1, x2, y2, C_GRAY,
                label=f"1−p\n({1-p:.2f})", rad=-0.28,
                lbl_off=(0, -0.55))

    # ── arrows Si → A ────────────────────────────────────────────
    for i, (cx, cy) in enumerate(s_pos):
        dx = a_pos[0] - cx
        dy = a_pos[1] - cy
        dist = math.hypot(dx, dy)
        ex = cx + (dx / dist) * R
        ey = cy + (dy / dist) * R
        ax2 = a_pos[0] - (dx / dist) * R * 0.9
        ay2 = a_pos[1] - (dy / dist) * R * 0.9
        rad = -0.08 * i
        arc_arrow(ex, ey, ax2, ay2, C_GREEN,
                  label=f"p ({p:.2f})", rad=rad,
                  lbl_off=(cx + dx * 0.38 - ex, cy + dy * 0.38 - ey + 0.18))

    # ── arrow S(n-1) → B ─────────────────────────────────────────
    lx, ly = s_pos[-1]
    dx = b_pos[0] - lx
    dy = b_pos[1] - ly
    dist = math.hypot(dx, dy)
    arc_arrow(lx + (dx/dist)*R, ly + (dy/dist)*R,
              b_pos[0] - (dx/dist)*R*0.9, b_pos[1] - (dy/dist)*R*0.9,
              C_RED, label=f"1−p\n({1-p:.2f})", rad=0.25,
              lbl_off=(dx * 0.38, dy * 0.38 - 0.18))

    # ── absorbing self-loops A→A and B→B ─────────────────────────
    for (cx, cy), col in [(a_pos, C_GREEN), (b_pos, C_RED)]:
        loop = mpatches.Arc((cx + 0.6, cy), 0.58, 0.58, angle=0,
                             theta1=20, theta2=340, color=col, lw=1.5, zorder=2)
        ax.add_patch(loop)
        ax.text(cx + 1.08, cy, "1", ha="center", va="center",
                fontsize=8, color=col, fontweight="bold")

    # ── transition matrix (generated dynamically from n) ─────────
    q = 1 - p
    header_states = "  ".join([f"S{i}" for i in range(n)] + ["A", "B"])
    matrix_lines = [f"Transition matrix T  ({', '.join([f'S{i}' for i in range(n)] + ['A', 'B'])})"]
    matrix_lines.append(f"     {header_states}")
    for i in range(n):
        row = ["0"] * (n + 2)
        if i < n - 1:
            row[i + 1] = f"{q:.2f}"   # → S(i+1)
        else:
            row[n + 1] = f"{q:.2f}"   # last state → B
        row[n] = f"{p:.2f}"           # → A
        matrix_lines.append(f"S{i} [ {' '.join(row)} ]")
    matrix_lines.append(f"A  [ {' '.join(['0']*n + ['1', '0'])} ]")
    matrix_lines.append(f"B  [ {' '.join(['0']*n + ['0', '1'])} ]")
    matrix_txt = "\n".join(matrix_lines)

    ax.text(0.01, 0.03, matrix_txt, transform=ax.transAxes,
            fontsize=8, color="#333", va="bottom", family="monospace",
            bbox=dict(boxstyle="round,pad=0.4", fc="#F8F9FA", ec="#CCC", lw=0.8))

    p_a = 1 - (1-p)**n
    p_b = (1-p)**n
    ax.set_title(
        f"Markov Chain — OPA Validation Cycle\n"
        f"n = {n} max attempts  |  p = {p:.2f}  |  "
        f"P(A) = {p_a:.3f}  |  P(B) = {p_b:.3f}",
        fontsize=12, fontweight="bold", color="#2C3E50", pad=16)

    out = os.path.join(OUT_DIR, "markov_opa.png")
    plt.tight_layout()
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"[OK] markov_opa.png  →  {out}")


# ════════════════════════════════════════════════════════════════
#  2. SENSITIVITY ANALYSIS
# ════════════════════════════════════════════════════════════════

def draw_sensitivity(p_ref: float):
    p_vals  = sorted(set([0.4, 0.5, 0.6, 0.7, 0.8, 0.9, round(p_ref, 2)]))
    n_range = list(range(1, 9))
    colors  = plt.cm.plasma(np.linspace(0.1, 0.85, len(p_vals)))

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    # ── left panel: P(success) ───────────────────────────────────
    ax1 = axes[0]
    for pv, col in zip(p_vals, colors):
        y = [1 - (1-pv)**n for n in n_range]
        lw = 2.8 if abs(pv - p_ref) < 0.005 else 1.6
        ls = "-" if abs(pv - p_ref) < 0.005 else "--"
        ax1.plot(n_range, y, color=col, lw=lw, ls=ls,
                marker="o", ms=5, label=f"p = {pv}")

    ax1.axvline(MAX_RETRIES, color="red", lw=2, ls=":", label=f"current n={MAX_RETRIES}")
    ax1.axhline(0.95, color="gray", lw=1, ls="--", alpha=0.5, label="95% threshold")
    ax1.set_xlabel("Max attempts (n)", fontsize=11)
    ax1.set_ylabel("P(automated success)", fontsize=11)
    ax1.set_title("P(success) = 1 − (1−p)ⁿ", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=8.5, loc="lower right")
    ax1.set_ylim(0, 1.05)
    ax1.grid(True, alpha=0.3)
    ax1.set_xticks(n_range)

    # ── right panel: expected cost ───────────────────────────────
    ax2 = axes[1]

    def ecost(p, n):
        return (1 - (1-p)**n) / p + C_RATIO * (1-p)**n

    for pv, col in zip(p_vals, colors):
        y  = [ecost(pv, n) for n in n_range]
        lw = 2.8 if abs(pv - p_ref) < 0.005 else 1.6
        ls = "-" if abs(pv - p_ref) < 0.005 else "--"
        ax2.plot(n_range, y, color=col, lw=lw, ls=ls,
                 marker="s", ms=5, label=f"p = {pv}")

    ax2.axvline(MAX_RETRIES, color="red", lw=2, ls=":", label=f"current n={MAX_RETRIES}")

    # n* correct: floor(ln(rp) / ln(1/(1-p))) + 1
    nstar_raw = math.log(C_RATIO * p_ref) / math.log(1.0 / (1.0 - p_ref))
    nstar     = max(1, math.floor(nstar_raw) + 1)
    ax2.axvline(nstar, color="green", lw=2, ls="-.",
                label=f"n* = {nstar} (p={p_ref:.2f})")

    ax2.set_xlabel("Max attempts (n)", fontsize=11)
    ax2.set_ylabel(f"E[cost] / c_iter   (c_esc/c_iter = {C_RATIO:.0f})", fontsize=11)
    ax2.set_title("Expected total cost", fontsize=12, fontweight="bold")
    ax2.legend(fontsize=8.5, loc="upper right")
    ax2.grid(True, alpha=0.3)
    ax2.set_xticks(n_range)

    plt.suptitle("Sensitivity Analysis — Optimal OPA_MAX_RETRIES",
                 fontsize=13, fontweight="bold", y=1.01)
    plt.tight_layout()
    out = os.path.join(OUT_DIR, "opa_sensitivity.png")
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"[OK] opa_sensitivity.png  →  {out}")


# ════════════════════════════════════════════════════════════════
#  3. EXPECTED COST CURVE + MARGINAL GAIN
# ════════════════════════════════════════════════════════════════

def draw_cost_curve(p: float):
    n_range = list(range(1, 9))

    def ecost(n):
        return (1 - (1-p)**n) / p + C_RATIO * (1-p)**n

    # Correct formula: ΔG(n) = (1-p)^n * (rp - 1)
    def marginal_gain(n):
        return (C_RATIO * p - 1) * (1-p)**n

    costs  = [ecost(n)         for n in n_range]
    gains  = [marginal_gain(n) for n in n_range]

    # n* correct: floor(ln(rp) / ln(1/(1-p))) + 1
    nstar_raw = math.log(C_RATIO * p) / math.log(1.0 / (1.0 - p))
    nstar     = max(1, math.floor(nstar_raw) + 1)

    fig, ax1 = plt.subplots(figsize=(10, 5.5))

    # expected cost
    ax1.plot(n_range, costs, color="#2E86AB", lw=2.5, marker="o", ms=7,
             label="E[cost(n)] / c_iter")
    ax1.set_xlabel("Max attempts (n)", fontsize=12)
    ax1.set_ylabel("E[cost] / c_iter", fontsize=12, color="#2E86AB")
    ax1.tick_params(axis="y", labelcolor="#2E86AB")

    # marginal gain (right axis)
    ax2 = ax1.twinx()
    ax2.plot(n_range, gains, color="#E74C3C", lw=2, ls="--", marker="s", ms=6,
             label="Marginal gain ΔG(n) = (rp−1)·(1−p)ⁿ")
    ax2.axhline(1.0, color="#E74C3C", lw=1.2, ls=":", alpha=0.6,
                label="Threshold = c_iter (= 1)")
    ax2.set_ylabel("Marginal gain / c_iter", fontsize=12, color="#E74C3C")
    ax2.tick_params(axis="y", labelcolor="#E74C3C")

    # reference lines
    ax1.axvline(MAX_RETRIES, color="orange", lw=2, ls=":",
                label=f"current n={MAX_RETRIES}")
    ax1.axvline(nstar, color="green", lw=2, ls="-.",
                label=f"n* = {nstar}")

    # n* annotation
    ax1.annotate(
        f"n* = {nstar}\nΔG(n*) < 1",
        xy=(nstar, ecost(nstar)),
        xytext=(nstar + 0.8, ecost(nstar) + 15),
        fontsize=9, color="green",
        arrowprops=dict(arrowstyle="->", color="green", lw=1.2),
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="green", lw=0.8)
    )

    # combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper right", fontsize=9)

    ax1.set_title(
        f"Expected cost and marginal gain vs n   (p = {p:.2f}, c_esc/c_iter = {C_RATIO:.0f})\n"
        f"Optimal n* = {nstar}  |  current = {MAX_RETRIES}",
        fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.set_xticks(n_range)

    plt.tight_layout()
    out = os.path.join(OUT_DIR, "opa_cost.png")
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"[OK] opa_cost.png  →  {out}")


# ════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    p = load_p()

    print("\nGenerating diagrams...")
    draw_markov(p=p, n=MAX_RETRIES)
    draw_sensitivity(p_ref=p)
    draw_cost_curve(p=p)

    print("\n[DONE] 3 diagrams generated in 'opa mathematical study/':")
    print("  → markov_opa.png      (Markov chain)")
    print("  → opa_sensitivity.png (sensitivity analysis)")
    print("  → opa_cost.png        (expected cost + marginal gain)")
