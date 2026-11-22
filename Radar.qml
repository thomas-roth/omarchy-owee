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
  // Warm the map while the panel is open on another page, so the Radar tab
  // opens with images already cached.
  property bool preload: false
  property bool legendExpanded: false
  property bool radarEnabled: false
  property int zoom: 6
  property string source: "auto"
  property string mapLayer: "rain"
  property bool settingsLoaded: false
  property var radar: ({})
  property string windSummary: ""
  property int frameIndex: 0
  property bool playing: false
  // Keep the view on the present (latest observation) until the user steps.
  property bool followPresent: true
  property int warmPolls: 0
  property string message: ""
  property var pending: null
  signal weatherRequested()
  property string coverageState: "unknown"
  property int imageRevision: 0
  readonly property bool imageReady: raster ? rasterImage.status === Image.Ready && localSource(currentFrame ? currentFrame.image : "") !== "" : frameImageState(false)
  readonly property bool imageError: raster ? rasterImage.status === Image.Error : frameImageState(true)
  readonly property bool projectionUnsupported: radar.status === "unsupported" && radar.reason === "projection_limit"
  readonly property bool coverageLimited: radar.status === "unsupported" && radar.reason === "coverage_limit"
  readonly property bool raster: radar.render === "raster"
  readonly property bool dwd: radar.provider === "DWD"
  readonly property bool wind: mapLayer === "wind" || radar.layer === "wind"
  readonly property bool germanView: city && isFinite(city.latitude) && isFinite(city.longitude)
    && Number(city.latitude) >= 47.0 && Number(city.latitude) <= 55.2
    && Number(city.longitude) >= 5.5 && Number(city.longitude) <= 15.6
  readonly property bool dwdSource: source === "dwd" || (source === "auto" && germanView)
  // DWD delivers 1 km composites at any map zoom; RainViewer stops at zoom 7.
  readonly property int maxZoom: wind || dwdSource ? 10 : 7
  readonly property bool viewportAvailable: radarEnabled && !projectionUnsupported
  readonly property var coverageTiles: Array.isArray(radar.coverage_tiles) ? radar.coverage_tiles : []
  readonly property var frames: Array.isArray(radar.frames) ? radar.frames : []
  readonly property var currentFrame: frames.length > frameIndex ? frames[frameIndex] : null
  readonly property bool busy: worker.running
  readonly property string cityKey: city && isFinite(city.latitude) && isFinite(city.longitude) ? Number(city.latitude).toFixed(5) + "," + Number(city.longitude).toFixed(5) : ""
  readonly property color muted: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.72)
  readonly property color soft: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.075)
  readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("radar.py").toString().replace(/^file:\/\//, ""))
  readonly property string frameTime: frames.length > frameIndex ? dateTime(frames[frameIndex]) : "—"
  readonly property string coverageText: projectionUnsupported
    ? "This map projection cannot show the selected location. Forecast weather is still available."
    : coverageLimited
      ? (wind ? "The wind map covers Germany only. Choose a German city." : "DWD radar covers Germany only. Choose another radar source or a German city.")
      : dwd || wind
        ? ""
        : coverageState === "uncovered"
          ? "No radar coverage at this location. Shaded areas have no radar observations."
          : coverageState === "covered"
            ? "Radar covers this location. Shaded areas are outside coverage."
            : ""
  readonly property string legendSource: Qt.resolvedUrl(wind ? "assets/legend-wind.png" : "assets/legend-rain.png")
  readonly property string legendDescription: wind
    ? "Wind legend in metres per second. A half feather is 2.5, a full feather is 5, a full and half feather is 7.5, and a pennant is 25."
    : "Rain legend in dBZ. The scale runs from 7 to 55."
  implicitHeight: content.implicitHeight + Commons.Style.space(28)
  height: implicitHeight
  radius: Commons.Style.cornerRadius
  color: soft

  function localSource(value) { return typeof value === "string" && value.length < 4096 && value.indexOf("file:///") === 0 ? value : "" }
  function frameImageState(errors) {
    if(imageRevision<0 || !frameImages || frameIndex>=frames.length || !frames.length || !Array.isArray(frames[frameIndex].tiles) || !frameImages.count) return false
    for(var i=0;i<frameImages.count;i++) {
      var image=frameImages.itemAt(i)
      if(errors && image && image.status===Image.Error)return true
      if(!errors && (!image || image.status!==Image.Ready))return false
    }
    return !errors && frameImages.count===frames[frameIndex].tiles.length
  }
  onImageErrorChanged: if(imageError) Qt.callLater(function(){if(root.imageError){root.playing=false;root.message="Radar image unavailable. Refresh to try again."}})
  function validLocal(value) { return typeof value === "string" && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && isFinite(Date.parse(value)) }
  function dateTime(frame) {
    if(!frame) return "—"
    if(validLocal(frame.local_time) && formats) return formats.dayTime(frame.local_time)
    if(validLocal(frame.local_time)) return frame.local_time.slice(8,10)+"/"+frame.local_time.slice(5,7)+" "+frame.local_time.slice(11,16)
    return typeof frame.time === "number" && isFinite(frame.time) ? (formats ? formats.instant(frame.time) : new Date(frame.time*1000).toLocaleString(Qt.locale("en_GB"),"dd/MM hh:mm")) : "—"
  }
  function prepareCoverage() {
    coverageState="unknown"
    if(!active || !radarEnabled || projectionUnsupported || radar.coverage_status!=="available" || !coverageTiles.length || coverageImages.count!==coverageTiles.length) return false
    for(var i=0;i<coverageTiles.length;i++) {
      var image=coverageImages.itemAt(i), source=localSource(coverageTiles[i].source)
      if(!image || image.status!==Image.Ready || !source) return false
      if(coverageSampler.requested.indexOf(source)<0) {
        coverageSampler.requested=coverageSampler.requested.concat([source])
        coverageSampler.loadImage(source)
      }
      if(!coverageSampler.isImageLoaded(source)) return false
    }
    return true
  }
  function checkCoverage() { if(prepareCoverage())coverageSampler.requestPaint() }
  onRadarChanged: {
    coverageState="unknown"
    if(coverageSampler)coverageSampler.resetSources()
    Qt.callLater(checkCoverage)
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
    worker.requestZoom = zoom
    worker.requestSource = source
    worker.requestLayer = mapLayer
    worker.command = arg === undefined ? ["python3", "-B", scriptPath, action] : ["python3", "-B", scriptPath, action, JSON.stringify(arg)]
    worker.running = true
  }
  function refresh() {
    if ((active || preload) && settingsLoaded && radarEnabled && cityKey !== "") run("load", city)
  }
  function configure(change) {
    if (change.enabled !== undefined) radarEnabled = change.enabled
    if (change.zoom !== undefined) { zoom = change.zoom; radar = ({}) }
    if (change.source !== undefined) { source = change.source; radar = ({}) }
    if (change.layer !== undefined) { mapLayer = change.layer; radar = ({}) }
    if (zoom > maxZoom) zoom = maxZoom
    followPresent = true
    warmPolls = 0
    playing = false
    message = ""
    run("configure", {enabled: radarEnabled, zoom: zoom, source: source, layer: mapLayer})
  }
  function showPresent() {
    var present = Number(radar.default_index)
    frameIndex = isFinite(present) && present >= 0 && present < frames.length ? present : Math.max(0, frames.length - 1)
  }
  function zoomBy(delta) {
    var next = Math.max(3, Math.min(maxZoom, zoom + delta))
    if (next === zoom) return false
    configure({zoom: next})
    return true
  }
  function step(delta) {
    playing = false
    followPresent = false
    if (!frames.length) return
    frameIndex = Math.max(0, Math.min(frames.length - 1, frameIndex + delta))
  }
  function togglePlayback() {
    if (!frames.length || !imageReady || Commons.Style.duration(1) <= 0) return
    if (playing) { playing = false; return }
    // A warming timeline can hold only the present frame. Arm playback and
    // keep the view on the present, so the button and the Space key answer at
    // once and the animation starts when the next frame arrives.
    if (frames.length < 2) { followPresent = true; playing = true; return }
    followPresent = false
    // Restart from the oldest frame when playback is resumed at the end.
    if (frameIndex >= frames.length - 1) frameIndex = 0
    playing = true
  }
  function focusViewport() {
    if (!root.visible || !viewportAvailable || !viewport.visible) return false
    viewport.forceActiveFocus()
    return viewport.activeFocus
  }
  function selectLayer(value) {
    if (["rain","wind"].indexOf(value) < 0) return
    if (mapLayer !== value) { configure({layer: value}); return }
    followPresent = true
    playing = false
    showPresent()
  }
  onCityKeyChanged: {
    radar = ({})
    message = ""
    if (zoom > maxZoom) zoom = maxZoom
    frameIndex = 0
    playing = false
    followPresent = true
    warmPolls = 0
    warmTimer.stop()
    refresh()
  }
  onActiveChanged: {
    if (active) {
      // Keep the frame on screen while the refresh runs instead of jumping
      // back to the oldest cached image.
      showPresent()
      playing = false
      followPresent = true
      warmPolls = 0
      refresh()
      Qt.callLater(checkCoverage)
    }
    else {
      coverageState="unknown"
      playing = false
      followPresent = true
      warmTimer.stop()
      if (pending && pending.action === "load") pending = null
      if (worker.running && worker.action === "load") worker.running = false
    }
  }
  onPreloadChanged: {
    if (preload) {
      warmPolls = 0
      refresh()
    }
  }
  Component.onCompleted: run("settings")

  Process {
    id: worker
    property bool timedOut: false
    onRunningChanged: if(running) {timedOut=false;requestDeadline.restart()} else requestDeadline.stop()
    property string action: ""
    property string requestKey: ""
    property int requestZoom: 6
    property string requestSource: "auto"
    property string requestLayer: "rain"
    onExited: {
      if (root.pending) {
        var next = root.pending
        root.pending = null
        if (next.action !== "load" || (root.active && root.radarEnabled))
          Qt.callLater(function() { root.run(next.action, next.arg) })
      }
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if(worker.timedOut)return
        if (!text.trim()) return
        try {
          var parsed = JSON.parse(text)
          if (worker.action !== "load") {
            // A rapid click may have queued a newer complete preference set.
            if (root.pending && root.pending.action === "configure") return
            if (parsed.settings) {
              root.radarEnabled = parsed.settings.enabled === true
              root.zoom = parsed.settings.zoom || 6
              root.source = ["auto","rainviewer","dwd"].indexOf(parsed.settings.source) >= 0 ? parsed.settings.source : "auto"
              root.mapLayer = ["rain","wind"].indexOf(parsed.settings.layer) >= 0 ? parsed.settings.layer : "rain"
              if (root.zoom > root.maxZoom) root.zoom = root.maxZoom
              root.settingsLoaded = true
              root.refresh()
            }
          } else if (root.active && root.radarEnabled && worker.requestKey === root.cityKey && worker.requestZoom === root.zoom && worker.requestSource === root.source && worker.requestLayer === root.mapLayer) {
            root.radar = parsed
            if (root.followPresent) root.showPresent()
            else root.frameIndex = Math.min(root.frameIndex, Math.max(0, root.frames.length - 1))
            // Armed playback waits on the present until a future frame exists,
            // then releases the view and animates forward.
            if (root.playing && root.followPresent
                && root.frames.length > Number(root.radar.default_index) + 1)
              root.followPresent = false
            root.message = parsed.error || parsed.message || ""
            if (parsed.warming === true) warmTimer.restart()
            else {
              warmTimer.stop()
              root.warmPolls = 0
              // The timeline is complete; stop holding a finished animation.
              if (root.playing && root.frameIndex >= root.frames.length - 1) root.playing = false
            }
          }
        } catch (e) { root.message = "Radar data unavailable" }
      }
    }
  }
  Timer {
    id: requestDeadline
    objectName: "radar-request-deadline"
    interval: 50000
    onTriggered: {worker.timedOut=true;root.pending=null;worker.running=false;root.playing=false;root.message="Radar request timed out. Please try again."}
  }
  Timer {
    id: warmTimer
    objectName: "radar-warm-timer"
    // DWD renders one frame at a time on the server; the worker fills the
    // cache in parallel, so poll often and show each frame as it arrives.
    interval: 3000
    repeat: true
    onTriggered: {
      if (!(root.active || root.preload) || !root.radarEnabled) warmTimer.stop()
      else if (!worker.running) {
        // The farthest forecast frame can stay missing for minutes;
        // stop polling after three minutes and wait for the next regular refresh.
        if (root.warmPolls >= 60) {
          warmTimer.stop()
          // Armed playback that never found a second frame must not keep a
          // pause button for a stalled timeline.
          if (root.frames.length < 2) root.playing = false
          return
        }
        root.warmPolls += 1
        root.refresh()
      }
    }
  }
  Timer {
    interval: 600000
    repeat: true
    running: root.active && root.radarEnabled && root.settingsLoaded
    onTriggered: if (!worker.running) root.refresh()
  }
  Timer {
    interval: 800
    repeat: true
    running: root.active && root.radarEnabled && root.playing && root.imageReady && root.frames.length > 1 && Commons.Style.duration(1) > 0
    onTriggered: {
      // Play only towards the future; step back by hand. While the timeline
      // is being polled for new frames, hold the newest frame and continue as
      // soon as more frames arrive.
      if (root.frameIndex >= root.frames.length - 1) {
        if (!warmTimer.running) root.playing = false
        return
      }
      root.frameIndex += 1
    }
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
    // A clicked button keeps focus and would swallow Space; return keyboard
    // control to the map so playback keys always reach the viewport.
    onClicked: Qt.callLater(root.focusViewport)
  }

  Column {
    id: content
    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
    anchors.margins: Commons.Style.space(14)
    spacing: Commons.Style.space(10)
    Row {
      width: parent.width; spacing: Commons.Style.space(8)
      PText { width: parent.width - Commons.Style.space(104); anchors.verticalCenter: parent.verticalCenter; text: root.wind ? "Wind map" : "Precipitation radar"; font.bold: true; font.pixelSize: Commons.Style.font.body; elide: Text.ElideRight }
      RadarButton { width: Commons.Style.space(96); label: root.radarEnabled ? "Disable" : "Enable"; accessibleLabel: root.radarEnabled ? "Disable map" : "Enable map"; onClicked: root.configure({enabled: !root.radarEnabled}) }
    }
    Row {
      width: parent.width; spacing: Commons.Style.space(12)
      PText {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, parent.width - layerGroup.implicitWidth - parent.spacing)
        text: "Map layer"; font.pixelSize: Commons.Style.font.body; elide: Text.ElideRight
      }
      Ui.ButtonGroup {
        id: layerGroup
        objectName: "radar-layer"
        options: [{value:"rain",label:"Rain",tooltip:"Rain · R"},{value:"wind",label:"Wind",tooltip:"Wind · W"}]
        value: root.mapLayer
        onChanged: function(value) { if (value !== root.mapLayer) root.configure({layer: value}) }
      }
    }
    Row {
      width: parent.width; spacing: Commons.Style.space(12)
      visible: !root.wind
      PText {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, parent.width - sourceGroup.implicitWidth - parent.spacing)
        text: "Radar source"; font.pixelSize: Commons.Style.font.body; elide: Text.ElideRight
      }
      Ui.ButtonGroup {
        id: sourceGroup
        objectName: "radar-source"
        options: [
          {value:"auto",label:"Auto",tooltip:"Uses DWD radar in Germany and RainViewer elsewhere"},
          {value:"rainviewer",label:"RainViewer",tooltip:"Radar images outside Germany"},
          {value:"dwd",label:"DWD",tooltip:"German Weather Service radar"}
        ]
        value: root.source
        onChanged: function(value) { if (value !== root.source) root.configure({source: value}) }
      }
    }
    PText {
      width: parent.width
      visible: !root.radarEnabled
      text: "Enable the map to see "+(root.wind?"the wind forecast":"recent radar images")+". "+(root.wind?"DWD and":"The selected radar source and")+" OpenStreetMap receive the area around this city. Updates every 5 minutes, only while this map is visible."
      wrapMode: Text.WordWrap; color: root.muted; font.pixelSize: Commons.Style.font.bodySmall
    }
    Column {
      width: parent.width; spacing: Commons.Style.space(8); visible: root.radarEnabled
      Item {
        id: viewport
        objectName: "radar-viewport"
        visible: !root.projectionUnsupported
        width: parent.width; height: width * 240 / 432
        clip: true
        activeFocusOnTab: root.viewportAvailable
        Accessible.role: Accessible.Graphic
        Accessible.name: "Radar map, " + root.frameTime
        Keys.onPressed: function(event) {
          var key = Commons.Util.readingKey(event)
          if (key === Qt.Key_Left) { root.step(-1); event.accepted = true }
          else if (key === Qt.Key_Right) { root.step(1); event.accepted = true }
          else if (key === Qt.Key_Space) { root.togglePlayback(); event.accepted = true }
          else if (key === Qt.Key_Plus || key === Qt.Key_Equal || event.text === "+") { root.zoomBy(1); event.accepted = true }
          else if (key === Qt.Key_Minus || event.text === "-" || event.text === "−") { root.zoomBy(-1); event.accepted = true }
        }
        TapHandler { onTapped: viewport.forceActiveFocus() }
        Rectangle {
          anchors.fill: parent; radius: Commons.Style.cornerRadius
          color: "#dce7e5"
          border.width: viewport.activeFocus ? 2 : 0; border.color: Commons.Color.accent
        }
        Item {
          width: 432; height: 240
          scale: viewport.width / 432
          transformOrigin: Item.TopLeft
          Repeater {
            model: root.radar.tiles || []
            delegate: Image {
              required property var modelData
              x: modelData.left; y: modelData.top; width: 256; height: 256
              source: root.localSource(modelData.source); asynchronous: true
              sourceSize.width: 256; sourceSize.height: 256
            }
          }
          // Dim the basemap under the wind barbs. The barbs are stored white,
          // so a dark scrim gives them contrast in every theme.
          Rectangle {
            anchors.fill: parent
            visible: root.raster && root.wind
            color: "#000000"
            opacity: 0.5
          }
          Image {
            id: rasterImage
            visible: root.raster
            width: 432; height: 240
            source: root.raster && root.currentFrame ? root.localSource(root.currentFrame.image) : ""
            // Keep roads and place names readable under heavy cells.
            opacity: root.wind ? 1.0 : 0.8
            fillMode: Image.Stretch; asynchronous: false; smooth: true; mipmap: true
            onStatusChanged: root.imageRevision++
          }
          Repeater {
            id: frameImages
            model: root.raster ? [] : (root.radar.tiles || [])
            onCountChanged: root.imageRevision++
            delegate: Image {
              required property var modelData
              required property int index
              x: modelData.left; y: modelData.top; width: 256; height: 256
              source: root.frames.length > root.frameIndex && Array.isArray(root.frames[root.frameIndex].tiles) ? root.localSource(root.frames[root.frameIndex].tiles[index]) : ""
              opacity: 0.8; asynchronous: false
              sourceSize.width: 256; sourceSize.height: 256
              onStatusChanged: root.imageRevision++
            }
          }
          Repeater {
            id: coverageImages
            model: root.coverageTiles
            delegate: Image {
              required property var modelData
              source: root.localSource(modelData.source)
              visible: false; asynchronous: true
              sourceSize.width: 256; sourceSize.height: 256
              onStatusChanged: Qt.callLater(root.checkCoverage)
            }
          }
          Canvas {
            id: coverageSampler
            anchors.fill: parent; opacity: 0.18
            visible: root.active && root.radarEnabled
            property var requested: []
            function resetSources() { for(var i=0;i<requested.length;i++)unloadImage(requested[i]);requested=[];requestPaint() }
            onImageLoaded: Qt.callLater(root.checkCoverage)
            onPaint: {
              var context=getContext("2d");context.reset();context.clearRect(0,0,width,height)
              if(!root.prepareCoverage())return
              try {
                for(var i=0;i<root.coverageTiles.length;i++) {
                  var tile=root.coverageTiles[i]
                  context.drawImage(root.localSource(tile.source),tile.left,tile.top,256,256)
                }
                var alpha=context.getImageData(216,120,1,1).data[3]
                root.coverageState=alpha===0?"covered":alpha===255?"uncovered":"unknown"
              } catch(error) {root.coverageState="unknown"}
            }
          }
          Rectangle {
            anchors.centerIn: parent; width: 12; height: 12; radius: 6
            color: Commons.Color.accent; border.color: "white"; border.width: 2
            visible: root.imageReady
          }
        }
        Rectangle {
          id: windBadge
          visible: root.wind && root.radarEnabled && root.imageReady && root.windSummary !== ""
          anchors.left: parent.left; anchors.bottom: parent.bottom
          anchors.margins: Commons.Style.space(8)
          width: Math.min(parent.width - Commons.Style.space(16), windBadgeLabel.implicitWidth + Commons.Style.space(16))
          height: windBadgeLabel.implicitHeight + Commons.Style.space(8)
          radius: Commons.Style.cornerRadius
          color: Commons.Color.background
          border.width: 1
          border.color: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.18)
          PText {
            id: windBadgeLabel
            anchors.centerIn: parent
            width: parent.width - Commons.Style.space(12)
            horizontalAlignment: Text.AlignHCenter
            text: "Now " + root.windSummary
            font.pixelSize: Commons.Style.font.bodySmall
            elide: Text.ElideRight
          }
        }
        Rectangle {
          anchors.centerIn: parent; width: Math.min(parent.width - 24, status.implicitWidth + 24); height: status.implicitHeight + 18; radius: Commons.Style.cornerRadius
          color: Commons.Color.background
          visible: root.busy || !root.imageReady
          PText { id: status; anchors.centerIn: parent; text: root.busy ? "Loading radar…" : "No image available"; font.pixelSize: Commons.Style.font.body }
        }
        Rectangle {
          anchors.bottom: parent.bottom; anchors.right: parent.right
          width: credit.implicitWidth + 8; height: credit.implicitHeight + 2
          color: "#eeffffff"
          PText { id: credit; anchors.centerIn: parent; text: "© OpenStreetMap ↗"; color: "#203030"; font.pixelSize: Commons.Style.font.bodySmall }
          TapHandler { onTapped: Qt.openUrlExternally("https://www.openstreetmap.org/copyright") }
          Accessible.role: Accessible.Link; Accessible.name: "OpenStreetMap attribution"
          activeFocusOnTab: true
          Keys.onReturnPressed: Qt.openUrlExternally("https://www.openstreetmap.org/copyright")
        }
      }
      Row {
        visible: !root.projectionUnsupported
        width: parent.width; spacing: Commons.Style.space(6)
        RadarButton { objectName: "radar-previous"; label: "‹"; accessibleLabel: "Previous image"; tooltipText: "Previous frame · Left"; enabled: root.frames.length > 0; onClicked: root.step(-1) }
        RadarButton { objectName: "radar-play"; label: root.playing ? "Ⅱ" : "▶"; accessibleLabel: root.playing ? "Pause radar animation" : "Play radar animation"; tooltipText: root.playing ? "Pause · Space" : "Play · Space"; enabled: root.frames.length > 0 && root.imageReady; onClicked: root.togglePlayback() }
        RadarButton { objectName: "radar-next"; label: "›"; accessibleLabel: "Next image"; tooltipText: "Next frame · Right"; enabled: root.frames.length > 0; onClicked: root.step(1) }
        PText { width: Math.max(0, parent.width - Commons.Style.space(264)); text: root.frameTime; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: Commons.Style.font.bodySmall; elide: Text.ElideRight }
        RadarButton { objectName: "radar-zoom-out"; label: "−"; accessibleLabel: "Zoom out (−)"; tooltipText: "Zoom out · −"; enabled: root.zoom > 3; onClicked: root.configure({zoom: root.zoom - 1}) }
        RadarButton { objectName: "radar-zoom-in"; label: "+"; accessibleLabel: "Zoom in (+)"; tooltipText: "Zoom in · +"; enabled: root.zoom < root.maxZoom; onClicked: root.configure({zoom: Math.min(root.zoom + 1, root.maxZoom)}) }
        RadarButton { objectName: "radar-refresh"; label: "↻"; accessibleLabel: "Refresh radar"; tooltipText: "Refresh radar"; enabled: !root.busy; onClicked: root.refresh() }
      }
      Slider {
        id: timeline
        visible: !root.projectionUnsupported
        width: parent.width
        implicitHeight: Commons.Style.space(28)
        from: 0; to: Math.max(1, root.frames.length - 1); stepSize: 1
        value: root.frameIndex; enabled: root.frames.length > 1
        Accessible.name: "Radar timeline"
        onMoved: { root.playing = false; root.followPresent = false; root.frameIndex = Math.round(value) }
        onPressedChanged: if (!pressed) Qt.callLater(root.focusViewport)
        background: Rectangle {
          x: timeline.leftPadding
          y: timeline.topPadding + (timeline.availableHeight - height) / 2
          width: timeline.availableWidth; height: Commons.Style.space(4)
          radius: Commons.Style.cornerRadius > 0 ? height / 2 : 0
          color: Commons.Style.normalFillFor(Commons.Color.foreground, Commons.Color.accent)
          Rectangle {
            x: timeline.mirrored ? parent.width - width : 0
            width: parent.width * timeline.position; height: parent.height; radius: parent.radius
            color: Commons.Color.accent
          }
        }
        handle: Rectangle {
          x: timeline.leftPadding + timeline.visualPosition * (timeline.availableWidth - width)
          y: timeline.topPadding + (timeline.availableHeight - height) / 2
          width: Commons.Style.space(14); height: width
          radius: Commons.Style.cornerRadius > 0 ? width / 2 : 0
          color: timeline.enabled ? Commons.Color.foreground : root.muted
          border.width: timeline.activeFocus ? 2 : 1
          border.color: timeline.activeFocus ? Commons.Color.accent : Commons.Color.background
        }
      }
      Row {
        visible: !root.projectionUnsupported
        width: parent.width; spacing: Commons.Style.space(8)
        PText { width: parent.width / 2 - Commons.Style.space(4); text: root.frames.length ? root.dateTime(root.frames[0]) : "—"; font.pixelSize: Commons.Style.font.bodySmall; color: root.muted }
        PText { width: parent.width / 2 - Commons.Style.space(4); horizontalAlignment: Text.AlignRight; text: root.frames.length ? root.dateTime(root.frames[root.frames.length - 1]) : "—"; font.pixelSize: Commons.Style.font.bodySmall; color: root.muted }
      }
      PText {
        objectName: "radar-coverage-status"; width: parent.width
        visible: text !== ""
        text: root.coverageText
        color: root.muted; font.pixelSize: Commons.Style.font.bodySmall; wrapMode: Text.WordWrap
      }
      RadarButton {
        objectName: "radar-forecast-cta"; width: parent.width
        visible: root.projectionUnsupported
        label: "See weather forecast"
        onClicked: root.weatherRequested()
      }
      PText {
        objectName: "radar-warming"; width: parent.width
        visible: root.radar.warming === true && root.frames.length < 2 && root.message === ""
        text: root.playing
          ? "Playback starts as soon as the next frame arrives."
          : "Warming the timeline. The first frames arrive in a few seconds."
        color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: Commons.Style.font.bodySmall
      }
      PText { width: parent.width; visible: root.message !== ""; text: root.message; color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: Commons.Style.font.bodySmall }
      PText { width: parent.width; visible: root.radar.stale === true; text: "Offline or outdated data · cached images"; color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: Commons.Style.font.bodySmall }
      RadarButton {
        objectName: "radar-legend-toggle"
        width: parent.width
        label: root.legendExpanded ? "Hide legend" : "Legend"
        accessibleLabel: root.legendExpanded ? "Hide the map legend" : "Show the map legend"
        Accessible.expandable: true
        Accessible.expanded: root.legendExpanded
        onClicked: root.legendExpanded = !root.legendExpanded
      }
      Image {
        objectName: "radar-legend"
        width: parent.width
        visible: root.legendExpanded
        source: root.legendSource
        sourceSize.width: 864
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        Accessible.role: Accessible.Graphic
        Accessible.name: root.legendDescription
      }
    }
  }
}
