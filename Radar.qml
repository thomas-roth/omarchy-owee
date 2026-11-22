import QtQuick
import QtQuick.Controls
import Quickshell.Io
import qs.Commons as Commons
import qs.Ui as Ui

Rectangle {
  id: root
  property var formats: null
  property var city: ({})
  property bool active: false
  // One radar per metric; each spans two hours before and after now.
  property string mode: "rain"
  property int zoomLevel: 1
  property bool settingsLoaded: false
  property var radar: ({})
  property var rainData: ({})
  property var windData: ({})
  property int frameIndex: 0
  property bool playing: false
  // A cold zoom step needs more map tiles than the shared download budget
  // allows in one minute; the newest frames paint first and these retries
  // quietly complete the rest of the cache while the popup stays open.
  property int retryCredits: 3
  property string message: ""
  property var pending: null
  property bool rainEnabled: true
  property bool windEnabled: true
  // Emitted when the in-map Rain/Wind switch is pressed; the panel owns the
  // mode (keybinds and the opening reset both write it).
  signal modeRequested(string requested)
  property bool imageFault: false
  property bool legendVisible: true
  readonly property bool modeEnabled: mode === "wind" ? windEnabled : rainEnabled
  readonly property var rain: rainData
  readonly property var wind: windData
  readonly property var sequence: mode === "wind" ? wind : rain
  readonly property var frames: Array.isArray(sequence.frames) ? sequence.frames : []
  readonly property int frameCount: frames.length
  readonly property int nowIndex: typeIsNumber(sequence.now_index) ? sequence.now_index : -1
  readonly property var currentFrame: frameIndex >= 0 && frameIndex < frameCount ? frames[frameIndex] : null
  function frameHasImages(index) {
    var frame = frames[index]
    return !!frame && Array.isArray(frame.tiles) && frame.tiles.length > 0
      && frame.tiles.every(function(tile) { return typeof tile.source === "string" && tile.source !== "" })
  }
  // Frames whose imagery could not be fetched do not blank the map: the view
  // falls back to the nearest frame that did load, preferring the past.
  readonly property int displayIndex: {
    if (mode === "wind") return frameIndex
    if (frameIndex >= 0 && frameIndex < frameCount && frameHasImages(frameIndex)) return frameIndex
    for (var distance = 1; distance < frameCount; ++distance) {
      if (frameIndex - distance >= 0 && frameHasImages(frameIndex - distance)) return frameIndex - distance
      if (frameIndex + distance < frameCount && frameHasImages(frameIndex + distance)) return frameIndex + distance
    }
    return -1
  }
  readonly property var displayFrame: displayIndex >= 0 && displayIndex < frameCount ? frames[displayIndex] : null
  readonly property bool imageReady: mode === "wind"
    ? !!currentFrame && Array.isArray(currentFrame.points) && currentFrame.points.length > 0
    : !!displayFrame && Array.isArray(displayFrame.tiles) && displayFrame.tiles.length > 0
      && displayFrame.tiles.every(function(tile) { return typeof tile.source === "string" && tile.source !== "" })
  readonly property bool unsupported: radar.status === "unsupported" && radar.reason === "projection_limit"
  readonly property var tiles: Array.isArray(radar.tiles) ? radar.tiles : []
  readonly property bool busy: worker.running
  readonly property string cityKey: city && isFinite(city.latitude) && isFinite(city.longitude) ? Number(city.latitude).toFixed(5) + "," + Number(city.longitude).toFixed(5) : ""
  readonly property color muted: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.72)
  readonly property color soft: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.075)
  readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("radar.py").toString().replace(/^file:\/\//, ""))
  readonly property string frameClock: displayFrame && validLocal(displayFrame.local_time) && formats && formats.dayTime ? formats.dayTime(displayFrame.local_time)
    : displayFrame && validLocal(displayFrame.local_time) ? displayFrame.local_time.substring(11, 16)
    : displayFrame && typeIsNumber(displayFrame.time) ? new Date(displayFrame.time * 1000).toLocaleString(Qt.locale(), "HH:mm") : "—"
  readonly property string frameLead: frameLeadLabel(displayFrame)
  implicitHeight: content.implicitHeight + Commons.Style.space(24)
  height: implicitHeight
  radius: Commons.Style.cornerRadius
  color: soft

  function typeIsNumber(value) { return typeof value === "number" && isFinite(value) }
  function validLocal(value) { return typeof value === "string" && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && isFinite(Date.parse(value)) }
  function localSource(value) { return typeof value === "string" && value.length < 4096 && value.indexOf("file:///") === 0 ? value : "" }
  function frameTileCount(index) {
    var frame = frames[index]
    return frame && Array.isArray(frame.tiles) ? frame.tiles.length : 0
  }
  function frameTile(frameIndex, tileIndex) {
    var frame = frames[frameIndex]
    return frame && Array.isArray(frame.tiles) && frame.tiles[tileIndex] ? frame.tiles[tileIndex] : null
  }
  function frameLeadLabel(frame) {
    if (!frame || !typeIsNumber(frame.time)) return ""
    // The lead is measured against the current frame's own timeline: the
    // wind frames sit on a 15 minute grid, so their "now" is the timeline's
    // now frame, not the five-minute radar clock.
    var frames = mode === "wind" ? windData.frames : rainData.frames
    var reference = (Array.isArray(frames) && nowIndex >= 0 && nowIndex < frames.length
                     && typeIsNumber(frames[nowIndex].time)) ? frames[nowIndex].time : radar.now
    if (!typeIsNumber(reference)) return ""
    var minutes = Math.round((frame.time - reference) / 60)
    if (Math.abs(minutes) < 5) return "now"
    if (minutes < 0) return "−" + Math.abs(minutes) + " min"
    if (minutes < 60) return "+" + minutes + " min"
    var rest = minutes % 60
    return "+" + Math.floor(minutes / 60) + " h" + (rest ? " " + rest + " min" : "")
  }
  function mapPoint(latitude, longitude) {
    // One point of the wind grid in the 432 x 240 view space.
    var spanX = Math.max(0.000001, Number(radar.east) - Number(radar.west))
    var spanY = Math.max(0.000001, Number(radar.north) - Number(radar.south))
    return {
      x: (Number(longitude) - Number(radar.west)) / spanX * 432,
      y: (Number(radar.north) - Number(latitude)) / spanY * 240
    }
  }

  function run(action, arg) {
    if (worker.running) {
      pending = {action: action, arg: arg}
      if (worker.action === "load" && action !== "load") worker.running = false
      return
    }
    pending = null
    worker.action = action
    worker.requestKey = cityKey
    worker.requestZoom = zoomLevel
    worker.command = arg === undefined ? ["python3", "-B", scriptPath, action] : ["python3", "-B", scriptPath, action, JSON.stringify(arg)]
    worker.running = true
  }
  function refresh() {
    if (!active || !settingsLoaded || cityKey === "") return
    // One radar per metric: a disabled radar fetches nothing and says so.
    // Raw properties, not bindings: a mode change may run before bindings settle.
    if (mode === "wind" ? !windEnabled : !rainEnabled) return
    run("load", Object.assign({}, city, {modes: [mode]}))
  }
  function configure(change) {
    if (change.rain_enabled !== undefined) rainEnabled = change.rain_enabled
    if (change.wind_enabled !== undefined) windEnabled = change.wind_enabled
    if (change.zoom_level !== undefined) { zoomLevel = change.zoom_level; radar = ({}); rainData = ({}); windData = ({}) }
    message = ""
    run("configure", {rain_enabled: rainEnabled, wind_enabled: windEnabled, zoom_level: zoomLevel})
    if (active) refresh()
  }
  function togglePlayback() {
    if (frameCount < 2) return
    playing = !playing
    if (playing && frameIndex >= frameCount - 1) frameIndex = Math.max(0, nowIndex)
  }
  function stepFrames(delta) {
    playing = false
    if (frameCount) frameIndex = (frameIndex + delta + frameCount) % frameCount
  }
  function zoomBy(delta) { configure({zoom_level: Math.max(-2, Math.min(3, zoomLevel + delta))}) }
  function schedulePartialRetry() {
    // Rate-limited or timed-out loads recover on their own: the shared
    // download budget resets after a minute and retries finish the cache.
    if (active && retryCredits > 0) partialRetry.restart()
  }
  function reportFault() {
    if (imageFault) return
    imageFault = true
    message = "Some radar images are unavailable."
  }
  // The DWD composite scale: official boundaries and swatch colours of the
  // Niederschlagsradar legend graphic, read from the DWD WMS legend.
  readonly property var rainScale: [
    {c: "#33ffff", l: "0.1 – 0.2"},
    {c: "#1acc9a", l: "0.2 – 0.4"},
    {c: "#019934", l: "0.4 – 1.0"},
    {c: "#4db31b", l: "1.0 – 2.0"},
    {c: "#99cc01", l: "2.0 – 3.0"},
    {c: "#cce601", l: "3.0 – 5.0"},
    {c: "#ffff01", l: "5.0 – 7.5"},
    {c: "#ffc401", l: "7.5 – 10"},
    {c: "#ff8901", l: "10 – 15"},
    {c: "#ff4501", l: "15 – 30"},
    {c: "#fe0000", l: "30 – 45"},
    {c: "#e5004c", l: "45 – 75"},
    {c: "#cc0098", l: "75 – 100"},
    {c: "#6600cb", l: "100 – 150"},
    {c: "#0000fe", l: "over 150"}
  ]
  readonly property var windScale: [{s: 10, l: "≈ 10 km/h"}, {s: 30, l: "≈ 30 km/h"}, {s: 60, l: "≈ 60 km/h"}]
  onCityKeyChanged: {
    radar = ({}); rainData = ({}); windData = ({})
    message = ""
    imageFault = false
    frameIndex = 0
    playing = false
    refresh()
  }
  onModeChanged: {
    playing = false
    imageFault = false
    message = ""
    // Derived bindings may still hold the previous mode; settle first.
    Qt.callLater(function() {
      frameIndex = Math.max(0, Math.min(nowIndex >= 0 ? nowIndex : frameCount - 1, frameCount - 1))
      refresh()
    })
  }
  onActiveChanged: {
    if (active) { retryCredits = 3; refresh() }
    else {
      playing = false
      partialRetry.stop()
      if (pending && pending.action === "load") pending = null
      if (worker.running && worker.action === "load") worker.running = false
    }
  }
  Component.onCompleted: run("settings")

  Process {
    id: worker
    property bool timedOut: false
    onRunningChanged: if(running) {timedOut=false;requestDeadline.restart()} else requestDeadline.stop()
    property string action: ""
    property string requestKey: ""
    property int requestZoom: 1
    stdout: SplitParser {
      onRead: function(line) {
        // Any output proves the worker is alive; the watchdog measures silence,
        // not total duration, so slow cold radar renders may finish.
        requestDeadline.restart()
        root.handleLine(line)
      }
    }
    onExited: {
      if (root.pending) {
        var next = root.pending
        root.pending = null
        if (next.action !== "load" || root.active)
          Qt.callLater(function() { root.run(next.action, next.arg) })
      }
    }
  }
  function handleLine(line) {
    if (worker.timedOut || !line || !line.trim()) return
    var parsed
    try { parsed = JSON.parse(line) } catch (e) { return }
    if (!parsed || typeof parsed !== "object") return
    if (worker.action !== "load") {
      // A rapid click may have queued a newer complete preference set.
      if (root.pending && root.pending.action === "configure") return
      if (parsed.settings) {
        root.rainEnabled = parsed.settings.rain_enabled !== false
        root.windEnabled = parsed.settings.wind_enabled !== false
        root.zoomLevel = typeIsNumber(parsed.settings.zoom_level) ? parsed.settings.zoom_level : 1
        root.settingsLoaded = true
        // configure() already queues its own load; only the startup read triggers one.
        if (worker.action === "settings") root.refresh()
      }
      return
    }
    if (parsed.kind === "meta") {
      if (worker.requestKey !== root.cityKey || worker.requestZoom !== root.zoomLevel) return
      root.radar = parsed
      // A mode that was not fetched keeps whatever it showed before; the
      // backend marks skipped sequences as disabled instead of emptying them.
      if (!parsed.rain || parsed.rain.disabled !== true) root.rainData = parsed.rain || {}
      if (!parsed.wind || parsed.wind.disabled !== true) root.windData = parsed.wind || {}
      root.imageFault = false
      root.frameIndex = Math.max(0, Math.min(nowIndex >= 0 ? nowIndex : frameCount - 1, frameCount - 1))
      root.message = parsed.error || ""
    } else if (parsed.kind === "frame") {
      if (worker.requestKey !== root.cityKey || worker.requestZoom !== root.zoomLevel) return
      var rainFrames = Array.isArray(rainData.frames) ? rainData.frames : []
      if (parsed.index >= 0 && parsed.index < rainFrames.length) {
        var framesCopy = rainFrames.slice()
        framesCopy[parsed.index] = Object.assign({}, framesCopy[parsed.index], {tiles: parsed.tiles})
        rainData = Object.assign({}, rainData, {frames: framesCopy})
      }
    } else if (parsed.kind === "done") {
      if (parsed.error && !root.frameCount) root.message = parsed.error
      else if (root.message === "" && parsed.message) root.message = parsed.message
      if (!root.active) return
      if (parsed.partial === true || root.message !== "") schedulePartialRetry()
      else { partialRetry.stop(); retryCredits = 3 }
    }
  }
  Timer {
    // Killed after 90 seconds without any streamed line: silent workers die,
    // slow but producing cold radar renders are left to finish.
    id: requestDeadline
    objectName: "radar-request-deadline"
    interval: 90000
    onTriggered: {worker.timedOut=true;root.pending=null;worker.running=false;root.playing=false;root.schedulePartialRetry();if(!root.frameCount)root.message="Radar request timed out. Please try again."}
  }
  Timer {
    // Completes rate-limited loads: one minute after a partial result the
    // download budget has recovered and the cached tiles shorten the work.
    id: partialRetry
    objectName: "radar-partial-retry"
    interval: 65000
    onTriggered: if (root.active && !root.busy && root.retryCredits > 0) { root.retryCredits--; root.refresh() }
  }
  Timer {
    interval: 600000
    repeat: true
    running: root.active && root.settingsLoaded
    onTriggered: if (!worker.running) root.refresh()
  }
  Timer {
    interval: 800
    repeat: true
    running: root.active && root.playing && root.frameCount > 1
    onTriggered: root.frameIndex = (root.frameIndex + 1) % root.frameCount
  }
  Timer {
    // Wind particles drift on their own clock, independent of the frames.
    interval: 90
    repeat: true
    running: root.active && root.mode === "wind" && root.imageReady
    onTriggered: windCanvas.phase = (windCanvas.phase + 1) % 1000000
  }
  Shortcut {
    // Space belongs to the radar timeline while the radars register is open.
    // A window shortcut fires before the focused control's own Space handling
    // would activate it, so play/pause is the only thing Space does here.
    sequence: "Space"
    enabled: root.active
    onActivated: root.togglePlayback()
  }

  component RadarButton: Ui.Button {
    id: button
    property string label: ""
    property string accessibleLabel: label
    width: Commons.Style.space(38)
    height: Commons.Style.space(36)
    text: label
    fontSize: width > Commons.Style.space(60) ? Commons.Style.font.bodySmall : Commons.Style.font.title
    background: root.soft
    bordered: true
    focusable: true
    opacity: enabled ? 1 : 0.4
    Accessible.role: Accessible.Button
    Accessible.name: accessibleLabel
    Accessible.onPressAction: clicked()
  }

  Column {
    id: content
    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
    anchors.margins: Commons.Style.space(14)
    anchors.topMargin: Commons.Style.space(10)
    spacing: Commons.Style.space(10)
    Item {
      width: parent.width; height: Commons.Style.space(36)
      RadarButton { id: rainSwitch; objectName: "map-rain"; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; width: Commons.Style.space(64); label: "Rain"; accessibleLabel: "Show the rain radar"; selected: root.mode !== "wind"; onClicked: root.modeRequested("rain") }
      RadarButton { objectName: "map-wind"; anchors.left: rainSwitch.right; anchors.leftMargin: Commons.Style.space(8); anchors.verticalCenter: parent.verticalCenter; width: Commons.Style.space(64); label: "Wind"; accessibleLabel: "Show the wind map"; selected: root.mode === "wind"; onClicked: root.modeRequested("wind") }
      RadarButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: Commons.Style.space(96); label: "Legend"; accessibleLabel: root.legendVisible ? "Hide legend" : "Show legend"; onClicked: root.legendVisible = !root.legendVisible }
    }
    Rectangle {
      objectName: "radar-legend"
      visible: root.legendVisible
      width: parent.width
      height: visible ? legendColumn.implicitHeight + Commons.Style.space(12) : 0
      color: "transparent"
      border.width: 1
      border.color: root.muted
      radius: Commons.Style.cornerRadius
      Column {
        id: legendColumn
        anchors.fill: parent; anchors.margins: Commons.Style.space(6)
        spacing: Commons.Style.space(3)
        // Rain: the DWD composite scale in mm/h. Wind: arrow length per speed.
        Grid {
          columns: 3; columnSpacing: Commons.Style.space(10); rowSpacing: Commons.Style.space(2)
          visible: root.mode !== "wind"
          Repeater {
            model: root.rainScale
            delegate: Row {
              required property var modelData
              spacing: Commons.Style.space(5)
              Rectangle { width: Commons.Style.space(14); height: Commons.Style.space(10); color: modelData.c; radius: 2; anchors.verticalCenter: parent.verticalCenter }
              PText { text: modelData.l + " mm/h"; font.pixelSize: Commons.Style.font.caption; color: Commons.Color.foreground }
            }
          }
        }
        Column {
          visible: root.mode === "wind"
          spacing: Commons.Style.space(3)
          Repeater {
            model: root.windScale
            delegate: Row {
              required property var modelData
              spacing: Commons.Style.space(6)
              Item {
                width: Commons.Style.space(14 + modelData.s / 4); height: Commons.Style.space(10); anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: parent.width - Commons.Style.space(6); height: 3; color: "#ffd180"; radius: 1.5; anchors.verticalCenter: parent.verticalCenter }
                Rectangle { width: Commons.Style.space(6); height: 3; color: "#ffd180"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; rotation: 45; transformOrigin: Item.Right }
              }
              PText { text: modelData.l; font.pixelSize: Commons.Style.font.caption; color: Commons.Color.foreground }
            }
          }
          PText { text: "white streaks: particle drift"; font.pixelSize: Commons.Style.font.caption; color: Commons.Color.foreground; opacity: 0.7 }
          PText { text: "yellow arrows: wind at grid points"; font.pixelSize: Commons.Style.font.caption; color: Commons.Color.foreground; opacity: 0.7 }
        }
      }
    }
    Column {
      width: parent.width; spacing: Commons.Style.space(8)
      Item {
        id: viewport
        visible: !root.unsupported
        width: parent.width; height: width * 240 / 432
        clip: true
        Rectangle { anchors.fill: parent; color: "#dce7e5"; radius: Commons.Style.cornerRadius }
        Item {
          width: 432; height: 240
          scale: viewport.width / 432
          transformOrigin: Item.TopLeft
          Repeater {
            model: root.tiles
            delegate: Image {
              required property var modelData
              x: modelData.left; y: modelData.top; width: modelData.width; height: modelData.height
              source: root.localSource(modelData.source); asynchronous: true
            }
          }
          Rectangle {
            // Dim the basemap so overlays read clearly: slightly in rain
            // mode, more strongly under the wind vector field.
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.mode === "wind" ? 0.38 : 0.15)
          }
          Repeater {
            model: root.mode === "rain" ? root.frameCount : 0
            delegate: Item {
              id: frameOwner
              required property int index
              width: 432; height: 240
              visible: index === root.displayIndex
              Repeater {
                model: root.frameTileCount(frameOwner.index)
                delegate: Image {
                  required property int index
                  readonly property var tile: root.frameTile(frameOwner.index, index)
                  x: tile ? tile.left : 0; y: tile ? tile.top : 0
                  width: tile ? tile.width : 0; height: tile ? tile.height : 0
                  source: tile ? root.localSource(tile.source) : ""
                  opacity: 0.8; asynchronous: false
                  visible: frameOwner.visible && tile && tile.source !== ""
                  onStatusChanged: if (status === Image.Error) root.reportFault()
                }
              }
            }
          }
          Canvas {
            id: windCanvas
            anchors.fill: parent
            visible: root.mode === "wind"
            property real phase: 0
            onPhaseChanged: requestPaint()
            onVisibleChanged: requestPaint()
            onPaint: {
              var context = getContext("2d")
              context.reset()
              if (!visible) return
              var points = root.currentFrame && root.currentFrame.points ? root.currentFrame.points : []
              if (!points.length) return
              context.fillStyle = "rgba(27,103,194,0.22)"
              context.fillRect(0, 0, width, height)
              // Drifting particles: one phase step per 90 ms, travel proportional
              // to the real wind near each particle's anchor.
              context.strokeStyle = "rgba(255,255,255,0.72)"
              context.lineWidth = 2.4
              for (var sampleIndex = 0; sampleIndex < 140; ++sampleIndex) {
                var sample = points[sampleIndex % points.length]
                var direction = Number(sample[3] || 0)
                var speed = Math.max(0, Number(sample[2] || 0))
                var angle = (direction + 90) * Math.PI / 180
                var dx = Math.cos(angle), dy = Math.sin(angle)
                var anchor = points.length > 1 ? root.mapPoint(sample[0], sample[1]) : null
                var anchorX = anchor ? anchor.x : (sampleIndex * 79 % 432)
                var anchorY = anchor ? anchor.y : (sampleIndex * 47 % 240)
                var jitterX = ((sampleIndex * 37) % 61) - 30
                var jitterY = ((sampleIndex * 53) % 45) - 22
                var travel = (windCanvas.phase * (0.15 + speed * 0.045) + sampleIndex * 7) % 34 - 17
                var px = anchorX + jitterX + dx * travel
                var py = anchorY + jitterY + dy * travel
                var length = 5 + Math.min(11, speed / 2)
                context.beginPath()
                context.moveTo(px, py)
                context.lineTo(px + dx * length, py + dy * length)
                context.stroke()
              }
              // One vector arrow at each of the 35 grid samples.
              context.strokeStyle = "rgba(255,209,128,0.95)"
              context.lineWidth = 3
              for (var point = 0; point < points.length; ++point) {
                var item = points[point]
                var itemAngle = (Number(item[3] || 0) + 90) * Math.PI / 180
                var itemDx = Math.cos(itemAngle), itemDy = Math.sin(itemAngle)
                var itemPoint = root.mapPoint(item[0], item[1])
                var arrowLength = 7 + Math.min(12, Number(item[2] || 0) / 2)
                var tipX = itemPoint.x + itemDx * arrowLength
                var tipY = itemPoint.y + itemDy * arrowLength
                context.beginPath(); context.moveTo(itemPoint.x, itemPoint.y); context.lineTo(tipX, tipY); context.stroke()
                context.beginPath()
                context.moveTo(tipX, tipY)
                context.lineTo(tipX - itemDx * 8 - itemDy * 5, tipY - itemDy * 8 + itemDx * 5)
                context.moveTo(tipX, tipY)
                context.lineTo(tipX - itemDx * 8 + itemDy * 5, tipY - itemDy * 8 - itemDx * 5)
                context.stroke()
              }
            }
          }
          Connections {
            target: root
            function onCurrentFrameChanged() { windCanvas.requestPaint() }
            function onModeChanged() { windCanvas.requestPaint() }
          }
          Rectangle {
            anchors.centerIn: parent; width: 12; height: 12; radius: 6
            color: Commons.Color.accent; border.color: "white"; border.width: 2
            visible: root.imageReady
          }
        }
        Rectangle {
          anchors.centerIn: parent; width: Math.min(parent.width - 24, status.implicitWidth + 24); height: status.implicitHeight + 18; radius: Commons.Style.cornerRadius
          color: Commons.Color.background
          visible: !root.unsupported && !root.imageReady
          PText { id: status; objectName: "radar-status"; anchors.centerIn: parent; text: root.busy ? "Loading…" : !root.modeEnabled ? "Radar is off" : "No data available"; font.pixelSize: Commons.Style.font.body }
        }
        Item {
          anchors.bottom: parent.bottom; anchors.right: parent.right
          width: credit.implicitWidth + 6; height: credit.implicitHeight
          PText { id: credit; anchors.centerIn: parent; text: "© OpenStreetMap contributors ↗"; color: Qt.rgba(0.12, 0.19, 0.19, 0.5); font.pixelSize: Commons.Style.font.caption }
          TapHandler { onTapped: Qt.openUrlExternally("https://www.openstreetmap.org/copyright") }
          Accessible.role: Accessible.Link; Accessible.name: "OpenStreetMap attribution"
          activeFocusOnTab: true
          Keys.onReturnPressed: Qt.openUrlExternally("https://www.openstreetmap.org/copyright")
        }
      }
      Row {
        visible: !root.unsupported
        width: parent.width; spacing: Commons.Style.space(4)
        RadarButton { width: Commons.Style.space(34); label: "‹"; accessibleLabel: "Earlier frame"; enabled: root.frameCount > 0; onClicked: root.stepFrames(-1) }
        RadarButton { width: Commons.Style.space(34); label: root.playing ? "Ⅱ" : "▶"; accessibleLabel: root.playing ? "Pause animation" : "Play animation"; enabled: root.frameCount > 1; onClicked: root.togglePlayback() }
        RadarButton { width: Commons.Style.space(34); label: "›"; accessibleLabel: "Later frame"; enabled: root.frameCount > 0; onClicked: root.stepFrames(1) }
        // Date and time sit between the two button groups; the frame's
        // relative lead keeps its own centered line below the timeline.
        PText { width: Math.max(0, parent.width - Commons.Style.space(228)); text: root.frameClock; anchors.verticalCenter: parent.verticalCenter; horizontalAlignment: Text.AlignHCenter; font.pixelSize: Commons.Style.font.bodySmall; elide: Text.ElideRight }
        RadarButton { objectName: "map-zoom-out"; width: Commons.Style.space(34); label: "−"; accessibleLabel: "Zoom out"; enabled: root.zoomLevel > -2; onClicked: root.zoomBy(-1) }
        RadarButton { objectName: "map-zoom-in"; width: Commons.Style.space(34); label: "+"; accessibleLabel: "Zoom in"; enabled: root.zoomLevel < 3; onClicked: root.zoomBy(1) }
        RadarButton { width: Commons.Style.space(34); label: "↻"; accessibleLabel: "Refresh radar"; enabled: !root.busy; onClicked: root.refresh() }
      }
      Slider {
        id: timelineSlider
        visible: !root.unsupported
        width: parent.width
        implicitHeight: Commons.Style.space(28)
        from: 0; to: Math.max(1, root.frameCount - 1); stepSize: 1
        value: root.frameIndex; enabled: root.frameCount > 1
        Accessible.name: "Radar timeline"
        onMoved: { root.playing = false; root.frameIndex = Math.round(value) }
        background: Rectangle {
          x: timelineSlider.leftPadding
          y: timelineSlider.topPadding + (timelineSlider.availableHeight - height) / 2
          width: timelineSlider.availableWidth; height: Commons.Style.space(4)
          radius: Commons.Style.cornerRadius > 0 ? height / 2 : 0
          color: Commons.Style.normalFillFor(Commons.Color.foreground, Commons.Color.accent)
          Rectangle {
            x: timelineSlider.mirrored ? parent.width - width : 0
            width: parent.width * timelineSlider.position; height: parent.height; radius: parent.radius
            color: Commons.Color.accent
          }
          Rectangle {
            // Marks where the observations end and the predictions begin.
            // It travels the same path as the slider handle so it stays
            // centred on the now frame at every index.
            visible: root.nowIndex > 0 && root.frameCount > 1
            x: (parent.width - Commons.Style.space(14)) * root.nowIndex / Math.max(1, root.frameCount - 1) + Commons.Style.space(7) - width / 2
            width: 2; height: Commons.Style.space(12); y: -Commons.Style.space(4)
            color: Commons.Color.accent
          }
        }
        handle: Rectangle {
          x: timelineSlider.leftPadding + timelineSlider.visualPosition * (timelineSlider.availableWidth - width)
          y: timelineSlider.topPadding + (timelineSlider.availableHeight - height) / 2
          width: Commons.Style.space(14); height: width
          radius: Commons.Style.cornerRadius > 0 ? width / 2 : 0
          color: timelineSlider.enabled ? Commons.Color.foreground : root.muted
          border.width: timelineSlider.activeFocus ? 2 : 1
          border.color: timelineSlider.activeFocus ? Commons.Color.accent : Commons.Color.background
        }
      }
      PText { width: parent.width; visible: root.message !== ""; text: root.message; color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: Commons.Style.font.bodySmall }
      PText { width: parent.width; visible: root.unsupported; text: "This map projection cannot show the selected location. Forecast weather is still available."; color: root.muted; font.pixelSize: Commons.Style.font.bodySmall; wrapMode: Text.WordWrap }
      Item {
        // Bottom line: the source link on the left, the frame's relative
        // time centered at the same height. Centered text cannot collide:
        // the longest source label ends near x≈130 while a centered
        // "+1 h 55 min" starts near x≈165.
        width: parent.width
        height: providerLink.text !== "" || root.frameLead !== "" ? providerLink.implicitHeight : 0
        PText {
          id: providerLink
          anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
          text: root.mode === "wind"
            ? "Wind: Open-Meteo ↗"
            : (root.sequence.provider_name === "DWD" ? "Radar: DWD ↗" : root.sequence.provider_name === "RainViewer" ? "Radar: RainViewer ↗" : "")
          visible: text !== ""
          color: root.muted; font.pixelSize: Commons.Style.font.bodySmall
          TapHandler {
            onTapped: Qt.openUrlExternally(root.mode === "wind" ? "https://open-meteo.com/"
              : root.sequence.provider_name === "DWD" ? "https://www.dwd.de/" : "https://www.rainviewer.com/")
          }
          activeFocusOnTab: true; Accessible.role: Accessible.Link; Accessible.name: text
          Keys.onReturnPressed: Qt.openUrlExternally(root.mode === "wind" ? "https://open-meteo.com/"
            : root.sequence.provider_name === "DWD" ? "https://www.dwd.de/" : "https://www.rainviewer.com/")
          Rectangle { anchors.fill: parent; color: "transparent"; border.width: parent.activeFocus ? 1 : 0; border.color: Commons.Color.accent }
        }
        PText {
          anchors.centerIn: parent
          text: root.frameLead; visible: root.frameLead !== ""
          color: Commons.Color.foreground; font.pixelSize: Commons.Style.font.bodySmall
          Accessible.role: Accessible.StaticText; Accessible.name: "Frame time relative to now: " + root.frameLead
        }
      }
    }
  }
}
