"""
emotion_graph.py — MAITRI AI Session Visualizer v2
- Saves PNG to disk (non-blocking Agg backend, never calls plt.show())
- Dual subplot: timeline scatter + pie chart
- Color-coded per emotion, dark theme
- Returns saved file path
"""
import logging
import datetime
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

EMOTION_COLORS = {
    "happy":    "#00ff87",
    "neutral":  "#00e5ff",
    "sad":      "#5b8dd9",
    "angry":    "#ff3355",
    "fear":     "#c084fc",
    "surprise": "#ffc107",
    "disgust":  "#ff8c42",
}
REPORT_DIR = Path("reports")


def plot_emotions(log: list, session_id: str = "", save: bool = True) -> str | None:
    if not log:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        logger.error("matplotlib not installed")
        return None

    all_labels = ["happy", "neutral", "surprise", "disgust", "fear", "sad", "angry"]
    label_idx  = {e: i for i, e in enumerate(all_labels)}
    y_vals     = [label_idx.get(e.lower(), 3) for e in log]
    colors_tl  = [EMOTION_COLORS.get(e.lower(), "#4a7a90") for e in log]
    c          = Counter(log)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5),
                                    gridspec_kw={"width_ratios": [2.2, 1]},
                                    facecolor="#020c14")
    fig.suptitle("MAITRI AI — Session Emotion Report"
                 + (f"  [{session_id[:8]}]" if session_id else ""),
                 color="#00e5ff", fontsize=13, fontweight="bold", y=1.01)

    ax1.set_facecolor("#071018")
    ax1.plot(range(len(y_vals)), y_vals, color="#163348", linewidth=0.8, zorder=2)
    ax1.scatter(range(len(y_vals)), y_vals, c=colors_tl, s=18, alpha=0.85, zorder=3)
    ax1.set_yticks(range(len(all_labels)))
    ax1.set_yticklabels(all_labels, fontsize=9, color="#daeaf5")
    ax1.set_xlabel("Frame Index", color="#4a7a90", fontsize=9)
    ax1.set_title("Emotion Timeline", color="#daeaf5", fontsize=10, pad=8)
    ax1.tick_params(colors="#4a7a90")
    for sp in ax1.spines.values(): sp.set_color("#0d2535")
    ax1.grid(axis="y", color="#0d2535", linewidth=0.5)
    patches = [mpatches.Patch(color=EMOTION_COLORS.get(e, "#4a7a90"), label=e.title())
               for e in all_labels if e in c]
    ax1.legend(handles=patches, loc="upper right", fontsize=7,
               facecolor="#071018", edgecolor="#0d2535", labelcolor="#daeaf5")

    pie_labels = list(c.keys())
    pie_sizes  = list(c.values())
    pie_colors = [EMOTION_COLORS.get(l.lower(), "#4a7a90") for l in pie_labels]
    ax2.set_facecolor("#071018")
    _, texts, autotexts = ax2.pie(pie_sizes, labels=pie_labels, colors=pie_colors,
                                   autopct="%1.0f%%", startangle=140,
                                   textprops={"color": "#daeaf5", "fontsize": 8},
                                   wedgeprops={"linewidth": 0.5, "edgecolor": "#020c14"})
    for at in autotexts:
        at.set_color("#020c14"); at.set_fontsize(7); at.set_fontweight("bold")
    ax2.set_title("Distribution", color="#daeaf5", fontsize=10, pad=8)
    dominant = c.most_common(1)[0]
    ax2.text(0, -1.5, f"Frames: {len(log)}\nDominant: {dominant[0].title()}\nStates: {len(c)}",
             ha="center", va="center", fontsize=7.5, color="#4a7a90",
             family="monospace", transform=ax2.transData)

    plt.tight_layout()

    if save:
        REPORT_DIR.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = REPORT_DIR / f"graph_{ts}{('_'+session_id[:8]) if session_id else ''}.png"
        fig.savefig(out, dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("Graph saved: %s", out)
        return str(out)
    else:
        plt.show()
        return None