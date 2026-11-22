# Privacy

OWEE has no account, advertising, analytics, telemetry or central proxy.
Locations and preferences stay in the legacy-compatible
`${XDG_STATE_HOME:-~/.local/state}/pixel-weather/` directory. Map images stay in
`${XDG_CACHE_HOME:-~/.cache}/pixel-weather/`. No GPS location is requested.

City searches go directly to Open-Meteo's geocoding service. Selected coordinates
go to Open-Meteo for weather and CAMS forecasts. These providers also receive the
network IP address. Manual coordinates bypass city geocoding.

RainViewer, DWD and OpenStreetMap receive the selected map area only
after that map is enabled and visible. Closing or leaving its page stops map
workers and playback. Radar coverage masks are downloaded alongside radar data.
Weather for the bar refreshes every 15 minutes when automatic refresh is enabled.
The viewed location is refreshed when needed; optional air/pollen has a one-hour
cache and its own worker. Disabling automatic refresh pauses automatic rules;
explicit user actions may still contact providers.

Notifications stay local and are disabled initially. Summary and quiet-hour
schedules use the desktop clock; forecast periods and maps use the selected
location's IANA timezone. Omarchy Do Not Disturb takes priority.

Reports produced by `qa/` use public fixture locations, not personal settings.
Do not attach your settings files, exact private coordinates, or complete desktop
screenshots to a public issue. There is no automatic report upload.

Removing the plugin through Omarchy removes its installed code. Preferences and
caches are retained for reinstall; removing the two directories above deletes
them explicitly. Backups made by the migration tools remain until you remove
them yourself.
