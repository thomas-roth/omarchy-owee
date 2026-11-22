# Sources, coverage and attribution

OWEE code is MIT licensed. Data and API access have separate conditions.
No key is embedded or requested. This release uses the providers' free public
services for non-commercial desktop/community use, within their limits; it is
not a promise of unlimited traffic or guaranteed uptime.

| Feature | Source | Coverage and limits |
| --- | --- | --- |
| Weather and forecasts | [Open-Meteo](https://open-meteo.com/en/docs) | Global best-match numerical models. Modelled conditions, not a claim of an observation station at each point. |
| City search | [Open-Meteo / GeoNames](https://open-meteo.com/en/docs/geocoding-api) | Gazetteer locations; coordinates work without a named city. |
| Air and pollen | [CAMS ENSEMBLE via Open-Meteo](https://open-meteo.com/en/docs/air-quality-api) | Global and European air models have different resolution. Pollen is regional/seasonal, currently European; null is never zero. European AQI is explicitly named. |
| Observed past rain | [RainViewer](https://www.rainviewer.com/api/weather-maps-api.html) | Two hours of past radar frames at ten-minute steps, and the official coverage mask. This API publishes no future frames, so RainViewer shows observations only. Coverage is not universal. Unknown coverage is not dry weather. Weather data by RainViewer. |
| Observed past rain and near forecast (Germany) | [DWD GeoServer](https://maps.dwd.de/geoserver/dwd/wms) | Radar composite for Germany. The analysis layer has two hours of observed frames; the product layer has a two-hour forecast. Both use five-minute steps. Use follows the [DWD terms](https://www.dwd.de/EN/). |
| Wind forecast (Germany) | [DWD ICON via GeoServer](https://maps.dwd.de/geoserver/dwd/wms) | Wind barbs at 10 m on a 2.5 km grid, hourly for the next twelve hours. Requested at the displayed map size so the strokes stay readable. A model forecast, not an observation. |
| Basemap | [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) | ODbL attribution; tile service use follows its [policy](https://operations.osmfoundation.org/policies/tiles/), with at least seven days' cache retention. |

Open-Meteo data attribution follows [CC BY 4.0](https://open-meteo.com/en/licence)
and the [API terms](https://open-meteo.com/en/terms). Current free limits include
600 calls/minute, 5,000/hour and 10,000/day, applied by IP/application. A public
deployment must not treat each installation as an exemption from those terms.
No SLA is provided. Growing or commercial usage needs a separate provider
agreement; OWEE does not silently switch to an undocumented endpoint.

RainViewer attribution is visible in its map; its
[terms](https://www.rainviewer.com/api.html) apply. DWD radar and ICON wind
imagery are a service of the Deutscher Wetterdienst; its terms are documented
here and in the README. The rain legend colour scale is composed from the public
DWD WMS legend graphic.

Network failures, rate limits, stale data, incomplete fields and unsupported
map projections are displayed explicitly. Web Mercator cannot represent the
poles: maps do not silently shift the requested point to a different latitude.

The visual language was inspired by Pixel Weather. Icons and UI code in this
repository are original or derived from Omarchy's MIT toolkit. OWEE is an
independent community plugin, not an official Google or Omarchy product.
