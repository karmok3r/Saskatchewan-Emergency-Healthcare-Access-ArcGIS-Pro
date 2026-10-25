# Emergency Healthcare Access in Saskatchewan (ArcGIS Pro + Python)

How long does it take Saskatchewan residents to drive to the nearest hospital emergency department? This project builds a province-wide road network in ArcGIS Pro Network Analyst. It measures drive time from every 2021 census dissemination area to the nearest hospital, tests whether access differs for seniors, Indigenous residents and lower-income areas, maps where poor access clusters, and uses location-allocation to find where new emergency sites would help the most people.

The whole workflow is scripted with **arcpy** and runs from raw open data to finished map layouts in one command.

![Drive time to nearest hospital](maps/01_drive_time_to_hospital.png)

## Research questions
1. What share of Saskatchewan's 1.13 million residents live within 15, 30, 60 and 90 minutes of a hospital?
2. Are seniors (65+), Indigenous residents or lower-income areas more likely to face long drives?
3. Where do areas with long drive times cluster significantly?
4. If the province added 1–3 emergency sites, where would they bring the most people within 30 minutes?

## Key findings
| Drive time to nearest hospital | All residents | Age 65+ | Indigenous identity |
|---|---|---|---|
| ≤ 15 min | 73.8% | 72.1% | 62.4% |
| 15–30 min | 14.8% | 15.8% | 14.6% |
| 30–60 min | 9.3% | 10.9% | 12.9% |
| 60–90 min | 0.8% | 0.5% | 3.8% |
| > 90 min | 1.0% | 0.6% | 4.9% |
| No road connection | 0.3% | 0.1% | 1.3% |

- **88.6% of residents (1.00 million people) live within 30 minutes of a hospital.** About 129,000 people are farther than that.
- **Indigenous residents face the largest gap.** Their population-weighted average drive is 24.0 minutes, against 13.3 minutes for the province overall. They are about 5 times more likely than the average resident to be more than 90 minutes away or have no road connection. Seniors are close to the provincial average.
- **Access follows income.** In the lowest-income fifth of dissemination areas, 14.8% of residents are more than 30 minutes from a hospital. In the highest-income fifth, 0.9% are.
- **Long drive times cluster in the north.** Getis-Ord Gi* (with false discovery rate correction) finds 83 dissemination areas in significant hot spots at 99% confidence, almost all in the Northern Saskatchewan Administration District.
- **New sites would bring modest gains.** Maximize Coverage location-allocation picks Earl Grey, Glen Ewen and Bethune. Together they bring about 14,700 more people within 30 minutes (88.6% → 89.9%). The large northern gaps cannot be closed within a 30-minute standard, because communities there are small and far apart. Those areas need other models, such as air ambulance, nurse-led clinics or a longer service standard.

| Access by population group | Access by household income |
|---|---|
| ![Access by group](figures/access_by_group.png) | ![Access by income](figures/drive_time_by_income.png) |

| Drive-time service areas | Hot spots and proposed sites |
|---|---|
| ![Service areas](maps/02_service_areas.png) | ![Hot spots](maps/03_hot_spots_new_sites.png) |

## Data (all open, Open Government Licence – Canada)
| Layer | Source | Notes |
|---|---|---|
| Hospitals | Statistics Canada, Open Database of Healthcare Facilities (ODHF) v1.1 | 96 records → 70 sites after cleaning |
| Roads | National Road Network (NRN) 15.0, Saskatchewan | 299,096 segments, with speed limit, road class and surface |
| Census areas | 2021 dissemination area boundaries (StatCan ArcGIS REST service) | 2,625 dissemination areas |
| Population | 2021 Census Profile (StatCan SDMX API) | Total, age 65+, Indigenous identity, median household income |

## Method
1. **Clean the hospital list** (`02_prepare_data.py`)
   - Kept ODHF records classed as Hospitals.
   - Removed psychiatric and rehabilitation facilities, and Moose Jaw Union Hospital (replaced by Dr. F.H. Wigmore Regional in 2015).
   - Filled missing coordinates from another record in the same town, or from National Road Network place names.
   - Merged records within 400 m of each other as duplicates.
2. **Calculate drive time on each road segment.** Minutes = length ÷ speed. Speed is the posted NRN limit where present, otherwise a default for the road class. Gravel and dirt roads are slowed by 20%. Winter roads are excluded.
3. **Place demand points where people live.** A large rural dissemination area's centre can fall in empty bush. Each area's point is placed at its densest cluster of local streets instead: the street midpoint with the most other street midpoints within 1.5 km. 2,214 areas use this method; 411 with no local streets keep a geometric interior point.
4. **Build the network dataset** (`03_build_network.py`). arcpy can only create a network with a Length cost. The script exports the network schema to an XML template, adds a `Minutes` cost attribute and a "Driving Time" travel mode, then recreates and builds the network from the edited template. Check: Regina General → Royal University Hospital is 258 km and 155 min.
5. **Find the nearest hospital for every area** (`04_access_analysis.py`). An OD Cost Matrix (`arcpy.nax`) gives each demand point its nearest hospital and drive time. Population is then summed by time band, and population-weighted averages are calculated. Service Area produces 15/30/60/90-minute rings.
6. **Spatial statistics and equity** (`05_hotspots_equity.py`). Hot Spot Analysis (Getis-Ord Gi*) runs on drive time using 8 nearest neighbours, because dissemination areas range from city blocks to thousands of km². False discovery rate correction is applied. Drive time is also summarised by household-income quintile.
7. **Location-allocation** (`06_location_allocation.py`). Maximize Coverage with a 30-minute cutoff. The 70 hospitals are required facilities. The 307 populated dissemination areas currently more than 30 minutes away are candidate sites, and every area is weighted by population. The model is solved for 1, 2 and 3 new sites. The optimal sites are not nested: Silton is best for one site, but Earl Grey and Bethune are best as a pair.
8. **Cartography** (`07_make_maps.py`). `arcpy.mp` builds `SK_Health_Access.aprx` from the blank project that ships with Pro. It creates three maps with symbology and three print layouts (legend, north arrow, scale bar, credits), and exports them to PDF and PNG.

## Reusable geoprocessing tool
`toolbox/HealthAccess.pyt` packages the analysis as an ArcGIS Pro tool called **Nearest Facility Drive-Time Access**. Given any network dataset, travel mode, facilities and population points, it writes drive time and access band to each point and reports the population in each band. It can be re-run for pharmacies, schools or EMS bases. On this project's data it reproduces the script results exactly.

## Limitations
- **Facility list.** ODHF v1.1 was compiled in 2020. Temporary emergency-department closures and staffing disruptions, which have been frequent in rural Saskatchewan, are not modelled, so access in practice is likely worse than shown.
- **Province boundary.** Hospitals in Alberta and Manitoba are excluded, so border communities (e.g. near Flin Flon or Lloydminster's Alberta side) may be overstated as underserved.
- **Northern health centres.** Northern nursing stations and health centres classed as ambulatory care in ODHF are not counted as emergency departments, even though some provide emergency care.
- **Drive times.** These are free-flow: no traffic, weather or seasonal road closures. Ferries and winter roads are excluded.
- **Demand points.** Each dissemination area is represented by one point, which hides variation inside large rural and northern areas.
- **Hot-spot map.** Large northern polygons dominate visually. The finding should be read together with the population tables, not from the area shaded.

## How to run
Requires ArcGIS Pro 3.x with the Network Analyst extension (developed on Pro 3.4, Advanced licence). Close the project in ArcGIS Pro first.

```bash
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" scripts/run_all.py
```

Raw data (~300 MB) is downloaded automatically. The full pipeline takes about 20 minutes. Then open `SK_Health_Access.aprx` in ArcGIS Pro.

## Repository layout
```
scripts/   01–07 pipeline steps, config.py, run_all.py
toolbox/   HealthAccess.pyt (reusable geoprocessing tool)
maps/      exported layouts (PNG, PDF)
figures/   charts
outputs/   cleaned hospital list, per-DA access table, summary tables
data/      raw downloads and file geodatabase (rebuilt by the pipeline, not committed)
```

## Skills demonstrated
ArcGIS Pro · arcpy · Network Analyst (network dataset creation, OD Cost Matrix, Service Area, Location-Allocation) · Spatial Statistics (Getis-Ord Gi*) · `arcpy.mp` cartography automation · Python toolboxes · REST and SDMX APIs · pandas · matplotlib · data cleaning and QA · census and equity analysis

## Author and AI use
Uday Karmoker. The analysis design, code and documentation were developed with help from Claude (Anthropic) as an AI pair programmer. All results were run locally in ArcGIS Pro 3.4 and checked against known values: a provincial population total of 1,132,505, and the Regina–Saskatoon drive time.
