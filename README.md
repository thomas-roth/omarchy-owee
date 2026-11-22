<div align="center">

# OWEE

**Omarchy Weather Enhanced Experience**

Pixel Weather clarity. Omarchy character.

[![Checks](https://github.com/Plapie690/omarchy-owee/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Plapie690/omarchy-owee/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-9aa5ce?style=flat-square)](LICENSE)
[![Made for Omarchy](https://img.shields.io/badge/made_for-Omarchy-7aa2f7?style=flat-square)](https://omarchy.org)

[The idea](#the-idea) · [A closer look](#a-closer-look) · [Install](#install) · [Reading the weather](#reading-the-weather) · [Data & privacy](#data-and-privacy)

<img src="preview.png" width="960" alt="OWEE — Weather for Omarchy: an expressive weather symbol beside the current conditions, favorite cities and hourly forecast interface">

<sub>Promotional artwork based on the sample-data interface. Actual plugin screenshots below.</sub>

</div>

## The idea

I wanted checking the weather to feel useful and pleasant: a small, expressive
widget in the bar, and a clear forecast when you open it. The starting point was
the clarity and playful atmosphere of Pixel Weather, brought into Omarchy's
colors, typography and desktop controls. Omarchy's native World Clock was also
a reference for coordinated motion and integration with the shell.

The project grew through everyday questions: *What is it like outside? When
might it rain? What do these bars actually tell me?* Those questions shaped the
interface, from the custom weather symbol to the hourly rain timelines.

The design follows a few simple principles:

- **Recognize the weather immediately.** Distinctive weather marks communicate
  the condition, with the icon alone in the bar; the tooltip names the
  temperature and the felt temperature.
- **Give each graphic a purpose.** Temperatures have explicit Low/High labels.
  Daily precipitation uses a 00:00–24:00 timeline so you can locate likely rain
  periods directly.
- **Make motion feel connected.** The weather illustration and forecast sections
  share a short opening progression. Weather movement stays active while viewed;
  closing the panel stops it. Reduced motion follows Omarchy.
- **Keep the desktop familiar.** Theme colors, type, spacing and controls follow
  Omarchy. Optional system formats adapt dates, numbers and temperature units.
- **Let the view fit the person.** Reorder measurement cards, hide what you do
  not need, save favorite cities and choose the city shown in the bar.
- **Be clear about uncertainty.** Forecast, observed radar, cached data and
  unavailable information have distinct labels. Missing data remains missing.

## A closer look

Captures show the actual plugin interface with illustrative sample data.
They demonstrate the layout and interactions, rather than a live forecast.

<p align="center">
  <img src="assets/screenshots/overview.png" width="360" alt="Actual OWEE overview: favorite-city navigation, current conditions, weather illustration and hourly precipitation forecasts">
</p>

<table>
  <tr>
    <td align="center" width="50%">
      <strong>When might it rain?</strong><br>
      <sub>Daily forecasts with local-time precipitation timelines.</sub><br><br>
      <img src="assets/screenshots/daily.png" width="300" alt="Daily weather: low and high temperatures and individual hourly rain-probability bars from midnight to midnight">
    </td>
    <td align="center" width="50%">
      <strong>Measurements with context</strong><br>
      <sub>Readable values, units and purpose-built visual indicators.</sub><br><br>
      <img src="assets/screenshots/measurements.png" width="300" alt="Measurement cards for wind, humidity, UV, sunrise and sunset, pressure and visibility">
    </td>
  </tr>
  <tr>
    <td align="center">
      <strong>Explore without losing your home weather</strong><br>
      <sub>The viewed city and the bar's primary city are separate choices.</sub><br><br>
      <img src="assets/screenshots/cities.png" width="300" alt="City picker with live search, coordinate input, favorites and a primary-city star">
    </td>
    <td align="center">
      <strong>Your cards, your order</strong><br>
      <sub>Drag to reorder measurements and choose which cards stay visible.</sub><br><br>
      <img src="assets/screenshots/customize.png" width="300" alt="Card customization with drag handles, visibility controls and measurement cards">
    </td>
  </tr>
</table>

<details>
<summary><strong>Settings and notification controls</strong></summary>
<br>
<p align="center">
  <img src="assets/screenshots/settings.png" width="360" alt="Settings for automatic refresh, system or manual temperature units, date and number formats, cards and optional notifications">
</p>

The interface stays in English. Select **System** to follow your desktop's
measurement system or date and number formats. Manual Celsius/Fahrenheit choices
remain available. Notifications are opt-in and support thresholds, quiet hours
and a daily summary.

</details>

## Install

```sh
omarchy plugin add https://github.com/Plapie690/omarchy-owee.git --enable
```

Update:

```sh
omarchy plugin update owee.weather
```

Remove:

```sh
omarchy plugin remove owee.weather
```

Removing the plugin keeps your saved preferences and cached forecasts.
Data locations are documented in [PRIVACY.md](PRIVACY.md).

**Requirements:** Omarchy Quattro with Qt 6.12 and Python 3.12+
with IANA tzdata. Optional notifications use `notify-send`.

No API key, account, subscription or third-party Python runtime package is needed.

## Reading the weather

| View | What it helps you understand |
| --- | --- |
| **Bar** | The primary city's condition icon; hover shows temperature and felt temperature. |
| **Now** | Modelled current conditions, feels-like temperature and today's Low/High. |
| **Hourly** | How temperatures and rain/snow probabilities change over the next hours. |
| **Daily** | Each day's conditions and the times when precipitation may occur. |
| **Measurements** | Wind, humidity, UV, solar events, pressure, visibility and optional air/pollen data; unavailable values never become zero. |
| **Past rain / Radar** | Observed and predicted precipitation at five minute steps (DWD in Germany) or roughly ten minute steps worldwide. |
| **Wind** | Modelled wind as a moving vector field at fifteen minute steps, from two hours before to two hours after now. |

**Radar keybinds.** In the Radars register: `1` and `2` switch Weather and
Radars, `R` and `W` switch the rain radar and wind map, `L` toggles the
legend, `Space` plays or pauses
the timeline and does nothing else while the register is open, `←`/`→` step
one frame, and `+`/`−` zoom the map. The timeline opens on the latest
observation, snapped to the five minute grid; the marker on the bar separates
observed frames from predictions. The date and time sit between the two radar
control button groups, and the frame's distance from now ("now", "+25 min",
"+1 h 55 min") is centered below the timeline on the source line — always
shown in full.
A `Legend` toggle explains the colour
scales — rain intensity in mm/h (the DWD composite scale), wind arrows in
km/h. It stays hidden whenever the popup is opened, and the popup height
follows the radars view so it ends just below the radar and timeline, growing
only when the legend is shown.

**Map readability.** The basemap is dimmed — a little in rain mode, more in
wind mode — so the radar colours and the wind vector field stand out. Zooming
to a fresh zoom level needs more map tiles than the shared download budget
allows in one minute; the newest frames paint first and the radar quietly
completes the remaining frames about a minute later on its own, so a cold
zoom step no longer stays empty until the panel is reopened. The
date and time sit between the two radar control button groups; the frame's
distance from now is centered below the timeline, always shown in full.

**The blue bars represent probability.** In the daily view, brighter blue means
higher rain/snow chance, grey means zero, and an outline means no hourly data.
Hover, click, or use Tab and arrow keys to read the precise interval. A provider
probability covers the hour ending at its timestamp; OWEE labels that interval.

**Times follow the selected city.** Repeated daylight-saving hours retain both
UTC periods, skipped hours are identified, and polar day/night are explicit.
The daily rain axis stays 00:00–24:00 even when using system display formats.

**Favorites are one click away.** Saved cities sit beside Weather and Radars.
Click a city to view it immediately; the Radars page stays open when switching
locations.
Scroll the strip for more cities or use Tab to reach them. The highlighted city
is the one being viewed; the star marks the city used by the bar and notifications.

**Browsing does not change your bar city.** Search updates as you type; enter a
city or decimal `latitude, longitude`, such as `27.7172, 85.3240`. Favorites keep
places close. **Use in bar**, beside the bar-city label, makes the viewed city primary for both
the bar and notifications.

**One radar per metric.** The rain radar shows observed precipitation followed
by the model prediction in a single timeline; DWD covers Germany at five minute
steps, RainViewer covers the world at roughly ten minute steps. The wind map
animates Open-Meteo's modelled wind. Maps are opt-in, stop when hidden and
explain projection limits near the poles. Rain shows model predictions after
the observed frames; wind is always modelled.

**Notifications stay under your control.** Quiet hours and the daily summary
follow the desktop clock; weather intervals follow the primary city's timezone.
Stale data does not trigger automatic alerts. Do Not Disturb takes priority.
Notifications are informational, not official weather warnings.

## Data and privacy

OWEE fetches forecasts directly from public weather providers. No account,
API key or telemetry is required. Your favorites, preferences and cached
forecasts stay on your computer. See [Privacy](PRIVACY.md) for details.

Forecasts refresh every fifteen minutes. Click the refresh icon beside Settings
to refresh manually, at most once per minute. The button stays accessible while
you browse the panel and is disabled during loading. Cached forecasts remain
readable offline and are clearly marked when out of date.

Public providers have their own terms, regional coverage and availability limits.
Code is MIT; data and imagery have separate licenses and attribution requirements.

---

[Sources & data terms](SOURCES.md) · [Privacy](PRIVACY.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Release notes](RELEASE_NOTES.md) · [MIT license](LICENSE)

An independent community project by Paul. Pixel Weather inspired the visual
direction; OWEE is not affiliated with Google or the Omarchy team.
