"""Drive time from every dissemination area to its nearest hospital, plus service areas.

Outputs:
  gdb/DA_Polygons     gains NEAR_HOSP, DRIVE_MIN, SNAP_KM and ACCESS_BAND fields
  gdb/ServiceAreas    dissolved 15/30/60/90-minute drive-time zones
  outputs/da_access.csv, outputs/access_summary.csv
"""
import arcpy
import pandas as pd

from config import BREAKS, GDB, ND, OUTPUTS, TRAVEL_MODE

arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Network")

HOSP = str(GDB / "Hospitals")
DA_PTS = str(GDB / "DA_Points")
DA_POLY = str(GDB / "DA_Polygons")
# Rural DA interior points can sit several km from the nearest mapped road
SEARCH_KM = 25


def band(minutes):
    if minutes is None:
        return "No road access"
    for b in BREAKS:
        if minutes <= b:
            return f"<= {b} min"
    return f"> {BREAKS[-1]} min"


def nearest_hospital():
    od = arcpy.nax.OriginDestinationCostMatrix(str(ND))
    od.travelMode = TRAVEL_MODE
    od.timeUnits = arcpy.nax.TimeUnits.Minutes
    od.distanceUnits = arcpy.nax.DistanceUnits.Kilometers
    od.defaultDestinationCount = 1
    od.lineShapeType = arcpy.nax.LineShapeType.NoLine
    od.searchTolerance = SEARCH_KM
    od.searchToleranceUnits = arcpy.nax.DistanceUnits.Kilometers

    fm = od.fieldMappings(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins)
    fm["Name"].mappedFieldName = "DAUID"
    od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins, DA_PTS, fm)
    fm = od.fieldMappings(arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations)
    fm["Name"].mappedFieldName = "facility_name"
    od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations, HOSP, fm)

    result = od.solve()
    if not result.solveSucceeded:
        raise RuntimeError(result.solverMessages(arcpy.nax.MessageSeverity.All))

    origins = {}
    with result.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Origins,
                             ["ObjectID", "Name", "Status", "SnapX"]) as cur:
        for oid, name, status, _ in cur:
            origins[oid] = name
    lines = {}
    with result.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Lines,
                             ["OriginOID", "DestinationName", "Total_Time", "Total_Distance"]) as cur:
        for oid, dest, minutes, km in cur:
            lines[origins[oid]] = (dest, minutes, km)
    print(f"  solved {len(lines):,} of {len(origins):,} DAs "
          f"({len(origins) - len(lines)} not reachable within {SEARCH_KM} km of a road)")
    return lines


def write_to_das(lines):
    for name, ftype, length in [("NEAR_HOSP", "TEXT", 120), ("DRIVE_MIN", "DOUBLE", None),
                                ("DRIVE_KM", "DOUBLE", None), ("ACCESS_BAND", "TEXT", 20)]:
        if name not in [f.name for f in arcpy.ListFields(DA_POLY)]:
            arcpy.management.AddField(DA_POLY, name, ftype, field_length=length)
    rows = []
    fields = ["DAUID", "pop_2021", "pop_65plus", "indig_pop", "indig_base", "med_hh_income",
              "NEAR_HOSP", "DRIVE_MIN", "DRIVE_KM", "ACCESS_BAND"]
    with arcpy.da.UpdateCursor(DA_POLY, fields) as cur:
        for row in cur:
            dest, minutes, km = lines.get(row[0], (None, None, None))
            row[6:] = [dest, minutes, km, band(minutes)]
            cur.updateRow(row)
            rows.append(row)
    df = pd.DataFrame(rows, columns=fields)
    df.to_csv(OUTPUTS / "da_access.csv", index=False)
    return df


def summarise(df):
    order = [f"<= {b} min" for b in BREAKS] + [f"> {BREAKS[-1]} min", "No road access"]
    groups = {"Total population": "pop_2021", "Age 65+": "pop_65plus",
              "Indigenous identity": "indig_pop"}
    table = pd.DataFrame({label: df.groupby("ACCESS_BAND")[col].sum() for label, col in groups.items()})
    table = table.reindex(order).fillna(0)
    pct = 100 * table / table.sum()
    out = pd.concat({"people": table.round(0), "percent": pct.round(1)}, axis=1)
    out.index.name = "Drive time to nearest hospital"
    out.to_csv(OUTPUTS / "access_summary.csv")
    print(out.to_string())

    reached = df.dropna(subset=["DRIVE_MIN"])
    for label, col in groups.items():
        w = reached[col].fillna(0)
        print(f"  population-weighted mean drive time, {label}: "
              f"{(reached['DRIVE_MIN'] * w).sum() / w.sum():.1f} min")


def service_areas():
    sa = arcpy.nax.ServiceArea(str(ND))
    sa.travelMode = TRAVEL_MODE
    sa.timeUnits = arcpy.nax.TimeUnits.Minutes
    sa.defaultImpedanceCutoffs = BREAKS
    sa.travelDirection = arcpy.nax.TravelDirection.ToFacility
    sa.geometryAtOverlap = arcpy.nax.ServiceAreaOverlapGeometry.Dissolve
    sa.geometryAtCutoff = arcpy.nax.ServiceAreaPolygonCutoffGeometry.Rings
    sa.polygonDetail = arcpy.nax.ServiceAreaPolygonDetail.Standard
    sa.load(arcpy.nax.ServiceAreaInputDataType.Facilities, HOSP)
    result = sa.solve()
    if not result.solveSucceeded:
        raise RuntimeError(result.solverMessages(arcpy.nax.MessageSeverity.All))
    result.export(arcpy.nax.ServiceAreaOutputDataType.Polygons, str(GDB / "ServiceAreas"))
    print(f"  service areas written ({len(BREAKS)} bands)")


if __name__ == "__main__":
    OUTPUTS.mkdir(exist_ok=True)
    print("Closest hospital (OD cost matrix)")
    df = write_to_das(nearest_hospital())
    print("Coverage summary")
    summarise(df)
    print("Service areas")
    service_areas()
