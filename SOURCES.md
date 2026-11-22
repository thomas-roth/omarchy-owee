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
| Rain radar | [DWD via Bright Sky](https://brightsky.dev/docs/) in Germany, [RainViewer](https://www.rainviewer.com/api/weather-maps-api.html) elsewhere | Germany: DWD composite at five minute steps, about two hours observed plus about two hours predicted. Worldwide: RainViewer composites at roughly ten minute steps; predictions exist only for part of the world and may be absent. |
| Wind map | [Open-Meteo](https://open-meteo.com/en/docs) | Modelled 10 m wind at fifteen minute steps, about two hours observed plus about two hours predicted, drawn as a vector grid. Forecasts, not observations. |
| Future map | — | The former ECCC GeoMet forecast map was removed; rain predictions stay inside the rain radar timeline and hourly/daily forecasts cover the outlook. |
| Basemap | [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) | ODbL attribution; tile service use follows its [policy](https://operations.osmfoundation.org/policies/tiles/), with at least seven days' cache retention. |

Open-Meteo data attribution follows [CC BY 4.0](https://open-meteo.com/en/licence)
and the [API terms](https://open-meteo.com/en/terms). Current free limits include
600 calls/minute, 5,000/hour and 10,000/day, applied by IP/application. A public
deployment must not treat each installation as an exemption from those terms.
No SLA is provided. Growing or commercial usage needs a separate provider
agreement; OWEE does not silently switch to an undocumented endpoint.

RainViewer attribution is visible in its map; its
[terms](https://www.rainviewer.com/api.html) apply.
German radar imagery is provided by the Deutscher Wetterdienst (DWD) via the
Bright Sky API; DWD radar products are use-restricted to non-commercial purposes.

Network failures, rate limits, stale data, incomplete fields and unsupported
map projections are displayed explicitly. Web Mercator cannot represent the
poles: maps do not silently shift the requested point to a different latitude.

The visual language was inspired by Pixel Weather. Icons and UI code in this
repository are original or derived from Omarchy's MIT toolkit. OWEE is an
independent community plugin, not an official Google or Omarchy product.
