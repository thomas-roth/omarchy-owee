# OWEE 1.4.0

## Rain and wind radars with past and future in one timeline

The Maps register becomes **Radars** with two pages: Rain and Wind. The
former forecast map page is gone. Each radar covers two hours before and two
hours after now in a single timeline that opens on the latest observation.
The mark on the timeline separates observed frames from predictions, and
frames carry their distance from now.

In Germany the rain radar uses the DWD composite through Bright Sky at five
minute steps, with the model's prediction attached. Elsewhere it uses
RainViewer's worldwide feed at roughly ten minute steps; predictions exist
only for part of the world and may be absent there. The wind map draws
Open-Meteo's modelled 10 m wind as a moving vector field at fifteen minute
steps over the same window.

Frames stream in newest-first, so the current conditions paint before the
rest of the timeline. Basemap tiles and radar images are cached; a repeat
visit is instant. A cold first load can take a minute while the DWD service
renders each requested timestep; frames appear as they finish. Zoom follows
the previous radar's model (default level 1, levels −2 to 3).

**New keybinds in the Radars register:** `1`/`2` switch Weather and Radars,
`R`/`W` switch the rain radar and wind map, `L` toggles the legend,
`Space` plays or pauses, `←`/`→`
step one frame, `+`/`−` zoom. The same actions remain available as on-screen
controls. Frames whose imagery cannot be
fetched do not blank the map; the view falls back to the nearest complete
frame and explains what happened. The old radar coverage masks are gone; the
rain overlay itself shows where observations exist.

**Readable maps:** a `Legend` toggle on each radar explains its colour scale
in real units — rain intensity in mm/h on the DWD composite scale (three
compact columns), wind arrows in km/h. The legend stays hidden whenever the
popup opens. The rain timeline's "now" snaps to the five minute grid so step
leads read 5, 10, 15 minutes; the wind map's frames sit on the wall-clock 15
minute grid and its timeline opens on a frame that reads "now". `Space` always
plays or pauses the radar while the register is open, even when a control such
as the legend toggle was the last thing clicked. The basemap is dimmed a
little in rain mode and more strongly in wind mode, where particles and
arrows are also drawn thicker, so the overlays read clearly. The date and
time sit between the two radar control button groups; the frame's distance
from now is centered below the timeline, always shown in full.
The OpenStreetMap attribution is
smaller and sits unobtrusively on the imagery. A zoom step into an area whose
map tiles are not cached yet may briefly outpace the shared per-minute
download budget; the newest frames still paint first and the radar completes
the remaining ones on its own about a minute later, so it recovers without a
reopen. The popup height now follows
the active view: the weather register keeps the previous height as the
maximum, and the radars page ends just below the radar and timeline, growing
only when the legend is shown.

---

# OWEE 1.3.4

## Refresh beside Settings

A manual refresh icon now sits beside Settings in the fixed panel header.
It is accessible from Weather, Maps, Settings and the city picker, including
when the content is scrolled. The same action is available through keyboard
focus. It uses the existing weather worker and one-minute request limit, and
is disabled while that worker is busy.

The former Settings-only refresh button has moved to the header. Weather
sources, preferences and the selected primary city are unchanged.

The incomplete endurance qualification documented for 1.3.0 remains incomplete;
this update does not claim a new twelve-hour run.

---

# OWEE 1.3.3

## Favorite cities in the navigation

Saved cities are available directly beside Weather and Maps. One click changes
the viewed city, with the current city highlighted and the bar city marked by a
star. Switching cities on Maps keeps the map page open. Choosing the current
city does not trigger another request.

The favorites strip scrolls when needed and reveals focused cities during
keyboard navigation. Long names remain bounded and their full label is available
in the tooltip. Cities still manages search, favorites, order and removal.

The separate Use in bar action sits beside the bar-city label. Viewing a favorite
keeps the bar and notification city unchanged until that action is chosen.

---

# OWEE 1.3.2

## Softer forecast panels

Hourly and daily forecasts now sit on a shared, quiet surface derived from the
active Omarchy theme. A subtle vertical tint, fine border and interior spacing
separate the forecasts from the main background and soften their contrast.

---

# OWEE 1.3.1

## Marketplace compatibility

The marketplace accepts `left`, `center` or `right` for
`barWidget.defaultSection`. Version 1.3.0 used `centerBegin`, which the local
shell accepted but the marketplace rejected. The manifest now uses `center`;
the native installer routes that choice beside the clock. Existing widget
placement is preserved.

A regression test now checks that the manifest uses the portable marketplace
contract. Validation includes the marketplace's own manifest validator and the
native runtime/UI gates. This patch changes the manifest and version labels,
without changing weather data, preferences or application behavior.

The incomplete endurance qualification documented for 1.3.0 below remains
incomplete; this metadata patch does not claim a new twelve-hour run.

---

# OWEE 1.3.0

Released as stable by maintainer decision on 16 November 2026.

## Features

- A compact weather symbol in the Omarchy bar; hovering the widget shows
  "Weather: x°C, feels y°C".
- Separate primary and viewed cities, favorites and coordinate search.
- Hourly forecasts and daily local-time precipitation timelines.
- Animated historical radar, coverage masks and on-demand forecast maps.
- Configurable measurement cards and opt-in notifications with quiet hours.
- Coordinated opening motion, native widget preferences and optional system formats.

## Validation and explicit release exception

The candidate passed 164 Python tests, native QML/runtime/UI checks, formatting,
motion and preference migration tests at 100% and 150% scaling, and bounded live
checks for twelve international locations and seven map cases. Stable metadata
is revalidated before the stable commit and tag are created.

The twelve-hour endurance run on candidate 1.3.0-rc.3 completed 458 cycles over
5 h 05 min before the desktop session closed during system power-off at 01:38
Europe/Paris on 16 November 2026. Average closed-panel CPU was about 0.005% of one
core; the final sampled memory remained below the configured allowance.
The report is failed/incomplete, not a passed twelve-hour qualification.

The maintainer explicitly requested stable promotion and publication without
repeating that run. This release records that exception; it does not change the
automatic release gate or fabricate additional runtime evidence. Other release
checks remain mandatory. No zero-bug or forecast-accuracy guarantee is made.

## Known limits

Data availability depends on public providers and regional coverage. Air/pollen
may be unavailable. Web Mercator maps cannot display the poles. Optional maps
and notifications are disabled until enabled. An uncertain notification delivery
is not retried for the same signature, so a system failure can lose an alert.
