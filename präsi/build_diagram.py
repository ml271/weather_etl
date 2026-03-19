"""
Architecture diagram for the Weather ETL project.
Uses matplotlib with custom patches and arrows.
Output: präsi/architecture_diagram.png  (2560 x 1440 px)
"""

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import os

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
BG        = "#0d1424"
BLUE      = "#4fc3f7"
GREEN     = "#81c784"
ORANGE    = "#ffb74d"
PURPLE    = "#ce93d8"
TEAL      = "#4db6ac"
RED       = "#ef9a9a"
WHITE     = "#ffffff"
DARK_CARD = "#1a2540"
BORDER    = "#2a3a5c"

# ---------------------------------------------------------------------------
# Canvas  — 2560×1440 at 160 dpi  (coordinate space: x ∈ [0,20], y ∈ [0,12])
# ---------------------------------------------------------------------------
DPI = 160
fig, ax = plt.subplots(figsize=(2560 / DPI, 1440 / DPI), dpi=DPI)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 20)
ax.set_ylim(0, 12)
ax.axis("off")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def card(cx, cy, w, h, title, subtitle=None,
         face=DARK_CARD, edge=BLUE, tc=WHITE, sc=None,
         fs=10, sfs=8, radius=0.3):
    """Rounded card with title + optional subtitle block."""
    box = FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=1.8, edgecolor=edge, facecolor=face, zorder=3
    )
    ax.add_patch(box)
    # accent top bar
    bar = FancyBboxPatch(
        (cx - w / 2, cy + h / 2 - 0.18), w, 0.18,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        linewidth=0, facecolor=edge, zorder=4
    )
    ax.add_patch(bar)

    ty = cy + 0.18 if subtitle else cy
    ax.text(cx, ty, title, ha="center", va="center",
            fontsize=fs, fontweight="bold", color=tc, zorder=5)
    if subtitle:
        ax.text(cx, cy - 0.22, subtitle, ha="center", va="center",
                fontsize=sfs, color=sc or WHITE, alpha=0.85, zorder=5,
                linespacing=1.5)


def arrow(x1, y1, x2, y2, color=WHITE, label="",
          lw=1.5, cs="arc3,rad=0.0", lfs=7.5):
    ax.annotate(
        "", xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                        connectionstyle=cs),
        zorder=6
    )
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx, my, label, ha="center", va="center",
                fontsize=lfs, color=color, zorder=7,
                bbox=dict(boxstyle="round,pad=0.2", facecolor=BG,
                          edgecolor="none", alpha=0.9))


def dashed_box(x, y, w, h, label, color=BORDER):
    rect = plt.Rectangle((x, y), w, h,
                          linewidth=1.6, edgecolor=color, facecolor="none",
                          linestyle="--", zorder=1)
    ax.add_patch(rect)
    ax.text(x + 0.25, y + h - 0.05, label,
            ha="left", va="top", fontsize=9,
            color=color, fontstyle="italic", zorder=2)


# ===========================================================================
# Title
# ===========================================================================
ax.text(10, 11.6, "Weather ETL — System Architecture",
        ha="center", va="center", fontsize=16, fontweight="bold",
        color=WHITE, zorder=8)

# ===========================================================================
# Docker Compose bounding box
# ===========================================================================
dashed_box(0.4, 0.55, 19.2, 9.8,
           "  Docker Compose", color="#4fc3f780")

# ===========================================================================
# Components
#
#  Row A (y≈10):  Open-Meteo API  (OUTSIDE Docker)
#  Row B (y≈8.2): Airflow  (left)
#  Row C (y≈5.5): PostgreSQL (centre)  |  FastAPI (right)
#  Row D (y≈3.0): Frontend (left)      |  Nginx (right)
#  Row E (y≈1.3): Browser (centre)
# ===========================================================================

# --- Row A: Open-Meteo API (external) ---
OM_X, OM_Y = 10.0, 10.2
card(OM_X, OM_Y, 4.0, 1.0,
     "Open-Meteo API",
     subtitle="External weather data source",
     face="#12233a", edge=TEAL, tc=TEAL, sc=TEAL,
     fs=11, sfs=8.5)

# --- Row B: Apache Airflow ---
AF_X, AF_Y = 4.5, 8.0
card(AF_X, AF_Y, 5.0, 1.9,
     "Apache Airflow",
     subtitle="weather_etl  (every 2 h)\ncheck_weather_warnings  (every 1 h)",
     edge=ORANGE, tc=ORANGE, sc=WHITE,
     fs=11, sfs=8.5)

# --- Row C: PostgreSQL (centre) ---
PG_X, PG_Y = 9.5, 5.5
card(PG_X, PG_Y, 5.5, 2.2,
     "PostgreSQL 15",
     subtitle="stations  ·  weather_daily  ·  weather_hourly\nweather_alerts  ·  users  ·  warnings",
     edge=BLUE, tc=BLUE, sc=WHITE,
     fs=11, sfs=8.5)

# --- Row C: FastAPI (right) ---
FA_X, FA_Y = 16.5, 5.5
card(FA_X, FA_Y, 4.0, 1.7,
     "FastAPI",
     subtitle="REST API endpoints\nJWT authentication",
     edge=GREEN, tc=GREEN, sc=WHITE,
     fs=11, sfs=8.5)

# --- Row D: Nginx (right) ---
NG_X, NG_Y = 16.5, 2.8
card(NG_X, NG_Y, 4.0, 1.7,
     "Nginx",
     subtitle="/api  →  FastAPI\n/  →  static files",
     edge=PURPLE, tc=PURPLE, sc=WHITE,
     fs=11, sfs=8.5)

# --- Row D: Frontend static files (left) ---
FE_X, FE_Y = 4.5, 2.8
card(FE_X, FE_Y, 5.0, 1.7,
     "Frontend (Static Files)",
     subtitle="index.html  ·  dashboard.html  ·  warnings.html",
     edge=RED, tc=RED, sc=WHITE,
     fs=11, sfs=8.5)

# --- Row E: Browser (centre) ---
BR_X, BR_Y = 10.5, 1.0
card(BR_X, BR_Y, 4.0, 1.0,
     "Browser",
     subtitle="User interface",
     face="#121a2e", edge=WHITE, tc=WHITE,
     fs=11, sfs=8.5)

# ===========================================================================
# Arrows
# ===========================================================================

# Open-Meteo → Airflow  (HTTP fetch)
arrow(OM_X - 2.0, OM_Y - 0.5,
      AF_X + 1.2, AF_Y + 0.95,
      color=TEAL, label="HTTP fetch",
      cs="arc3,rad=0.18")

# Airflow → PostgreSQL  (UPSERT)
arrow(AF_X + 2.5, AF_Y,
      PG_X - 2.75, PG_Y + 0.5,
      color=ORANGE, label="UPSERT data",
      cs="arc3,rad=-0.2")

# FastAPI ↔ PostgreSQL  (read / write)
arrow(FA_X - 2.0, FA_Y,
      PG_X + 2.75, PG_Y,
      color=GREEN, label="read / write")

# Nginx → FastAPI  (proxy /api)
arrow(NG_X, NG_Y + 0.85,
      FA_X, FA_Y - 0.85,
      color=PURPLE, label="proxy /api")

# Nginx → Frontend  (serve static)
arrow(NG_X - 2.0, NG_Y,
      FE_X + 2.5, FE_Y,
      color=RED, label="serve static",
      cs="arc3,rad=0.12")

# Browser → Nginx  (HTTPS)
arrow(BR_X + 1.0, BR_Y + 0.5,
      NG_X - 0.5, NG_Y - 0.85,
      color=WHITE, label="HTTPS",
      cs="arc3,rad=-0.2")

# ===========================================================================
# Legend
# ===========================================================================
legend_items = [
    mpatches.Patch(facecolor=TEAL,   label="External API"),
    mpatches.Patch(facecolor=ORANGE, label="Airflow"),
    mpatches.Patch(facecolor=BLUE,   label="PostgreSQL"),
    mpatches.Patch(facecolor=GREEN,  label="FastAPI"),
    mpatches.Patch(facecolor=PURPLE, label="Nginx"),
    mpatches.Patch(facecolor=RED,    label="Frontend"),
    mpatches.Patch(facecolor=WHITE,  label="Browser"),
]
ax.legend(
    handles=legend_items,
    loc="lower left",
    bbox_to_anchor=(0.005, 0.002),
    frameon=True, framealpha=0.45,
    facecolor=DARK_CARD, edgecolor=BORDER,
    labelcolor=WHITE, fontsize=8,
    ncol=4, handlelength=1.3, handleheight=1.0,
    borderpad=0.7, columnspacing=1.2,
)

# ===========================================================================
# Save
# ===========================================================================
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "architecture_diagram.png")
fig.savefig(OUT, dpi=DPI, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
print(f"Saved: {OUT}")
