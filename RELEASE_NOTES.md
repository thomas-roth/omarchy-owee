# OWEE 1.3.4

## Readable wind map

The wind map now dims the basemap under the barbs. DWD draws the barbs at a
fixed pixel size, so OWEE requests them at the displayed map size instead of
downscaling them. The strokes keep their full width, and OWEE repaints them in
white so they stand out in every theme. A small badge shows the current city
wind speed and direction.

## Panel fits the page

The popup now sizes itself to the active page instead of using one tall card.
Weather ends after the hourly forecast, so the daily forecast begins below the
fold. Radar ends after the map and its Legend button. The available screen
height still caps the card, and an expanded legend can make the Radar card
taller.

## Refresh beside Settings

A manual refresh icon now sits beside Settings in the fixed panel header.
It is accessible from Weather, Radar, Settings and the city picker, including
when the content is scrolled. The same action is available through keyboard
focus. It uses the existing weather worker and one-minute request limit, and
is disabled while that worker is busy.

The former Settings-only refresh button has moved to the header. Weather
sources, preferences and the selected primary city are unchanged.

## Radar playback at close zoom

Close zoom levels show fewer radar frames, because DWD renders each frame on
its own. The timeline now loads several frames at the same time and checks for
new frames every three seconds. The map opens at the present observation and
stays paused; Space plays forward, and playback continues when more frames
arrive. The play button and the Space key answer as soon as the first frame
appears. When only the present frame is ready, playback waits on it and starts
at the next frame instead of staying disabled.

Plus and minus change the radar zoom level. Radar controls return keyboard
focus to the map, so Space, Left, Right, plus and minus always control the
radar after a click on a zoom, layer, source or timeline control.

## Radar legend and new shortcuts

The radar no longer prints a forecast tag beside the time. A Legend button
replaces the explanatory paragraph and shows the rain scale in dBZ, or the wind
barb scale with speeds in metres per second. The source buttons explain
themselves in tooltips, and the provider line below the map is gone.

Press 1 for Weather and 2 for Radar. R selects rain and W selects wind. The F
shortcut is removed.

## Two-hour nowcast

The DWD timeline now runs two hours each way in five-minute steps: two hours of
observations and two hours of forecast. It holds 49 frames. The warm-up checks
for new frames for up to three minutes at a close zoom. A frame that fails
during the parallel warm-up is retried once with fewer requests. One cold load
asks for about 50 frames, so the local request guard allows the larger burst
that this timeline needs and never records a refused call as a missing frame.

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

- A compact weather symbol and temperature in the Omarchy bar.
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
