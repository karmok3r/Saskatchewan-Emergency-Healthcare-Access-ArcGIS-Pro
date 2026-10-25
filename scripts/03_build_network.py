"""Build a drive-time network dataset (Transport/Roads_ND) from the prepared NRN roads.

CreateNetworkDataset only gives a Length attribute, so the script exports the
schema as an XML template, adds a Minutes cost attribute evaluated from the
MINUTES field, and recreates the network from the edited template.
"""
import json
import re
from xml.sax.saxutils import escape

import arcpy

from config import GDB, ROOT, TRAVEL_MODE

arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("Network")

FD = str(GDB / "Transport")
ND = f"{FD}/Roads_ND"
TEMPLATE = ROOT / "data" / "roads_nd_template.xml"


def add_minutes_attribute(xml):
    """Duplicate the Length attribute and its evaluators as a Minutes cost attribute."""
    attr = re.search(r"<EvaluatedNetworkAttribute .*?</EvaluatedNetworkAttribute>", xml, re.S).group()
    minutes = (attr.replace("<ID>1</ID>", "<ID>2</ID>")
                   .replace("<Name>Length</Name>", "<Name>Minutes</Name>")
                   .replace("<Units>Meters</Units>", "<Units>Minutes</Units>")
                   .replace("<UseByDefault>false</UseByDefault>", "<UseByDefault>true</UseByDefault>"))
    xml = xml.replace(attr, attr + minutes)

    assigns = re.findall(r"<NetworkAssignment .*?</NetworkAssignment>", xml, re.S)
    new = [a.replace("<NetworkAttributeName>Length</NetworkAttributeName>",
                     "<NetworkAttributeName>Minutes</NetworkAttributeName>")
            .replace("!Shape!", "!MINUTES!") for a in assigns]
    return xml.replace(assigns[-1], assigns[-1] + "".join(new))


def add_travel_mode(xml):
    """Store a default 'Driving Time' travel mode in the network-level property set.

    arcpy has no tool for adding travel modes, but templates carry them as JSON
    (same layout as the Indoors network templates shipped with ArcGIS Pro).
    """
    mode = json.dumps({
        "name": TRAVEL_MODE, "type": "AUTOMOBILE",
        "description": "Free-flow driving time on the NRN road network",
        "impedanceAttributeName": "Minutes", "timeAttributeName": "Minutes",
        "distanceAttributeName": "Length", "restrictionAttributeNames": [],
        "attributeParameterValues": [], "useHierarchy": False,
        "uturnAtJunctions": "esriNFSBAllowBacktrack",
        "simplificationTolerance": None, "simplificationToleranceUnits": "esriUnknownUnits"})
    prop = ("<PropertySetProperty xsi:type='typens:PropertySetProperty'><Key>{}</Key>"
            "<Value xsi:type='{}'>{}</Value></PropertySetProperty>")
    props = ("<Properties xsi:type='typens:PropertySet'>"
             "<PropertyArray xsi:type='typens:ArrayOfPropertySetProperty'>"
             "<PropertySetProperty xsi:type='typens:PropertySetProperty'>"
             "<Key>NetworkTravelModes</Key><Value xsi:type='typens:PropertySet'>"
             "<PropertyArray xsi:type='typens:ArrayOfPropertySetProperty'>"
             + prop.format("TravelModeCount", "xs:int", 1)
             + prop.format("TravelMode0", "xs:string", escape(mode))
             + prop.format("DefaultTravelModeName", "xs:string", TRAVEL_MODE)
             + "</PropertyArray></Value></PropertySetProperty></PropertyArray></Properties>")
    anchor = "<SupportsTurns>true</SupportsTurns><Properties xsi:nil='true'/>"
    if anchor not in xml:
        raise ValueError("Unexpected template layout; network properties not found")
    return xml.replace(anchor, "<SupportsTurns>true</SupportsTurns>" + props, 1)


def build():
    if arcpy.Exists(ND):
        arcpy.management.Delete(ND)
    arcpy.na.CreateNetworkDataset(FD, "Roads_ND", ["Roads"], "NO_ELEVATION")
    arcpy.na.CreateTemplateFromNetworkDataset(ND, str(TEMPLATE))
    TEMPLATE.write_text(add_travel_mode(add_minutes_attribute(TEMPLATE.read_text())))
    arcpy.management.Delete(ND)

    arcpy.na.CreateNetworkDatasetFromTemplate(str(TEMPLATE), FD)
    print("  building network (this takes a few minutes)...")
    arcpy.na.BuildNetwork(ND)
    desc = arcpy.Describe(ND)
    print("  attributes:", [(a.name, a.units) for a in desc.attributes])


def smoke_test():
    """Route between Regina General and Royal University Hospital (~235 km by Hwy 11)."""
    route = arcpy.nax.Route(ND)
    route.travelMode = TRAVEL_MODE
    route.timeUnits = arcpy.nax.TimeUnits.Minutes
    route.distanceUnits = arcpy.nax.DistanceUnits.Kilometers
    hosp = str(GDB / "Hospitals")
    route.load(arcpy.nax.RouteInputDataType.Stops,
               arcpy.management.MakeFeatureLayer(
                   hosp, "stops", "facility_name IN ('Regina General Hospital', "
                                  "'Royal University Hospital (Ruh)')")[0])
    result = route.solve()
    with result.searchCursor(arcpy.nax.RouteOutputDataType.Routes,
                             ["Total_Minutes", "Total_Kilometers"]) as cur:
        for minutes, km in cur:
            print(f"  Regina -> Saskatoon: {km:.0f} km, {minutes:.0f} min")


if __name__ == "__main__":
    build()
    smoke_test()
