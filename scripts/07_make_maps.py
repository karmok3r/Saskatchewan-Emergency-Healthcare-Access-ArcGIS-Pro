"""Build SK_Health_Access.aprx with three print layouts and export them (PNG + PDF).

  1. Drive time from each dissemination area to the nearest hospital
  2. 15/30/60/90-minute drive-time service areas
  3. Hot spots of long drive times and the location-allocation sites

Starts from the Blank.aprx that ships with ArcGIS Pro, so no manual setup is needed.
"""
import shutil
import sys
from pathlib import Path

import arcpy

from config import APRX, BREAKS, GDB, MAPS

arcpy.env.overwriteOutput = True

BLANK = r"C:\Program Files\ArcGIS\Pro\Resources\ArcToolBox\Services\routingservices\data\Blank.aprx"
MAP_SR = arcpy.SpatialReference(26913)  # NAD83 / UTM 13N keeps Saskatchewan upright
PAGE_W, PAGE_H = 8.5, 11.0

# Same light -> dark sequential blues as the charts (short -> long drive)
BLUES = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
NO_ACCESS = "#898781"
HOT = {"3": "#b2182b", "2": "#d6604d", "1": "#f4a582", "0": "#ecebe6"}
INK = "#0b0b0b"
SOURCES = ("Data: Statistics Canada ODHF v1.1, 2021 Census, National Road Network 15.0 "
           "(Open Government Licence - Canada). Free-flow drive times; see README for method.")


def rgb(hex_color, alpha=100):
    h = hex_color.lstrip("#")
    return {"RGB": [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alpha]}


def province_outline():
    out = str(GDB / "Province")
    if not arcpy.Exists(out):
        arcpy.management.Dissolve(str(GDB / "DA_Polygons"), out)
    return out


def style_simple(lyr, fill=None, outline="#52514e", width=0.4, size=None):
    sym = lyr.symbology
    s = sym.renderer.symbol
    if fill is not None:
        s.color = rgb(fill) if fill else {"RGB": [0, 0, 0, 0]}
    s.outlineColor = rgb(outline)
    s.outlineWidth = width
    if size:
        s.size = size
    lyr.symbology = sym


def style_hospitals(lyr):
    sym = lyr.symbology
    sym.renderer.symbol.applySymbolFromGallery("Circle 1")
    sym.renderer.symbol.color = rgb("#d03b3b")
    sym.renderer.symbol.outlineColor = rgb("#ffffff")
    sym.renderer.symbol.size = 6
    sym.renderer.label = "Hospital (ODHF, cleaned)"
    lyr.symbology = sym


def style_drive_time(lyr):
    sym = lyr.symbology
    sym.updateRenderer("GraduatedColorsRenderer")
    r = sym.renderer
    r.classificationField = "DRIVE_MIN"
    r.breakCount = len(BLUES)
    labels = [f"≤ {BREAKS[0]} min"] + [f"{a}–{b} min" for a, b in zip(BREAKS, BREAKS[1:])] \
        + [f"> {BREAKS[-1]} min"]
    uppers = BREAKS + [1000]
    # Setting upper bounds regenerates labels, so commit the bounds before labelling
    for brk, upper in zip(r.classBreaks, uppers):
        brk.upperBound = upper
    lyr.symbology = sym
    sym = lyr.symbology
    for brk, color in zip(sym.renderer.classBreaks, BLUES):
        brk.symbol.color = rgb(color)
        brk.symbol.outlineColor = rgb("#ffffff", 30)
        brk.symbol.outlineWidth = 0.1
    lyr.symbology = sym
    # The symbology API does not persist class labels, so set them in the CIM
    cim = lyr.getDefinition("V3")
    for brk, label in zip(cim.renderer.breaks, labels):
        brk.label = label
    lyr.setDefinition(cim)
    clear_heading(lyr)


def clear_heading(lyr):
    """Hide the field-name heading (e.g. DRIVE_MIN) that Pro adds to legend entries."""
    cim = lyr.getDefinition("V3")
    if hasattr(cim.renderer, "heading"):
        cim.renderer.heading = ""
    for group in getattr(cim.renderer, "groups", None) or []:
        group.heading = ""
    lyr.setDefinition(cim)


def style_service_areas(lyr):
    sym = lyr.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = ["ToBreak"]
    lyr.symbology = sym
    sym = lyr.symbology
    colors = dict(zip([str(b) for b in BREAKS], BLUES))
    for item in sym.renderer.groups[0].items:
        val = str(int(float(item.values[0][0])))
        lo = [0] + BREAKS
        item.label = f"{lo[BREAKS.index(int(val))]}–{val} min"
        item.symbol.color = rgb(colors[val], 85)
        item.symbol.outlineColor = rgb("#ffffff", 0)
    lyr.symbology = sym
    clear_heading(lyr)


def style_hot_spots(lyr):
    sym = lyr.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = ["Gi_Bin"]
    lyr.symbology = sym
    sym = lyr.symbology
    labels = {"3": "Hot spot, 99% confidence", "2": "Hot spot, 95% confidence",
              "1": "Hot spot, 90% confidence", "0": "Not significant"}
    for item in sym.renderer.groups[0].items:
        val = str(item.values[0][0])
        item.label = labels.get(val, val)
        item.symbol.color = rgb(HOT.get(val, "#ecebe6"))
        item.symbol.outlineColor = rgb("#ffffff", 25)
        item.symbol.outlineWidth = 0.1
    lyr.symbology = sym
    clear_heading(lyr)


def style_new_sites(lyr):
    sym = lyr.symbology
    sym.renderer.symbol.applySymbolFromGallery("Star 1")
    sym.renderer.symbol.color = rgb("#eda100")
    sym.renderer.symbol.outlineColor = rgb(INK)
    sym.renderer.symbol.size = 16
    sym.renderer.label = "Proposed site (maximize 30-min coverage)"
    lyr.symbology = sym
    lyr.showLabels = True
    lbl = lyr.listLabelClasses()[0]
    lbl.expression = 'Replace($feature.PLACE, "Rm Of ", "RM of ")'
    lbl.expressionEngine = "Arcade"


def new_map(aprx, name, outline):
    m = aprx.createMap(name, "MAP")
    m.spatialReference = MAP_SR
    for lyr in m.listLayers():
        m.removeLayer(lyr)
    prov = m.addDataFromPath(outline)
    prov.name = "Saskatchewan"
    style_simple(prov, fill="#f9f9f7", outline="#52514e", width=0.8)
    return m


def add(m, path, name, styler=None, query=None):
    lyr = m.addDataFromPath(path)
    lyr.name = name
    if query:
        lyr.definitionQuery = query
    if styler:
        styler(lyr)
    return lyr


def build_layout(aprx, m, title, subtitle, name, extent_layer):
    lyt = aprx.createLayout(PAGE_W, PAGE_H, "INCH", name)
    mf = lyt.createMapFrame(arcpy.Extent(0.35, 1.25, 5.85, 9.85), m, "Map Frame")
    mf.camera.setExtent(mf.getLayerExtent(extent_layer, False, True))
    mf.camera.scale *= 1.03

    aprx.createTextElement(lyt, arcpy.Point(0.4, 10.55), "POINT", title, 20,
                           style_item=None, name="Title")
    aprx.createTextElement(lyt, arcpy.Point(0.4, 10.17), "POINT", subtitle, 10.5,
                           name="Subtitle")
    legend = lyt.createMapSurroundElement(arcpy.Point(6.0, 9.85), "LEGEND", mf,
                                          name="Legend")
    legend.elementWidth = 2.3
    legend.title = ""
    for item in legend.items:
        if item.name == "Saskatchewan":
            item.visible = False
    # Hide the field-name headings (DRIVE_MIN, Gi_Bin) under each legend entry
    cim = lyt.getDefinition("V3")
    for el in cim.elements:
        if type(el).__name__ == "CIMLegend":
            for item in el.items:
                item.showHeading = False
    lyt.setDefinition(cim)

    north = aprx.listStyleItems("ArcGIS 2D", "NORTH_ARROW", "ArcGIS North 1")[0]
    na = lyt.createMapSurroundElement(arcpy.Point(6.2, 2.4), "NORTH_ARROW", mf, north)
    na.elementHeight = 0.6
    bar = aprx.listStyleItems("ArcGIS 2D", "SCALE_BAR", "Scale Line 1 Metric")
    bar = bar[0] if bar else aprx.listStyleItems("ArcGIS 2D", "SCALE_BAR")[0]
    sb = lyt.createMapSurroundElement(arcpy.Point(6.0, 1.55), "SCALE_BAR", mf, bar)
    sb.elementWidth = 2.2

    credit = aprx.createTextElement(lyt, arcpy.Point(0.4, 0.75), "POINT",
                                    SOURCES + "\nMap: NAD83 / UTM zone 13N. Author: Uday Karmoker, 2026.",
                                    7, name="Credits")
    return lyt


def export(lyt, stem):
    MAPS.mkdir(exist_ok=True)
    lyt.exportToPNG(str(MAPS / f"{stem}.png"), resolution=200)
    lyt.exportToPDF(str(MAPS / f"{stem}.pdf"), resolution=300)
    print(f"  exported maps/{stem}.png/.pdf")


def main(aprx_path=APRX):
    """Rebuild the project from scratch. Pass another path if the project is open in Pro."""
    aprx_path = Path(aprx_path)
    try:
        aprx_path.unlink(missing_ok=True)
    except PermissionError:
        sys.exit(f"{aprx_path.name} is open in ArcGIS Pro. Close it, or run:\n"
                 f"  python 07_make_maps.py <other_path.aprx>")
    shutil.copy(BLANK, aprx_path)
    aprx = arcpy.mp.ArcGISProject(str(aprx_path))
    aprx.defaultGeodatabase = str(GDB)
    for m in aprx.listMaps():
        aprx.deleteItem(m)
    for lyt in aprx.listLayouts():
        aprx.deleteItem(lyt)

    outline = province_outline()
    hosp = str(GDB / "Hospitals")
    das = str(GDB / "DA_Polygons")

    # 1. Drive time choropleth
    m = new_map(aprx, "Drive Time", outline)
    add(m, das, "No road connection", lambda l: style_simple(l, fill=NO_ACCESS,
                                                              outline="#ffffff", width=0.1),
        "DRIVE_MIN IS NULL")
    da_lyr = add(m, das, "Drive time to nearest hospital", style_drive_time, "DRIVE_MIN IS NOT NULL")
    add(m, hosp, "Hospitals", style_hospitals)
    lyt = build_layout(aprx, m, "How far is the nearest emergency department?",
                       "Free-flow drive time from each 2021 dissemination area to the nearest hospital",
                       "01 Drive Time", da_lyr)
    export(lyt, "01_drive_time_to_hospital")

    # 2. Service areas
    m = new_map(aprx, "Service Areas", outline)
    sa = add(m, str(GDB / "ServiceAreas"), "Drive time from nearest hospital",
             style_service_areas)
    add(m, hosp, "Hospitals", style_hospitals)
    lyt = build_layout(aprx, m, "Hospital drive-time service areas",
                       "Areas reachable within 15, 30, 60 and 90 minutes on the National Road Network",
                       "02 Service Areas", m.listLayers("Saskatchewan")[0])
    export(lyt, "02_service_areas")

    # 3. Hot spots + location-allocation
    m = new_map(aprx, "Hot Spots", outline)
    add(m, str(GDB / "Access_HotSpots"), "Clusters of long drive times (Gi*)", style_hot_spots)
    add(m, hosp, "Hospitals", style_hospitals)
    add(m, str(GDB / "New_Sites_k3"), "Proposed sites", style_new_sites)
    lyt = build_layout(aprx, m, "Where access gaps cluster",
                       "Getis-Ord Gi* hot spots of drive time (FDR-corrected) and the 3 sites that "
                       "add the most people within 30 min",
                       "03 Hot Spots", m.listLayers("Saskatchewan")[0])
    export(lyt, "03_hot_spots_new_sites")

    aprx.save()
    print(f"  saved {aprx_path}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
