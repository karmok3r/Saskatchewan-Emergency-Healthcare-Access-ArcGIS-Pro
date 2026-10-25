"""Build the project file geodatabase from the raw downloads.

Outputs in data/sk_health_access.gdb:
  Hospitals        cleaned, de-duplicated hospital points (ODHF v1.1)
  DA_Polygons      2021 dissemination areas with census attributes
  DA_Points        one demand point per DA, snapped to its densest local streets
  Transport/Roads  NRN road segments with a drive-time field (MINUTES)
"""
import math
import re

import arcpy
import numpy as np
import pandas as pd

from config import (DEFAULT_SPEED, GDB, OUTPUTS, RAW, SR_WKID, UNPAVED_FACTOR)

arcpy.env.overwriteOutput = True
SR = arcpy.SpatialReference(SR_WKID)
WGS84 = arcpy.SpatialReference(4326)
NRN = RAW / "nrn" / "NRN_SK_15_0_GPKG_en.gpkg"
ROADSEG = str(NRN / "main.NRN_SK_15_0_ROADSEG")

# Specialty facilities without a general emergency department
EXCLUDE = re.compile(r"psychiatric|rehabilitation|mental health\)|^saskatchewan hospital", re.I)
# Facilities replaced by a newer hospital after the ODHF sources were compiled
SUPERSEDED = {"Moose Jaw Union Hospital"}  # replaced by Dr. F.H. Wigmore Regional (2015)
# Hospitals closer than this are treated as one site (duplicate records across sources)
DEDUP_M = 400
# When records merge, keep the name of the main acute-care hospital
MAIN_NAME = re.compile(r"regional|university|general|union|victoria", re.I)
# Neighbourhood radius used to find the densest cluster of local streets in a DA
STREET_RADIUS_M = 1500
# Seasonal links that cannot be relied on year-round
SKIP_CLASSES = ("Winter", "Rapid Transit")


def place_centroid(place):
    """Mean location (WGS84) of road segments whose left-side place name matches."""
    xs, ys = [], []
    where = f"L_PLACENAM = '{place}'"
    with arcpy.da.SearchCursor(ROADSEG, ["SHAPE@XY"], where, WGS84) as cur:
        for (x, y), in cur:
            xs.append(x)
            ys.append(y)
    if not xs:
        raise ValueError(f"No NRN segments named {place}")
    return sum(ys) / len(ys), sum(xs) / len(xs)


def clean_hospitals():
    df = pd.read_csv(RAW / "odhf" / "ODHF_v1.1" / "odhf_v1.1.csv", encoding="latin-1")
    df = df[(df["province"].str.lower() == "sk") & (df["odhf_facility_type"] == "Hospitals")]
    df = df[~df["facility_name"].str.contains(EXCLUDE)
            & ~df["facility_name"].isin(SUPERSEDED)].copy()
    df["city"] = df["city"].str.strip().str.lower()
    df["coord_source"] = "ODHF"

    # 1) Records without coordinates usually duplicate another record in the same town
    known = df.dropna(subset=["latitude"]).groupby("city")[["latitude", "longitude"]].first()
    missing = df["latitude"].isna()
    for idx in df.index[missing]:
        city = df.at[idx, "city"]
        if city in known.index:
            df.loc[idx, ["latitude", "longitude"]] = known.loc[city].values
            df.at[idx, "coord_source"] = "Same-town ODHF record"
        else:
            lat, lon = place_centroid(city.title())
            df.loc[idx, ["latitude", "longitude"]] = (lat, lon)
            df.at[idx, "coord_source"] = "NRN place-name centroid"

    # 2) Merge records within DEDUP_M of each other, keeping main-hospital names and
    #    original ODHF coordinates first
    df["rank"] = (~df["facility_name"].str.contains(MAIN_NAME)).astype(int)
    df = df.sort_values(["coord_source", "rank", "facility_name"]).reset_index(drop=True)
    keep, merged_names = [], {}
    for i, row in df.iterrows():
        for k in keep:
            dy = (row.latitude - df.at[k, "latitude"]) * 111_320
            dx = (row.longitude - df.at[k, "longitude"]) * 111_320 * math.cos(math.radians(row.latitude))
            if math.hypot(dx, dy) < DEDUP_M:
                merged_names[k].append(row.facility_name)
                break
        else:
            keep.append(i)
            merged_names[i] = []
    out = df.loc[keep, ["facility_name", "city", "source_facility_type",
                        "latitude", "longitude", "coord_source"]].copy()
    out["merged_records"] = ["; ".join(merged_names[k]) for k in keep]
    out["city"] = out["city"].str.title()
    out = out.sort_values("facility_name").reset_index(drop=True)
    out.insert(0, "HOSP_ID", range(1, len(out) + 1))
    OUTPUTS.mkdir(exist_ok=True)
    out.to_csv(OUTPUTS / "hospitals_clean.csv", index=False)
    print(f"  {len(out)} hospital sites after cleaning")
    return OUTPUTS / "hospitals_clean.csv"


def load_hospitals(csv):
    with arcpy.EnvManager(outputCoordinateSystem=SR):
        arcpy.management.XYTableToPoint(str(csv), str(GDB / "Hospitals"), "longitude",
                                        "latitude", coordinate_system=WGS84)


def load_das():
    polys = str(GDB / "DA_Polygons")
    tmp = arcpy.conversion.JSONToFeatures(str(RAW / "sk_da_2021.geojson"),
                                          f"{arcpy.env.scratchGDB}/da_wgs84", "POLYGON")
    arcpy.management.Project(tmp, polys, SR)

    census = pd.read_csv(RAW / "sk_da_census_2021.csv", dtype={"DAUID": str}).set_index("DAUID")
    fields = ["pop_2021", "pop_65plus", "indig_pop", "indig_base", "med_hh_income"]
    for f in fields:
        arcpy.management.AddField(polys, f, "DOUBLE")
    arcpy.management.AddField(polys, "pct_65plus", "DOUBLE")
    arcpy.management.AddField(polys, "pct_indig", "DOUBLE")
    with arcpy.da.UpdateCursor(polys, ["DAUID"] + fields + ["pct_65plus", "pct_indig"]) as cur:
        for row in cur:
            rec = census.loc[row[0]] if row[0] in census.index else None
            vals = [None if rec is None or pd.isna(rec[f]) else float(rec[f]) for f in fields]
            pop, p65, ind, base = vals[0], vals[1], vals[2], vals[3]
            pct65 = 100 * p65 / pop if pop and p65 is not None else None
            pctind = 100 * ind / base if base and ind is not None else None
            cur.updateRow([row[0]] + vals + [pct65, pctind])

    total = sum(r[0] or 0 for r in arcpy.da.SearchCursor(polys, ["pop_2021"]))
    print(f"  {int(arcpy.management.GetCount(polys)[0])} DAs, population {total:,.0f}")


def settlement_points():
    """One demand point per DA, placed where people actually live.

    Northern and rural DAs can cover thousands of km2, so a geometric centre may land
    far from the community. Local streets mark settlements: the point moves to the
    local-street midpoint with the most other street midpoints within STREET_RADIUS_M.
    DAs without local streets keep their interior point.
    """
    polys, pts = str(GDB / "DA_Polygons"), str(GDB / "DA_Points")
    arcpy.management.FeatureToPoint(polys, pts, "INSIDE")
    arcpy.management.AddField(pts, "PT_METHOD", "TEXT", field_length=24)

    streets = arcpy.management.MakeFeatureLayer(
        str(GDB / "Transport" / "Roads"), "streets", "ROADCLASS LIKE 'Local%'")[0]
    mids = arcpy.management.FeatureVerticesToPoints(streets, "memory/mids", "MID")
    joined = arcpy.analysis.SpatialJoin(mids, polys, "memory/mids_da", "JOIN_ONE_TO_ONE",
                                        match_option="INTERSECT")
    by_da = {}
    with arcpy.da.SearchCursor(joined, ["DAUID", "SHAPE@X", "SHAPE@Y"]) as cur:
        for dauid, x, y in cur:
            if dauid:
                by_da.setdefault(dauid, []).append((x, y))

    moved = kept = 0
    with arcpy.da.UpdateCursor(pts, ["DAUID", "SHAPE@XY", "PT_METHOD"]) as cur:
        for dauid, xy, _ in cur:
            coords = np.array(by_da.get(dauid, []))
            if len(coords) == 0:
                cur.updateRow([dauid, xy, "Interior point"])
                kept += 1
                continue
            if len(coords) > 2000:  # keep the pairwise matrix small in dense urban DAs
                coords = coords[np.random.default_rng(0).choice(len(coords), 2000, replace=False)]
            d2 = ((coords[:, None, :] - coords[None, :, :]) ** 2).sum(axis=2)
            best = coords[(d2 < STREET_RADIUS_M ** 2).sum(axis=1).argmax()]
            cur.updateRow([dauid, (float(best[0]), float(best[1])), "Densest local streets"])
            moved += 1
    print(f"  {moved:,} DA points placed on settlement streets, {kept:,} interior points")


def load_roads():
    fd = str(GDB / "Transport")
    arcpy.management.CreateFeatureDataset(str(GDB), "Transport", SR)
    # Network datasets require 32-bit ObjectIDs; GeoPackage exports default to 64-bit
    roads = arcpy.management.CreateFeatureclass(fd, "Roads", "POLYLINE", spatial_reference=SR,
                                                oid_type="32_BIT")[0]
    for name, ftype, length in [("NID", "TEXT", 32), ("ROADCLASS", "TEXT", 40),
                                ("PAVSTATUS", "TEXT", 12), ("RTNUMBER1", "TEXT", 10),
                                ("STREET", "TEXT", 100), ("SPEED", "SHORT", None),
                                ("KPH", "DOUBLE", None), ("MINUTES", "DOUBLE", None)]:
        arcpy.management.AddField(roads, name, ftype, field_length=length)

    src_fields = ["SHAPE@", "NID", "ROADCLASS", "PAVSTATUS", "RTNUMBER1", "R_STNAME_C", "SPEED"]
    out_fields = src_fields[:5] + ["STREET", "SPEED", "KPH", "MINUTES"]
    n = skipped = 0
    with arcpy.da.SearchCursor(ROADSEG, src_fields, spatial_reference=SR) as src, \
            arcpy.da.InsertCursor(roads, out_fields) as dst:
        for shape, nid, rclass, pav, rte, street, speed in src:
            if rclass in SKIP_CLASSES or shape is None:
                skipped += 1
                continue
            kph = speed if speed and speed > 0 else DEFAULT_SPEED.get(rclass, 50)
            if pav == "Unpaved":
                kph *= UNPAVED_FACTOR
            minutes = shape.length / 1000 / kph * 60
            dst.insertRow([shape, nid, rclass, pav, rte, street, speed, kph, minutes])
            n += 1
    print(f"  {n:,} road segments loaded ({skipped:,} winter/transit/empty skipped)")


if __name__ == "__main__":
    if arcpy.Exists(str(GDB)):
        arcpy.management.Delete(str(GDB))
    arcpy.management.CreateFileGDB(str(GDB.parent), GDB.name)
    print("Hospitals")
    load_hospitals(clean_hospitals())
    print("Dissemination areas + census")
    load_das()
    print("Roads")
    load_roads()
    print("Demand points")
    settlement_points()
