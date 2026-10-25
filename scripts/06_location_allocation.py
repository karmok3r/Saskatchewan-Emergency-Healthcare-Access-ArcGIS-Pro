"""Where would 1-3 new emergency sites bring the most people within 30 minutes?

Maximize Coverage location-allocation: the existing hospitals are Required
facilities, and candidate sites are populated DA points currently more than
COVERAGE_CUTOFF minutes from a hospital. Demand is every DA point weighted by
2021 population.

Outputs:
  gdb/Candidate_Sites, gdb/New_Sites_k{1,2,3}
  outputs/location_allocation.csv
"""
import arcpy
import pandas as pd

from config import COVERAGE_CUTOFF, GDB, ND, OUTPUTS, RAW, TRAVEL_MODE

arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Network")

HOSP = str(GDB / "Hospitals")
DA_PTS = str(GDB / "DA_Points")
CANDIDATES = str(GDB / "Candidate_Sites")
MIN_CANDIDATE_POP = 100  # ignore near-empty DAs as candidate sites
LA = arcpy.nax.LocationAllocationInputDataType
NRN_ROADS = str(RAW / "nrn" / "NRN_SK_15_0_GPKG_en.gpkg" / "main.NRN_SK_15_0_ROADSEG")


def make_candidates():
    """Populated DA points beyond the cutoff (DRIVE_MIN comes from 04_access_analysis)."""
    drive = {r[0]: r[1:] for r in arcpy.da.SearchCursor(
        str(GDB / "DA_Polygons"), ["DAUID", "DRIVE_MIN", "pop_2021"])}
    ids = [d for d, (m, p) in drive.items()
           if m is not None and m > COVERAGE_CUTOFF and (p or 0) >= MIN_CANDIDATE_POP]
    where = "DAUID IN ({})".format(",".join(f"'{d}'" for d in ids))
    arcpy.conversion.ExportFeatures(DA_PTS, CANDIDATES, where)
    print(f"  {len(ids)} candidate sites")


def solve(k, n_existing):
    la = arcpy.nax.LocationAllocation(str(ND))
    la.travelMode = TRAVEL_MODE
    la.timeUnits = arcpy.nax.TimeUnits.Minutes
    la.problemType = arcpy.nax.LocationAllocationProblemType.MaximizeCoverage
    la.defaultImpedanceCutoff = COVERAGE_CUTOFF
    la.facilityCount = n_existing + k
    la.travelDirection = arcpy.nax.TravelDirection.FromFacility
    la.searchTolerance = 25
    la.searchToleranceUnits = arcpy.nax.DistanceUnits.Kilometers

    fm = la.fieldMappings(LA.Facilities)
    fm["Name"].mappedFieldName = "facility_name"
    fm["FacilityType"].defaultValue = 1  # required
    la.load(LA.Facilities, HOSP, fm)
    fm = la.fieldMappings(LA.Facilities)
    fm["Name"].mappedFieldName = "DAUID"
    fm["FacilityType"].defaultValue = 0  # candidate
    la.load(LA.Facilities, CANDIDATES, fm, append=True)

    fm = la.fieldMappings(LA.DemandPoints)
    fm["Name"].mappedFieldName = "DAUID"
    fm["Weight"].mappedFieldName = "pop_2021"
    la.load(LA.DemandPoints, DA_PTS, fm)

    result = la.solve()
    if not result.solveSucceeded:
        raise RuntimeError(result.solverMessages(arcpy.nax.MessageSeverity.All))

    chosen, covered = [], 0.0
    with result.searchCursor(arcpy.nax.LocationAllocationOutputDataType.Facilities,
                             ["Name", "FacilityType", "DemandWeight", "SHAPE@"]) as cur:
        for name, ftype, weight, shape in cur:
            covered += weight or 0
            if ftype == 3:  # chosen candidate
                chosen.append((name, nearest_place(shape), weight or 0, shape))

    out = str(GDB / f"New_Sites_k{k}")
    arcpy.management.CreateFeatureclass(str(GDB), f"New_Sites_k{k}", "POINT",
                                        spatial_reference=arcpy.Describe(HOSP).spatialReference)
    arcpy.management.AddField(out, "DAUID", "TEXT", field_length=12)
    arcpy.management.AddField(out, "PLACE", "TEXT", field_length=60)
    arcpy.management.AddField(out, "POP_SERVED", "DOUBLE")
    with arcpy.da.InsertCursor(out, ["DAUID", "PLACE", "POP_SERVED", "SHAPE@"]) as ins:
        for row in chosen:
            ins.insertRow(row)
    return covered, chosen


def nearest_place(shape):
    """Label a site with the most common NRN place name within 3 km (skipping RM names)."""
    roads = arcpy.management.MakeFeatureLayer(NRN_ROADS, "nrn_roads")[0]
    arcpy.management.SelectLayerByLocation(roads, "WITHIN_A_DISTANCE", shape, "3 Kilometers")
    names = [r[0] for r in arcpy.da.SearchCursor(roads, ["L_PLACENAM"])
             if r[0] and r[0] != "None" and not r[0].startswith("Rm Of")]
    if not names:  # fall back to the rural municipality name
        names = [r[0] for r in arcpy.da.SearchCursor(roads, ["L_PLACENAM"]) if r[0]]
    return pd.Series(names).mode().iat[0].replace("Rm Of ", "RM of ") if names else ""


if __name__ == "__main__":
    print("Candidate sites")
    make_candidates()
    n_existing = int(arcpy.management.GetCount(HOSP)[0])
    total = sum(r[0] or 0 for r in arcpy.da.SearchCursor(DA_PTS, ["pop_2021"]))
    rows = []
    for k in (0, 1, 2, 3):
        covered, chosen = solve(k, n_existing)
        rows.append({"new_sites": k, "pop_within_30": round(covered),
                     "pct_within_30": round(100 * covered / total, 2),
                     "chosen_DAUIDs": "; ".join(c[0] for c in chosen),
                     "chosen_places": "; ".join(c[1] for c in chosen)})
        print(f"  k={k}: {covered:,.0f} people within {COVERAGE_CUTOFF} min "
              f"({100 * covered / total:.1f}%)  new: {[c[1] for c in chosen]}")
    df = pd.DataFrame(rows)
    df["added_vs_today"] = df["pop_within_30"] - df.loc[0, "pop_within_30"]
    df.to_csv(OUTPUTS / "location_allocation.csv", index=False)
    print(df.to_string(index=False))
