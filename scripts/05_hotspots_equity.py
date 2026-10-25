"""Spatial clustering of poor access (Getis-Ord Gi*) and equity summaries.

Outputs:
  gdb/Access_HotSpots                  Gi* z-scores and confidence bins for DRIVE_MIN
  outputs/equity_income_quintile.csv   population-weighted drive time by income quintile
  figures/access_by_group.png          share of each population group by drive-time band
  figures/drive_time_by_income.png     mean drive time by household income quintile
"""
import arcpy
import matplotlib.pyplot as plt
import pandas as pd

from config import BREAKS, FIGURES, GDB, OUTPUTS

arcpy.env.overwriteOutput = True

# Sequential blue ramp (light -> dark = shorter -> longer drive); grey = no road access
BAND_COLORS = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b", "#898781"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e1e0d9"
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 10, "axes.edgecolor": "#c3c2b7",
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})


def hot_spots():
    lyr = arcpy.management.MakeFeatureLayer(str(GDB / "DA_Polygons"), "reached",
                                            "DRIVE_MIN IS NOT NULL")[0]
    # DAs range from city blocks to thousands of km2, so a fixed distance band would
    # give urban DAs hundreds of neighbours and northern DAs none; K nearest is balanced.
    arcpy.stats.HotSpots(lyr, "DRIVE_MIN", str(GDB / "Access_HotSpots"),
                         "K_NEAREST_NEIGHBORS", "EUCLIDEAN_DISTANCE", "ROW",
                         Apply_False_Discovery_Rate__FDR__Correction="APPLY_FDR",
                         number_of_neighbors=8)
    bins = pd.Series([r[0] for r in arcpy.da.SearchCursor(str(GDB / "Access_HotSpots"),
                                                          ["Gi_Bin"])]).value_counts().sort_index()
    print("  DAs per Gi_Bin (3 = hot spot of long drive times at 99% confidence):")
    print("  " + bins.to_string().replace("\n", "\n  "))


def access_by_group(df):
    order = [f"<= {b} min" for b in BREAKS] + [f"> {BREAKS[-1]} min", "No road access"]
    labels = [f"≤{b} min" for b in BREAKS] + [f">{BREAKS[-1]} min", "No road"]
    groups = {"All residents": "pop_2021", "Age 65+": "pop_65plus",
              "Indigenous identity": "indig_pop"}
    share = pd.DataFrame({g: df.groupby("ACCESS_BAND")[c].sum() for g, c in groups.items()})
    share = (100 * share / share.sum()).reindex(order).fillna(0)

    fig, ax = plt.subplots(figsize=(9, 3.2))
    names = list(groups)[::-1]
    left = pd.Series(0.0, index=names)
    for band, label, color in zip(order, labels, BAND_COLORS):
        vals = share.loc[band, names]
        ax.barh(names, vals, left=left, color=color, edgecolor="#fcfcfb", linewidth=2,
                height=0.6, label=label)
        for i, (n, v) in enumerate(vals.items()):
            if v >= 4:
                ax.text(left[n] + v / 2, i, f"{v:.0f}%", va="center", ha="center", fontsize=9,
                        color=INK if band in order[:2] else "#ffffff")
        left += vals
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of group (%)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=6, loc="lower center", bbox_to_anchor=(0.45, 1.0), frameon=False,
              fontsize=9, title="Drive time to nearest hospital", title_fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES / "access_by_group.png", dpi=200)
    plt.close(fig)


def by_income(df):
    d = df.dropna(subset=["DRIVE_MIN", "med_hh_income"]).copy()
    d = d[d["pop_2021"] > 0]
    d["quintile"] = pd.qcut(d["med_hh_income"], 5, labels=["Q1\nlowest", "Q2", "Q3", "Q4",
                                                            "Q5\nhighest"])
    d["pop_x_min"] = d["DRIVE_MIN"] * d["pop_2021"]
    d["pop_over_30"] = d["pop_2021"].where(d["DRIVE_MIN"] > 30, 0)
    g = d.groupby("quintile", observed=True).agg(
        das=("DAUID", "size"), population=("pop_2021", "sum"),
        median_income=("med_hh_income", "median"), pop_x_min=("pop_x_min", "sum"),
        pop_over_30=("pop_over_30", "sum"))
    g["mean_drive_min"] = g.pop("pop_x_min") / g["population"]
    g["pct_over_30"] = 100 * g.pop("pop_over_30") / g["population"]
    g.to_csv(OUTPUTS / "equity_income_quintile.csv")
    print(g.round(1).to_string())

    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    bars = ax.bar(g.index.astype(str), g["pct_over_30"], color="#2a78d6", width=0.6)
    ax.bar_label(bars, fmt="%.0f%%", padding=3, color=INK, fontsize=9)
    ax.set_ylabel("Residents >30 min from a hospital (%)")
    ax.set_xlabel("Dissemination areas grouped by median household income (2020)")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    fig.savefig(FIGURES / "drive_time_by_income.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    FIGURES.mkdir(exist_ok=True)
    df = pd.read_csv(OUTPUTS / "da_access.csv", dtype={"DAUID": str})
    print("Hot spot analysis")
    hot_spots()
    print("Equity charts")
    access_by_group(df)
    by_income(df)
