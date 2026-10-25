"""ArcGIS Pro Python toolbox: drive-time access to the nearest facility.

Generalises the project workflow so it can be re-run for any facility type
(hospitals, pharmacies, schools, EMS bases) on any network dataset with a
time-based travel mode. Add it in Pro via Catalog > Toolboxes > Add Toolbox.
"""
import arcpy


class Toolbox:
    def __init__(self):
        self.label = "Health Access"
        self.alias = "healthaccess"
        self.tools = [NearestFacilityAccess]


class NearestFacilityAccess:
    def __init__(self):
        self.label = "Nearest Facility Drive-Time Access"
        self.description = ("Finds the drive time from every demand point to its nearest "
                            "facility and reports the population within each time threshold.")
        self.canRunInBackground = True

    def getParameterInfo(self):
        network = arcpy.Parameter(displayName="Network dataset", name="network",
                                  datatype=["DENetworkDataset", "GPNetworkDatasetLayer"],
                                  parameterType="Required", direction="Input")
        mode = arcpy.Parameter(displayName="Travel mode", name="travel_mode",
                               datatype="NetworkTravelMode", parameterType="Required",
                               direction="Input")
        mode.parameterDependencies = [network.name]
        facilities = arcpy.Parameter(displayName="Facilities", name="facilities",
                                     datatype="GPFeatureLayer", parameterType="Required",
                                     direction="Input")
        facilities.filter.list = ["Point"]
        demand = arcpy.Parameter(displayName="Demand points", name="demand",
                                 datatype="GPFeatureLayer", parameterType="Required",
                                 direction="Input")
        demand.filter.list = ["Point"]
        pop = arcpy.Parameter(displayName="Population field", name="pop_field",
                              datatype="Field", parameterType="Required", direction="Input")
        pop.parameterDependencies = [demand.name]
        pop.filter.list = ["Short", "Long", "Float", "Double"]
        breaks = arcpy.Parameter(displayName="Thresholds (minutes)", name="breaks",
                                 datatype="GPDouble", parameterType="Required",
                                 direction="Input", multiValue=True)
        breaks.value = [15, 30, 60, 90]
        tolerance = arcpy.Parameter(displayName="Search tolerance (km)", name="tolerance",
                                    datatype="GPDouble", parameterType="Optional",
                                    direction="Input")
        tolerance.value = 25
        out = arcpy.Parameter(displayName="Output demand points", name="out_fc",
                              datatype="DEFeatureClass", parameterType="Required",
                              direction="Output")
        table = arcpy.Parameter(displayName="Output coverage table", name="out_table",
                                datatype="DETable", parameterType="Optional",
                                direction="Output")
        return [network, mode, facilities, demand, pop, breaks, tolerance, out, table]

    def isLicensed(self):
        return arcpy.CheckExtension("Network") == "Available"

    def execute(self, parameters, messages):
        p = {param.name: param for param in parameters}
        network = p["network"].valueAsText
        breaks = sorted(float(b) for b in p["breaks"].values)
        pop_field = p["pop_field"].valueAsText
        out_fc = p["out_fc"].valueAsText

        arcpy.CheckOutExtension("Network")
        od = arcpy.nax.OriginDestinationCostMatrix(network)
        od.travelMode = p["travel_mode"].value
        od.timeUnits = arcpy.nax.TimeUnits.Minutes
        od.defaultDestinationCount = 1
        od.lineShapeType = arcpy.nax.LineShapeType.NoLine
        od.searchTolerance = p["tolerance"].value or 25
        od.searchToleranceUnits = arcpy.nax.DistanceUnits.Kilometers

        arcpy.management.CopyFeatures(p["demand"].valueAsText, out_fc)
        oid = arcpy.Describe(out_fc).OIDFieldName
        arcpy.management.AddField(out_fc, "SRC_OID", "LONG")
        arcpy.management.CalculateField(out_fc, "SRC_OID", f"!{oid}!")
        fm = od.fieldMappings(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins)
        fm["Name"].mappedFieldName = "SRC_OID"
        od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins, out_fc, fm)
        od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations,
                p["facilities"].valueAsText)
        messages.addMessage("Solving origin-destination cost matrix...")
        result = od.solve()
        if not result.solveSucceeded:
            raise arcpy.ExecuteError(result.solverMessages(arcpy.nax.MessageSeverity.All))

        names = {}
        with result.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Origins,
                                 ["ObjectID", "Name"]) as cur:
            names = {o: int(n) for o, n in cur}
        minutes = {}
        with result.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Lines,
                                 ["OriginOID", "Total_Time"]) as cur:
            for o, t in cur:
                minutes[names[o]] = t

        arcpy.management.AddField(out_fc, "DRIVE_MIN", "DOUBLE")
        arcpy.management.AddField(out_fc, "ACCESS_BAND", "TEXT", field_length=20)
        totals = {}
        with arcpy.da.UpdateCursor(out_fc, ["SRC_OID", pop_field, "DRIVE_MIN", "ACCESS_BAND"]) as cur:
            for src, pop, _, _ in cur:
                t = minutes.get(src)
                band = ("Not reachable" if t is None else
                        next((f"<= {b:g} min" for b in breaks if t <= b), f"> {breaks[-1]:g} min"))
                totals[band] = totals.get(band, 0) + (pop or 0)
                cur.updateRow([src, pop, t, band])

        grand = sum(totals.values()) or 1
        order = [f"<= {b:g} min" for b in breaks] + [f"> {breaks[-1]:g} min", "Not reachable"]
        for band in order:
            messages.addMessage(f"{band:>14}: {totals.get(band, 0):>12,.0f} "
                                f"({100 * totals.get(band, 0) / grand:.1f}%)")

        if p["out_table"].valueAsText:
            table = p["out_table"].valueAsText
            path, name = table.rsplit("\\", 1) if "\\" in table else table.rsplit("/", 1)
            arcpy.management.CreateTable(path, name)
            arcpy.management.AddField(table, "ACCESS_BAND", "TEXT", field_length=20)
            arcpy.management.AddField(table, "POPULATION", "DOUBLE")
            arcpy.management.AddField(table, "PERCENT", "DOUBLE")
            with arcpy.da.InsertCursor(table, ["ACCESS_BAND", "POPULATION", "PERCENT"]) as ins:
                for band in order:
                    ins.insertRow([band, totals.get(band, 0), 100 * totals.get(band, 0) / grand])
