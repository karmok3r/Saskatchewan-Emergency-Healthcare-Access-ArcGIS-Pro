"""Add a 'City Access' map and layout to SK_Health_Access.aprx and export one map per city.

A single layout is reused for every city (like a map series): the script moves the
map frame to each city's boundary, updates the title, and exports PNG + PDF to maps/cities/.
Run after 07_make_maps.py (which creates the project) and 08_city_analysis.py.
"""
import importlib
import sys
from pathlib import Path

import arcpy
import pandas as pd

from config import APRX, CITY_BREAKS, GDB, MAPS, OUTPUTS

maps07 = importlib.import_module("07_make_maps")
rgb, clear_heading = maps07.rgb, maps07.clear_heading

arcpy.env.overwriteOutput = True
CITY_DIR = MAPS / "cities"
BLUES = ["#cde2fb", "#86b6ef", "#3987e5", "#0d366b"]
PAGE_W, PAGE_H = 11.0, 8.5


def style_city_drive(lyr):
    sym = lyr.symbology
    sym.updateRenderer("GraduatedColorsRenderer")
    r = sym.renderer
    r.classificationField = "DRIVE_MIN"
    r.breakCount = len(BLUES)
    for brk, upper in zip(r.classBreaks, CITY_BREAKS + [1000]):
        brk.upperBound = upper
    lyr.symbology = sym
    sym = lyr.symbology
    for brk, color in zip(sym.renderer.classBreaks, BLUES):
        brk.symbol.color = rgb(color)
        brk.symbol.outlineColor = rgb("#ffffff", 60)
        brk.symbol.outlineWidth = 0.3
    lyr.symbology = sym
    labels = ([f"≤ {CITY_BREAKS[0]} min"]
              + [f"{a}–{b} min" for a, b in zip(CITY_BREAKS, CITY_BREAKS[1:])]
              + [f"> {CITY_BREAKS[-1]} min"])
    cim = lyr.getDefinition("V3")
    for brk, label in zip(cim.renderer.breaks, labels):
        brk.label = label
    lyr.setDefinition(cim)
    clear_heading(lyr)


def style_outline(lyr, color, width, label):
    sym = lyr.symbology
    sym.renderer.symbol.color = {"RGB": [0, 0, 0, 0]}
    sym.renderer.symbol.outlineColor = rgb(color)
    sym.renderer.symbol.outlineWidth = width
    sym.renderer.label = label
    lyr.symbology = sym


def style_eds(lyr):
    maps07.style_hospitals(lyr)
    sym = lyr.symbology
    sym.renderer.symbol.size = 11
    sym.renderer.label = "Emergency department"
    lyr.symbology = sym
    lyr.showLabels = True
    lbl = lyr.listLabelClasses()[0]
    lbl.expressionEngine = "Arcade"
    lbl.expression = "$feature.facility_name"
    cim = lyr.getDefinition("V3")
    text = cim.labelClasses[0].textSymbol.symbol
    text.height = 9
    text.haloSize = 1.5
    text.haloSymbol = arcpy.cim.CreateCIMObjectFromClassName("CIMPolygonSymbol", "V3")
    text.haloSymbol.symbolLayers = [arcpy.cim.CreateCIMObjectFromClassName("CIMSolidFill", "V3")]
    text.haloSymbol.symbolLayers[0].color = arcpy.cim.CreateCIMObjectFromClassName("CIMRGBColor", "V3")
    text.haloSymbol.symbolLayers[0].color.values = [255, 255, 255, 100]
    lyr.setDefinition(cim)


def city_extents():
    out = {}
    with arcpy.da.SearchCursor(str(GDB / "Cities"), ["CITY", "SHAPE@"],
                               spatial_reference=maps07.MAP_SR) as cur:
        for city, shape in cur:
            out[city] = shape.extent
    return out


def build(aprx):
    for m in aprx.listMaps("City Access"):
        aprx.deleteItem(m)
    for lyt in aprx.listLayouts("City Access"):
        aprx.deleteItem(lyt)

    m = aprx.createMap("City Access", "MAP")
    m.spatialReference = maps07.MAP_SR
    for lyr in m.listLayers():
        m.removeLayer(lyr)
    try:  # basemap needs an internet connection and is optional
        m.addBasemap("Light Gray Canvas")
    except Exception as e:
        print(f"  basemap skipped: {e}")

    das = m.addDataFromPath(str(GDB / "DA_Polygons"))
    das.name = "Drive time to nearest ED"
    das.definitionQuery = "CITY IS NOT NULL AND DRIVE_MIN IS NOT NULL"
    das.transparency = 15
    style_city_drive(das)
    catch = m.addDataFromPath(str(GDB / "City_Catchments"))
    catch.name = "ED catchment"
    style_outline(catch, "#0b0b0b", 1.6, "ED catchment boundary")
    city = m.addDataFromPath(str(GDB / "Cities"))
    city.name = "City limits"
    style_outline(city, "#d03b3b", 1.0, "City limits (2021 CSD)")
    eds = m.addDataFromPath(str(GDB / "Hospitals"))
    eds.name = "Emergency departments"
    style_eds(eds)

    lyt = aprx.createLayout(PAGE_W, PAGE_H, "INCH", "City Access")
    mf = lyt.createMapFrame(arcpy.Extent(0.35, 0.9, 7.85, 7.55), m, "Map Frame")
    aprx.createTextElement(lyt, arcpy.Point(0.4, 8.05), "POINT", "City", 20, name="Title")
    aprx.createTextElement(lyt, arcpy.Point(0.4, 7.72), "POINT", "Subtitle", 10, name="Subtitle")
    legend = lyt.createMapSurroundElement(arcpy.Point(8.1, 7.55), "LEGEND", mf, name="Legend")
    legend.elementWidth = 2.6
    legend.title = ""
    for item in legend.items:
        if item.name not in ("Drive time to nearest ED", "ED catchment", "City limits",
                             "Emergency departments"):
            item.visible = False
    cim = lyt.getDefinition("V3")
    for el in cim.elements:
        if type(el).__name__ == "CIMLegend":
            for item in el.items:
                item.showHeading = False
    lyt.setDefinition(cim)
    north = aprx.listStyleItems("ArcGIS 2D", "NORTH_ARROW", "ArcGIS North 1")[0]
    na = lyt.createMapSurroundElement(arcpy.Point(8.3, 2.3), "NORTH_ARROW", mf, north)
    na.elementHeight = 0.5
    bar = aprx.listStyleItems("ArcGIS 2D", "SCALE_BAR", "Scale Line 1 Metric")
    sb = lyt.createMapSurroundElement(arcpy.Point(8.1, 1.5), "SCALE_BAR", mf,
                                      bar[0] if bar else None)
    sb.elementWidth = 2.4
    aprx.createTextElement(lyt, arcpy.Point(8.1, 3.3), "POINT", "Stats", 8.5, name="Stats")
    aprx.createTextElement(lyt, arcpy.Point(0.4, 0.55), "POINT", maps07.SOURCES
                           + " Basemap: Esri Light Gray Canvas.", 7, name="Credits")
    return lyt, mf


def export_cities(lyt, mf):
    summary = pd.read_csv(OUTPUTS / "city_summary.csv").set_index("city")
    scen = pd.read_csv(OUTPUTS / "city_closure_scenarios.csv")
    title = lyt.listElements("TEXT_ELEMENT", "Title")[0]
    subtitle = lyt.listElements("TEXT_ELEMENT", "Subtitle")[0]
    stats = lyt.listElements("TEXT_ELEMENT", "Stats")[0]
    CITY_DIR.mkdir(parents=True, exist_ok=True)
    for city, ext in city_extents().items():
        s = summary.loc[city]
        worst = scen[scen["city"] == city].sort_values("mean_added_min_displaced").iloc[-1]
        title.text = f"{city}: drive time to the nearest emergency department"
        subtitle.text = (f"{s.population:,.0f} residents · {int(s.emergency_departments)} ED"
                         f"{'s' if s.emergency_departments > 1 else ''} · population-weighted "
                         f"mean {s.mean_drive_min} min")
        stats.text = (f"Within 5 min: {s['pct_<= 5 min']}% of residents\n"
                      f"If {worst.ed_closed} closed:\n"
                      f"  +{worst.mean_added_min_displaced} min for "
                      f"{worst.residents_displaced:,.0f} residents")
        pad_x, pad_y = (ext.XMax - ext.XMin) * 0.06, (ext.YMax - ext.YMin) * 0.06
        mf.camera.setExtent(arcpy.Extent(ext.XMin - pad_x, ext.YMin - pad_y,
                                         ext.XMax + pad_x, ext.YMax + pad_y))
        stem = city.lower().replace(" ", "_")
        lyt.exportToPNG(str(CITY_DIR / f"{stem}.png"), resolution=200)
        lyt.exportToPDF(str(CITY_DIR / f"{stem}.pdf"), resolution=300)
        print(f"  exported maps/cities/{stem}.png/.pdf")


def main(aprx_path=APRX):
    try:
        aprx = arcpy.mp.ArcGISProject(str(aprx_path))
        lyt, mf = build(aprx)
        export_cities(lyt, mf)
        aprx.save()
    except OSError as e:
        sys.exit(f"Could not update {Path(aprx_path).name} (is it open in ArcGIS Pro?): {e}")
    print(f"  saved {Path(aprx_path).name}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
