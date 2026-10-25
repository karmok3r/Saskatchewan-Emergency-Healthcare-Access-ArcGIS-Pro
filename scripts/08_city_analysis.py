"""City-level emergency access for Saskatchewan's eight largest cities.

For each city:
  * drive time from every dissemination area (DA) to its nearest emergency department,
    summarised in finer 5/10/15-minute bands
  * ED catchments (which DAs each ED is nearest to) and the population each one serves
  * within-city equity: Spearman correlation between DA median income and drive time
  * closure scenarios: remove one ED at a time, re-solve, and measure the extra minutes
    and where displaced residents would go

Outputs:
  gdb/Cities, gdb/City_Catchments; DA_Polygons gains a CITY field
  outputs/city_summary.csv, city_ed_load.csv, city_closure_scenarios.csv
  figures/city_access_bands.png, figures/city_closure_impact.png
"""
import itertools

import arcpy
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import spearmanr

from config import (CITIES, CITY_BREAKS, FIGURES, GDB, ND, OUTPUTS, RAW, SR_WKID,
                    TRAVEL_MODE)

arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Network")

HOSP = str(GDB / "Hospitals")
DA_PTS = str(GDB / "DA_Points")
DA_POLY = str(GDB / "DA_Polygons")
CITY_FC = str(GDB / "Cities")
OD_IN = arcpy.nax.OriginDestinationCostMatrixInputDataType
OD_OUT = arcpy.nax.OriginDestinationCostMatrixOutputDataType
_LAYER_ID = itertools.count()

BLUES = ["#cde2fb", "#86b6ef", "#3987e5", "#0d366b"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e1e0d9"
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 10, "axes.edgecolor": "#c3c2b7",
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})


def city_band(minutes):
    for b in CITY_BREAKS:
        if minutes <= b:
            return f"<= {b} min"
    return f"> {CITY_BREAKS[-1]} min"


def load_cities():
    tmp = arcpy.conversion.JSONToFeatures(str(RAW / "sk_cities_2021.geojson"),
                                          f"{arcpy.env.scratchGDB}/cities_wgs84", "POLYGON")
    arcpy.management.Project(tmp, CITY_FC, arcpy.SpatialReference(SR_WKID))
    arcpy.management.AddField(CITY_FC, "CITY", "TEXT", field_length=40)
    names = {uid: name for name, uid in CITIES.items()}
    with arcpy.da.UpdateCursor(CITY_FC, ["CSDUID", "CITY"]) as cur:
        for uid, _ in cur:
            cur.updateRow([uid, names[uid]])


def tag(fc, key):
    """Return {key value: city} for features of fc that fall inside a city."""
    out = arcpy.analysis.SpatialJoin(fc, CITY_FC, "memory/tagged", "JOIN_ONE_TO_ONE",
                                     "KEEP_COMMON", match_option="INTERSECT")
    return {k: c for k, c in arcpy.da.SearchCursor(out, [key, "CITY"])}


def tag_da_polygons(da_city):
    if "CITY" not in [f.name for f in arcpy.ListFields(DA_POLY)]:
        arcpy.management.AddField(DA_POLY, "CITY", "TEXT", field_length=40)
    with arcpy.da.UpdateCursor(DA_POLY, ["DAUID", "CITY"]) as cur:
        for dauid, _ in cur:
            cur.updateRow([dauid, da_city.get(dauid)])


def solve_nearest(origin_ids, exclude=None):
    """Nearest-ED drive time for the given DAUIDs, optionally with one ED removed."""
    od = arcpy.nax.OriginDestinationCostMatrix(str(ND))
    od.travelMode = TRAVEL_MODE
    od.timeUnits = arcpy.nax.TimeUnits.Minutes
    od.defaultDestinationCount = 1
    od.lineShapeType = arcpy.nax.LineShapeType.NoLine

    ids = ",".join(f"'{d}'" for d in origin_ids)
    where = None if exclude is None else "facility_name <> '{}'".format(exclude.replace("'", "''"))
    # Unique layer names: reusing a name would silently keep the previous query
    orig = arcpy.management.MakeFeatureLayer(DA_PTS, f"orig{next(_LAYER_ID)}",
                                             f"DAUID IN ({ids})")[0]
    dest = arcpy.management.MakeFeatureLayer(HOSP, f"dest{next(_LAYER_ID)}", where)[0]
    fm = od.fieldMappings(OD_IN.Origins)
    fm["Name"].mappedFieldName = "DAUID"
    od.load(OD_IN.Origins, orig, fm)
    fm = od.fieldMappings(OD_IN.Destinations)
    fm["Name"].mappedFieldName = "facility_name"
    od.load(OD_IN.Destinations, dest, fm)

    result = od.solve()
    if not result.solveSucceeded:
        raise RuntimeError(result.solverMessages(arcpy.nax.MessageSeverity.All))
    return {o: (d, t) for o, d, t in
            result.searchCursor(OD_OUT.Lines, ["OriginName", "DestinationName", "Total_Time"])}


def wmean(values, weights):
    w = weights.fillna(0)
    return (values * w).sum() / w.sum() if w.sum() else float("nan")


def summarise(df, city_eds):
    rows = []
    for city, d in df.groupby("CITY"):
        pop = d["pop_2021"]
        rho, p = spearmanr(d["med_hh_income"], d["DRIVE_MIN"], nan_policy="omit")
        rows.append({
            "city": city, "population": pop.sum(), "das": len(d),
            "emergency_departments": len(city_eds.get(city, [])),
            "mean_drive_min": round(wmean(d["DRIVE_MIN"], pop), 1),
            "max_drive_min": round(d["DRIVE_MIN"].max(), 1),
            **{f"pct_{band}": round(100 * pop[d["CITY_BAND"] == band].sum() / pop.sum(), 1)
               for band in [f"<= {b} min" for b in CITY_BREAKS] + [f"> {CITY_BREAKS[-1]} min"]},
            "mean_drive_65plus": round(wmean(d["DRIVE_MIN"], d["pop_65plus"]), 1),
            "mean_drive_indigenous": round(wmean(d["DRIVE_MIN"], d["indig_pop"]), 1),
            "spearman_income_vs_drive": round(rho, 2), "spearman_p": round(p, 4),
        })
    out = pd.DataFrame(rows).sort_values("population", ascending=False)
    out.to_csv(OUTPUTS / "city_summary.csv", index=False)
    print(out.to_string(index=False))
    return out


def ed_load(df):
    load = (df.groupby(["CITY", "NEAR_HOSP"])
              .agg(population=("pop_2021", "sum"), pop_65plus=("pop_65plus", "sum"),
                   indig_pop=("indig_pop", "sum"), das=("DAUID", "size"),
                   mean_drive_min=("DRIVE_MIN", "mean"))
              .reset_index())
    load["share_of_city_pct"] = (100 * load["population"]
                                 / load.groupby("CITY")["population"].transform("sum")).round(1)
    load.to_csv(OUTPUTS / "city_ed_load.csv", index=False)
    print(load.round(1).to_string(index=False))


def closures(df, city_eds):
    rows = []
    for city, eds in city_eds.items():
        d = df[df["CITY"] == city].set_index("DAUID")
        for ed in eds:
            after = solve_nearest(d.index.tolist(), exclude=ed)
            new_min = pd.Series({k: v[1] for k, v in after.items()})
            new_dest = pd.Series({k: v[0] for k, v in after.items()})
            hit = d["NEAR_HOSP"] == ed
            pop = d["pop_2021"]
            displaced = pop[hit].sum()
            added = new_min[hit[hit].index] - d.loc[hit, "DRIVE_MIN"]
            redirect = (pop[hit].groupby(new_dest[hit[hit].index]).sum()
                        .sort_values(ascending=False))
            rows.append({
                "city": city, "ed_closed": ed, "residents_displaced": displaced,
                "displaced_pct_of_city": round(100 * displaced / pop.sum(), 1),
                "mean_added_min_displaced": round(wmean(added, pop[hit]), 1),
                "city_mean_before": round(wmean(d["DRIVE_MIN"], pop), 1),
                "city_mean_after": round(wmean(new_min[d.index], pop), 1),
                "pop_over_10min_before": pop[d["DRIVE_MIN"] > 10].sum(),
                "pop_over_10min_after": pop[new_min[d.index] > 10].sum(),
                "redirected_to": "; ".join(f"{k} ({100 * v / displaced:.0f}%)"
                                           for k, v in redirect.items()) if displaced else "",
            })
            print(f"  {city}: close {ed} -> {displaced:,.0f} displaced, "
                  f"+{rows[-1]['mean_added_min_displaced']} min")
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUTS / "city_closure_scenarios.csv", index=False)
    return out


def catchments():
    lyr = arcpy.management.MakeFeatureLayer(DA_POLY, "city_das", "CITY IS NOT NULL")[0]
    arcpy.management.Dissolve(lyr, str(GDB / "City_Catchments"), ["CITY", "NEAR_HOSP"])


def chart_bands(summary):
    bands = [f"<= {b} min" for b in CITY_BREAKS] + [f"> {CITY_BREAKS[-1]} min"]
    labels = ([f"≤{CITY_BREAKS[0]} min"]
              + [f"{a}–{b} min" for a, b in zip(CITY_BREAKS, CITY_BREAKS[1:])]
              + [f">{CITY_BREAKS[-1]} min"])
    s = summary.set_index("city").iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    left = pd.Series(0.0, index=s.index)
    for band, label, color in zip(bands, labels, BLUES):
        vals = s[f"pct_{band}"]
        ax.barh(s.index, vals, left=left, color=color, edgecolor="#fcfcfb", linewidth=2,
                height=0.62, label=label)
        for i, (c, v) in enumerate(vals.items()):
            if v >= 6:
                ax.text(left[c] + v / 2, i, f"{v:.0f}%", va="center", ha="center", fontsize=8.5,
                        color=INK if band == bands[0] or band == bands[1] else "#ffffff")
        left += vals
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of city residents (%)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.42, 1.0), frameon=False, fontsize=9,
              title="Drive time to nearest emergency department", title_fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES / "city_access_bands.png", dpi=200)
    plt.close(fig)


def chart_closures(scen):
    s = scen.sort_values("mean_added_min_displaced")
    labels = [f"{r.city}: {r.ed_closed}" for r in s.itertuples()]
    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.barh(labels, s["mean_added_min_displaced"], color="#2a78d6", height=0.6)
    for bar, (_, r) in zip(bars, s.iterrows()):
        ax.text(bar.get_width() + 0.6, bar.get_y() + bar.get_height() / 2,
                f"+{r.mean_added_min_displaced:.0f} min · {r.residents_displaced:,.0f} residents",
                va="center", fontsize=8.5, color=INK)
    ax.set_xlabel("Average extra drive time for residents whose nearest ED closes (min)")
    ax.set_xlim(0, s["mean_added_min_displaced"].max() * 1.45)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", length=0, labelsize=8.5)
    fig.tight_layout()
    fig.savefig(FIGURES / "city_closure_impact.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    print("City boundaries")
    load_cities()
    da_city = tag(DA_PTS, "DAUID")
    tag_da_polygons(da_city)
    city_eds = {}
    for name, city in tag(HOSP, "facility_name").items():
        city_eds.setdefault(city, []).append(name)
    print(f"  {len(da_city)} DAs and {sum(map(len, city_eds.values()))} EDs inside the 8 cities")

    df = pd.read_csv(OUTPUTS / "da_access.csv", dtype={"DAUID": str})
    df["CITY"] = df["DAUID"].map(da_city)
    df = df.dropna(subset=["CITY", "DRIVE_MIN"])
    df["CITY_BAND"] = df["DRIVE_MIN"].apply(city_band)

    print("City summary")
    summary = summarise(df, city_eds)
    print("ED catchment load")
    ed_load(df)
    print("Closure scenarios")
    scen = closures(df, city_eds)
    catchments()
    FIGURES.mkdir(exist_ok=True)
    chart_bands(summary)
    chart_closures(scen)
