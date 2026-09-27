"""Static charts for the report (matplotlib, print-friendly)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e0", "#ffffff"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
BLUE, ORANGE = SERIES[0], SERIES[1]
TARGET = 75.0

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.titlelocation": "left", "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
})


def _clean(ax, grid_axis="x"):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def _target(ax, horizontal=True):
    if horizontal:
        ax.axvline(TARGET, color=INK2, linestyle=(0, (4, 3)), linewidth=1, zorder=1)
    else:
        ax.axhline(TARGET, color=INK2, linestyle=(0, (4, 3)), linewidth=1)


def hbar(ax, labels, values, color=BLUE, fmt="{:.0f}%", xmax=100):
    y = range(len(labels))
    ax.barh(y, values, color=color, height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.set_yticks(list(y), labels)
    ax.set_xlim(0, xmax)
    for i, v in enumerate(values):
        ax.text(v + xmax * 0.015, i, fmt.format(v), va="center", color=INK, fontsize=8.5, zorder=5,
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=0.6))
    _clean(ax)


def make_all(seg: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    paths = {}

    # 1. where the time goes: met vs breached
    sb = seg["stage_breakdown_breached"].set_index("segment").loc[["met SLA", "breached SLA"]]
    stages = ["triage", "first_response_wait", "rerouting", "work", "waiting_on_student", "reopen_cycle"]
    names = ["Triage wait", "Wait for 1st response", "Re-routing (misrouted)", "Work by right team",
             "Waiting on student (paused)", "Reopen cycle"]
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    left = [0.0, 0.0]
    for st, nm, c in zip(stages, names, SERIES):
        vals = sb[st].tolist()
        ax.barh([1, 0], vals, left=left, color=c, height=0.55, label=nm, edgecolor=SURFACE, linewidth=2)
        for i, (l, v) in enumerate(zip(left, vals)):
            if v >= 6:
                ax.text(l + v / 2, [1, 0][i], f"{v:.0f}h", ha="center", va="center", color="white", fontsize=8,
                        fontweight="bold")
        left = [l + v for l, v in zip(left, vals)]
    for i, tot in enumerate(left):
        ax.text(tot + 1, [1, 0][i], f"{tot:.0f}h total", va="center", color=INK, fontsize=8.5)
    ax.set_yticks([1, 0], ["Met SLA", "Breached SLA"])
    ax.set_xlabel("Hours from ticket creation to final resolution")
    ax.set_xlim(0, max(left) * 1.18)
    ax.set_title("Where the time goes (average hours per ticket)")
    ax.legend(ncol=3, fontsize=7.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.32))
    _clean(ax)
    fig.tight_layout()
    paths["stages"] = out / "stage_breakdown.png"
    fig.savefig(paths["stages"], dpi=200)
    plt.close(fig)

    # 2. by department / by priority / by reassignment (small multiples)
    fig, axes = plt.subplots(1, 3, figsize=(7.6, 2.5), gridspec_kw={"wspace": 0.9})
    d = seg["by_department"].sort_values("sla_pct")
    hbar(axes[0], d.segment.str.replace(" & ", " &\n"), d.sla_pct)
    axes[0].set_title("By department", fontsize=9)
    _target(axes[0])
    p = seg["by_priority"].set_index("segment").loc[["High", "Medium", "Low"]].iloc[::-1]
    hbar(axes[1], [f"{i} ({int(t)}h)" for i, t in zip(p.index, p.target_h)], p.sla_pct)
    axes[1].set_title("By priority (target)", fontsize=9)
    _target(axes[1])
    r = seg["by_reassignment"].sort_values("segment", ascending=False)
    hbar(axes[2], ["Routed right\nfirst time", "1 reassignment", "2+ reassign."][::-1], r.sla_pct, color=BLUE)
    axes[2].set_title("By reassignments", fontsize=9)
    _target(axes[2])
    fig.suptitle("SLA compliance, % of resolved tickets  (dashed line = 75% target)", x=0.01, ha="left",
                 fontsize=10.5, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.15, right=0.97, top=0.80, bottom=0.12)
    paths["segments"] = out / "sla_segments.png"
    fig.savefig(paths["segments"], dpi=200)
    plt.close(fig)

    # 3. weekly trend
    w = seg["weekly_trend"]
    fig, ax = plt.subplots(figsize=(7.2, 2.1))
    ax.plot(range(len(w)), w.sla_pct, color=BLUE, linewidth=2, marker="o", markersize=5)
    ax.set_xticks(range(len(w)), [f"wk of\n{s[5:]}" for s in w.week_start], fontsize=7.5)
    ax.set_ylim(0, 100)
    _target(ax, horizontal=False)
    ax.text(0, TARGET + 3, "target 75%", color=INK2, fontsize=8, ha="left")
    for i, (v, n) in enumerate(zip(w.sla_pct, w.tickets)):
        ax.text(i, v - 11 if i < len(w) - 1 else v + 5, f"{v:.0f}%", ha="center", color=INK, fontsize=8)
    # last week is right-censored: slow tickets from it are still open, so only fast ones are counted
    ax.plot([len(w) - 1], [w.sla_pct.iloc[-1]], marker="o", markersize=8, markerfacecolor=SURFACE,
            markeredgecolor=BLUE, markeredgewidth=2)
    ax.annotate("incomplete week:\nslow tickets still open", (len(w) - 1, w.sla_pct.iloc[-1]),
                xytext=(len(w) - 2.6, 22), fontsize=7.5, color=INK2,
                arrowprops=dict(arrowstyle="-", color=MUTED, linewidth=0.8))
    ax.set_title("Weekly SLA compliance by week created - stuck near 60%, never close to target")
    _clean(ax, "y")
    fig.tight_layout()
    paths["trend"] = out / "weekly_trend.png"
    fig.savefig(paths["trend"], dpi=200)
    plt.close(fig)
    return paths
