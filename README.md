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
  the condition, with the temperature always visible in the bar.
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
| **Bar** | The primary city's condition and temperature at a glance. |
| **Now** | Modelled current conditions, feels-like temperature and today's Low/High. |
| **Hourly** | How temperatures and rain/snow probabilities change over the next hours. |
| **Daily** | Each day's conditions and the times when precipitation may occur. |
| **Measurements** | Wind, humidity, UV, solar events, pressure, visibility and optional air/pollen data. |
| **Radar** | Rain nowcast from the past two hours into the next two hours, and the hourly wind forecast. |

**Two rain sources and one wind source.** Auto uses the DWD German composite
inside Germany and RainViewer elsewhere. Choose Auto, RainViewer or DWD in the
Radar view. DWD shows the last two hours of observations and a two-hour nowcast
in five-minute steps. RainViewer shows two hours of observations in ten-minute
steps and has no nowcast. The Wind layer uses DWD ICON on a 2.5 km grid, hourly
for the next twelve hours, and covers Germany.

**One nowcast timeline.** The map opens at the present time and stays paused.
Press Space to play forward from the present frame into the future forecast; it
stops at the last frame. Left and Right step one frame at a time. DWD renders
each radar frame separately, so a close zoom can take a few seconds to fill the
timeline. The play button works as soon as the first frame appears: if only the
present frame is ready, it waits and starts when the next frame arrives. The
warm-up retries a frame that fails and renders several frames at the same time.
Playback continues when more frames arrive.

**Zoom follows the source.** The zoom buttons, and the plus and minus keys,
reach level 10 with DWD in Germany, about 40 km across, which is close to the
1 km radar resolution. RainViewer stops at level 7, because it does not publish
closer radar tiles.

**The card fits the page.** The popup ends after the hourly forecast on Weather
and after the map on Radar. The daily forecast stays below the fold and scrolls
into view. The available screen height caps the card, and an expanded legend can
make the Radar card taller.

**The wind map stays readable.** DWD draws the wind barbs at a fixed pixel size.
OWEE requests them at the displayed map size, so each stroke keeps its full
width. The basemap dims under the barbs, and the barbs are stored in white, so
they stand out in every theme. A small badge shows the current city wind speed
and direction while the wind layer is open.

## Keyboard shortcuts

These shortcuts work while the panel is open.

| Key | Action |
| --- | --- |
| 1 | Weather tab |
| 2 | Radar tab |
| R | Radar with the rain layer |
| W | Radar with the wind layer |
| Space | Play or pause the animation |
| Left / Right | Previous or next frame |
| + / − | Zoom the radar in or out |

The map keeps focus when you open it. Buttons and the timeline return focus to
the map after a click, so Space, Left, Right, plus and minus always control the
radar. When a text field has focus, keys type into the field instead of
changing the tab.

Press **Legend** below the timeline to show the colour scale in dBZ for rain,
or the barb scale with speeds in metres per second for wind. The rain scale
follows the DWD ranges.

**The blue bars represent probability.** In the daily view, brighter blue means
higher rain/snow chance, grey means zero, and an outline means no hourly data.
Hover, click, or use Tab and arrow keys to read the precise interval. A provider
probability covers the hour ending at its timestamp; OWEE labels that interval.

**Times follow the selected city.** Repeated daylight-saving hours retain both
UTC periods, skipped hours are identified, and polar day/night are explicit.
The daily rain axis stays 00:00–24:00 even when using system display formats.

**Favorites are one click away.** Saved cities sit beside Weather and Radar.
Click a city to view it immediately; Radar stays open when switching locations.
Scroll the strip for more cities or use Tab to reach them. The highlighted city
is the one being viewed; the star marks the city used by the bar and notifications.

**Browsing does not change your bar city.** Search updates as you type; enter a
city or decimal `latitude, longitude`, such as `27.7172, 85.3240`. Favorites keep
places close. **Use in bar**, beside the bar-city label, makes the viewed city primary for both
the bar and notifications.

**Coverage is visible.** Radar coverage masks distinguish missing observations
from dry conditions. RainViewer supplies a coverage mask; the DWD composite
covers Germany and shows no separate mask. Air and pollen vary by region;
unavailable values do not become zero. The radar is opt-in, stops when hidden and
explain projection limits near the poles. The rain nowcast combines two hours of
observed frames with a two-hour forecast; the wind layer is a model forecast.

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
