import QtQuick
import QtQuick.Controls
import QtQuick.Window
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import qs.Ui as Ui
import "WeatherModel.js" as WeatherModel

Panel {
  id: root
  moduleName: "owee.weather"
  manageIpc: false
  readonly property string pluginVersion: "1.3.4"
  property string activePage: "weather"
  // The card height follows the active page: the hourly forecast on Weather
  // and the map on Radar, capped by the available screen height.
  readonly property real pageContentHeight: popup.loadedContent && popup.loadedContent.pageContentHeight !== undefined ? popup.loadedContent.pageContentHeight : Style.space(760)
  // Current city wind, shown on the wind map beside the DWD barbs.
  readonly property string windSummary: {
    var current = root.current
    if (!current || current.wind_speed_10m === undefined || current.wind_speed_10m === null
        || !isFinite(current.wind_speed_10m)) return ""
    return root.number(current.wind_speed_10m, " km/h") + " · " + WeatherModel.windOrigin(current.wind_direction_10m)
  }
  property bool measurementHelp: false
  property int openingSerial: 0
  onOpenedChanged: {
    if (opened) {prepareOpening();Qt.callLater(enrichVisibleCity)}
    else { searching=false; cancelSearch();if(airWorker.running)airWorker.running=false }
  }
  function showPage(page) {
    if (["weather","radar","settings"].indexOf(page)<0) return
    activePage=page
    searching=false
    suggestions=[]
    if(page!=="settings") editingCards=false
    var content=popup.ensureContent()
    if(content) content.resetForOpening()
    Qt.callLater(focusCurrentPage)
  }
  function showMapLayer(layer) {
    if (["rain","wind"].indexOf(layer)<0) return
    showPage("radar")
    var content=popup.ensureContent()
    var map=content?findItem(content,"radar-panel"):null
    if(map && typeof map.selectLayer==="function") map.selectLayer(layer)
    Qt.callLater(focusCurrentPage)
  }
  function focusCurrentPage() {
    var content=popup.loadedContent
    if (!content) return
    if (activePage==="radar") {
      var map=findItem(content,"radar-panel")
      if (map && typeof map.focusViewport==="function" && map.focusViewport()) return
    }
    content.forceActiveFocus()
  }
  function zoomRadar(delta) {
    var content = popup.loadedContent
    var map = content ? findItem(content, "radar-panel") : null
    if (!map || typeof map.zoomBy !== "function") return false
    map.zoomBy(delta)
    return true
  }
  function findItem(item,name) {
    if (!item) return null
    if (item.objectName===name) return item
    for (var i=0;item.children && i<item.children.length;i++) {
      var found=findItem(item.children[i],name)
      if (found) return found
    }
    return null
  }
  function prepareOpening() {
    activePage="weather"
    editingCards=false
    measurementHelp=false
    var content = popup.ensureContent()
    if (content) content.resetForOpening()
    openingSerial += 1
  }
  property var anchorItem: null
  property var hostWidget: null
  property var result: ({})
  property var suggestions: []
  property string errorText: ""
  property bool searching: false
  property string searchQuery: ""
  property string searchMessage: ""
  property bool searchBusy: false
  property bool searchInFlight: false
  property bool searchQueued: false
  property int searchRevision: 0
  onSearchingChanged: if (!searching) cancelSearch()
  property bool editingCards: false
  property bool loading: false
  property var pendingActions: []
  property string notificationFeedback: ""
  property var airEnvelope: ({})
  readonly property string viewedKey: cityKey(result.city)
  onViewedKeyChanged: { airEnvelope=({});if(airWorker.running)airWorker.running=false;Qt.callLater(enrichVisibleCity) }
  readonly property var current: result.data ? result.data.current : null
  readonly property var primaryWeather: result.primary || result
  readonly property var primaryCurrent: primaryWeather.data ? primaryWeather.data.current : null
  readonly property var primaryCity: result.primary_city || result.city || null
  readonly property string primaryCityName: primaryCity && primaryCity.name ? primaryCity.name : "Lyon"
  readonly property bool viewingPrimary: !!result.city && !!primaryCity && cityKey(result.city) === cityKey(primaryCity)
  readonly property var daily: result.data ? result.data.daily : null
  readonly property var hourly: result.data ? result.data.hourly : null
  readonly property var air: airEnvelope.city_key===viewedKey && airEnvelope.air ? airEnvelope.air : result.data && result.data.air ? result.data.air : ({})
  readonly property var cities: result.cities || []
  readonly property var cardOrder: result.cards || ["wind", "humidity", "uv", "sun", "pressure", "visibility", "precipitation", "air", "pollen"]
  readonly property var hiddenCards: result.hidden_cards || []
  readonly property bool autoRefresh: typeof setting("autoRefresh", null) === "boolean" ? setting("autoRefresh", true) : result.auto_refresh !== false
  readonly property string unit: temperatureMode === "system" ? (systemLocale.measurementSystem === Locale.ImperialUSSystem ? "F" : "C") : temperatureMode
  readonly property var notificationConfig: result.notifications || ({})
  readonly property string cityName: result.city && result.city.name ? result.city.name : "Lyon"
  readonly property string label: primaryCurrent ? icon(primaryCurrent.weather_code, primaryCurrent.is_day) + " " + weatherFormats.number(deg(primaryCurrent.temperature_2m)) + "°" : "☁ —"
  readonly property string barTemperature: primaryCurrent && typeof primaryCurrent.temperature_2m === "number" && isFinite(primaryCurrent.temperature_2m) ? weatherFormats.number(deg(primaryCurrent.temperature_2m)) + "°" : "—"
  readonly property color mutedText: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.72)
  readonly property color cardColor: Qt.rgba(Commons.Color.foreground.r, Commons.Color.foreground.g, Commons.Color.foreground.b, 0.075)
  readonly property color accentSoft: Qt.rgba(Commons.Color.accent.r, Commons.Color.accent.g, Commons.Color.accent.b, 0.16)
  readonly property string temperatureMode: ["C","F","system"].indexOf(setting("temperatureMode", "")) >= 0 ? setting("temperatureMode", "") : result.unit === "F" ? "F" : "C"
  readonly property string formatMode: setting("formatMode", "english") === "system" ? "system" : "english"
  readonly property var systemLocale: Qt.locale(Commons.I18n.formatLocale)
  WeatherFormats { id: weatherFormats; mode: root.formatMode }
  MotionCoordinator { id: openingMotion; active: root.opened; openingSerial: root.openingSerial }
  onSettingsChanged: Qt.callLater(syncBackendPreferences)
  onUnitChanged: Qt.callLater(syncBackendPreferences)
  onAutoRefreshChanged: Qt.callLater(syncBackendPreferences)
  onResultChanged: { Qt.callLater(seedNativePreferences); Qt.callLater(syncBackendPreferences) }

  function canPersistNativePreferences() {
    return bar && bar.shell && typeof bar.shell.updateEntryInline === "function"
  }
  function persistNativePreferences(values) {
    var entry = Object.assign({}, settings || {}, {id: moduleName}, values)
    if (canPersistNativePreferences()) bar.shell.updateEntryInline(moduleName, entry)
    settings = entry
    if (hostWidget) hostWidget.settings = entry
  }
  function seedNativePreferences() {
    if (!result.city || !result.unit || setting("preferencesVersion", 0) === 1 || !canPersistNativePreferences()) return
    var savedMode = setting("temperatureMode", "")
    var savedAuto = setting("autoRefresh", null)
    persistNativePreferences({preferencesVersion: 1,
      temperatureMode: ["C","F","system"].indexOf(savedMode)>=0 ? savedMode : result.unit === "F" ? "F" : "C",
      formatMode: setting("formatMode", "english") === "system" ? "system" : "english",
      autoRefresh: typeof savedAuto === "boolean" ? savedAuto : result.auto_refresh !== false})
  }
  function setTemperatureMode(value) {
    if (["C","F","system"].indexOf(value) >= 0) persistNativePreferences({temperatureMode:value})
  }
  function setFormatMode(value) {
    if (["english","system"].indexOf(value) >= 0) persistNativePreferences({formatMode:value})
  }
  function setAutoRefresh(value) { persistNativePreferences({autoRefresh:value === true}) }
  function syncBackendPreferences() {
    if (!result.city || !result.unit || worker.running || pendingActions.length) return
    if (result.unit !== unit) { run("unit",unit); return }
    if ((result.auto_refresh !== false) !== autoRefresh) run("auto",autoRefresh?"on":"off")
  }
  readonly property string scriptPath: decodeURIComponent(Qt.resolvedUrl("weather.py").toString().replace(/^file:\/\//, ""))

  function icon(code, day) {
    if (code === 0) return day === 0 ? "☾" : "☀"
    if (code <= 3) return "☁"
    if (code === 45 || code === 48) return "≋"
    if (code >= 95) return "ϟ"
    if ((code >= 71 && code <= 77) || code >= 85 && code <= 86) return "❄"
    if (code >= 51 && code <= 82) return "☂"
    return "☁"
  }
  function description(code) {
    return WeatherModel.description(code)
  }
  function deg(v) { return Math.round(unit === "F" ? v * 9 / 5 + 32 : v) }
  function degrees(arr, i) { return arr && arr[i] !== undefined && arr[i] !== null ? weatherFormats.number(deg(arr[i])) + "°" : "—" }
  function value(arr, i, suffix) { return arr && arr[i] !== undefined && arr[i] !== null ? weatherFormats.number(arr[i]) + suffix : "—" }
  function time(s) { return weatherFormats.cityTime(s) }
  function date(s) { var parts=weatherFormats.dateParts(s); return parts ? weatherFormats.locale.dayName(parts.weekday, Locale.ShortFormat) : "—" }
  function hourStart() {
    if (!hourly || !hourly.time || !current || !current.time) return 0
    if(typeof current.time_utc==="number" && Array.isArray(hourly.time_utc)) {
      for(var h=0;h<hourly.time_utc.length;h++)if(typeof hourly.time_utc[h]==="number"&&hourly.time_utc[h]>=current.time_utc)return h
    }
    var t = current.time
    for (var i=0; i<hourly.time.length; i++) if (hourly.time[i] >= t) return i
    return 0
  }
  function barDegrees() {
    return current && typeof current.temperature_2m==="number" && isFinite(current.temperature_2m) ? weatherFormats.number(deg(current.temperature_2m))+"°" : "—"
  }
  function freshness() {
    if (loading) return "Updating…"
    if (!result.updated) return "Waiting for data"
    return result.stale===true ? "Offline · "+weatherFormats.instant(result.updated) : "Updated at "+weatherFormats.instant(result.updated)
  }
  function bulletin() {
    var probabilities=hourly ? hourly.precipitation_probability : null
    var peak=null, start=hourStart()
    if(probabilities) for(var i=start;i<Math.min(start+6,probabilities.length);i++) {
      var v=probabilities[i]
      if(typeof v!=="number" || !isFinite(v)) continue
      peak=peak===null?v:Math.max(peak,v)
    }
    if(peak!==null) return "Next 6 hours · rain / snow chance up to "+weatherFormats.number(peak)+"%"
    var today=daily && daily.precipitation_probability_max ? daily.precipitation_probability_max[0] : null
    return typeof today==="number" && isFinite(today) ? "Precipitation chance today: "+weatherFormats.number(today)+" %" : "Additional forecast unavailable."
  }
  function cityKey(c) { return c && c.latitude != null && c.longitude != null ? Number(c.latitude).toFixed(5) + "," + Number(c.longitude).toFixed(5) : "" }
  function number(v, suffix) { return v === undefined || v === null || !isFinite(v) ? "—" : weatherFormats.number(v) + suffix }
  function pollenText() {
    var a = [air.alder_pollen, air.birch_pollen, air.grass_pollen, air.mugwort_pollen, air.olive_pollen, air.ragweed_pollen]
    var valid = a.filter(function(v) { return v !== null && v !== undefined && isFinite(v) })
    if (!valid.length) return "Unavailable"
    return number(Math.max.apply(null, valid), " grains/m³")
  }
  function sunProgress() {
    if (!current || current.is_day === 0 || !daily || !daily.sunrise || !daily.sunset) return NaN
    if(typeof current.time_utc==="number" && daily.sunrise_utc && daily.sunset_utc) {
      var rise=daily.sunrise_utc[0],set=daily.sunset_utc[0]
      return typeof rise==="number"&&typeof set==="number"&&set>rise?(current.time_utc-rise)/(set-rise):NaN
    }
    var sunrise = Date.parse(daily.sunrise[0]), sunset = Date.parse(daily.sunset[0]), now = Date.parse(current.time)
    return isFinite(sunrise) && isFinite(sunset) && isFinite(now) && sunset > sunrise ? (now-sunrise)/(sunset-sunrise) : NaN
  }
  function card(id) {
    var map = {
      wind: {title:"Wind", value:current ? number(current.wind_speed_10m, " km/h") : "—", detail:WeatherModel.windOrigin(current ? current.wind_direction_10m : null), direction:current ? current.wind_direction_10m : null},
      humidity: {title:"Humidity", value:current ? number(current.relative_humidity_2m," %") : "—", detail:"Moisture in the air", reading:current ? current.relative_humidity_2m : null},
      uv: {title:"UV index", value:daily ? value(daily.uv_index_max,0,"") : "—", detail:"Today’s peak · forecast", reading:daily && daily.uv_index_max ? daily.uv_index_max[0] : null},
      sun: {title:"Sunrise / sunset", value:daily && daily.solar_state && daily.solar_state[0]==="polar_night"?"Polar night":daily && daily.solar_state && daily.solar_state[0]==="polar_day"?"Polar day":(daily && daily.sunrise ? time(daily.sunrise[0]) : "—")+" / "+(daily && daily.sunset ? time(daily.sunset[0]) : "—"), detail:"City local time", progress:sunProgress()},
      pressure: {title:"Pressure", value:current ? number(current.surface_pressure," hPa") : "—", detail:"At ground level", reading:current ? current.surface_pressure : null},
      visibility: {title:"Visibility", value:hourly && hourly.visibility && hourly.visibility[hourStart()] != null ? weatherFormats.number(hourly.visibility[hourStart()]/1000,1) + " km" : "—", detail:"Viewing distance · forecast"},
      precipitation: {title:"Precipitation", value:current && typeof current.precipitation==="number" && isFinite(current.precipitation) && current.precipitation>=0 ? weatherFormats.number(current.precipitation,current.precipitation<10?1:0)+" mm" : "—", detail:"Recent rain / snow amount"},
      air: {title:"Air quality", value:number(air.european_aqi,""), detail:WeatherModel.airCategory(air.european_aqi)+" · EU AQI"},
      pollen: {title:"Pollen", value:pollenText(), detail:"Highest type · forecast"}
    }
    var info=map[id] || {title:id, value:"—", detail:""}
    info.explanation=WeatherModel.explanation(id)
    return info
  }
  function run(action, arg) {
    if (worker.running) {
      var queue = pendingActions.slice()
      // Periodic work may be coalesced; preference changes must keep their order.
      if (action === "load" || action === "notify")
        queue = queue.filter(function(item) { return item.action !== action })
      if (queue.length < 64) queue.push({action: action, arg: arg})
      pendingActions = queue
      return
    }
    loading = true
    worker.action = action
    worker.command = arg === undefined || arg === null ? ["python3", "-B", scriptPath, action] : ["python3", "-B", scriptPath, action, arg]
    worker.running = true
  }
  function refresh() { run("load",opened?undefined:"primary-only") }
  function enrichVisibleCity() {
    if(!opened || !result.city || !result.data || airWorker.running) return
    if(airEnvelope.city_key===viewedKey && airEnvelope.updated && Date.now()/1000-airEnvelope.updated<3600) return
    airWorker.requestKey=viewedKey
    airWorker.command=["python3","-B",scriptPath,"air",JSON.stringify(result.city)]
    airWorker.running=true
  }
  function queueSearch(query) {
    searchRevision += 1
    searchQuery=String(query).trim().slice(0,80)
    suggestions=[]
    searchMessage=""
    citySearchDelay.stop()
    searchQueued=searching && opened && searchQuery.length>=2
    searchBusy=searchQueued
    if(searchInFlight) citySearchWorker.running=false
    if(searchQueued) citySearchDelay.restart()
  }
  function cancelSearch() {
    searchRevision += 1
    citySearchDelay.stop()
    searchQuery=""
    searchQueued=false
    searchBusy=false
    searchMessage=""
    suggestions=[]
    if(searchInFlight) citySearchWorker.running=false
  }
  function startSearch() {
    if(!opened || !searching || searchQuery.length<2) return
    if(searchInFlight) return
    searchQueued=false
    searchInFlight=true
    citySearchWorker.revision=searchRevision
    citySearchWorker.query=searchQuery
    citySearchWorker.command=["python3","-B",scriptPath,"search",searchQuery]
    citySearchWorker.running=true
  }
  function search(query) {
    if(String(query).trim().slice(0,80)!==searchQuery) queueSearch(query)
    citySearchDelay.stop()
    if(searching && opened && searchQuery.length>=2 && !searchInFlight) {
      searchQueued=true; searchBusy=true; startSearch()
    }
  }
  function choose(item) { suggestions = []; searching = false; run("select", JSON.stringify(item)) }
  function chooseFavorite(item) {
    if (loading || !item) return
    searching = false
    suggestions = []
    if (activePage === "settings") showPage("weather")
    var content = popup.ensureContent()
    if (content) content.resetForOpening()
    if (cityKey(item) !== viewedKey) choose(item)
  }
  function open() { controller.show() }
  function toggle() { if (opened) close(); else open() }
  function close() { searching = false; suggestions = []; controller.hide() }
  function switchPanel(direction) { return bar && typeof bar.switchPanelFrom === "function" ? bar.switchPanelFrom(hostWidget || root, direction) : false }

  Process {
    id: worker
    property string action: ""
    onRunningChanged: if(running)weatherDeadline.restart();else weatherDeadline.stop()
    onExited: {
      if (!root.errorText) Qt.callLater(root.syncBackendPreferences)
      root.loading = false
      if (root.pendingActions.length) {
        var queue = root.pendingActions.slice()
        var next = queue.shift()
        root.pendingActions = queue
        Qt.callLater(function() { root.run(next.action, next.arg) })
      }
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.loading = false
        try {
          var parsed = JSON.parse(text)
          if (worker.action === "notify-test" || worker.action === "notify") {
            var status = parsed.notification_status || ({})
            if (worker.action === "notify-test") root.notificationFeedback = status.error || parsed.error || (status.sent ? "Test notification sent." : "Test notification unavailable.")
          } else if (parsed.error && !parsed.data) {
            root.errorText = parsed.error
            if (parsed.city) root.result = parsed
          } else {
            if(parsed.data && (!parsed.data.current || typeof parsed.data.current.temperature_2m!=="number" || !isFinite(parsed.data.current.temperature_2m) || !parsed.data.hourly || !Array.isArray(parsed.data.hourly.time) || parsed.data.hourly.time.length>500 || !parsed.data.daily || !Array.isArray(parsed.data.daily.time) || parsed.data.daily.time.length>20)) {
              root.errorText="Invalid weather response. Previous data is kept.";return
            }
            root.errorText = ""
            root.result = parsed
            Qt.callLater(root.enrichVisibleCity)
          }
        } catch (e) { root.errorText = "Weather data unavailable" }
      }
    }
  }
  Timer { id: weatherDeadline; interval: 30000; onTriggered: {worker.running=false;root.loading=false;root.errorText="Weather request timed out. Cached data is kept."} }
  Timer { id: airDeadline; interval: 12000; onTriggered: airWorker.running=false }
  Process {
    id: airWorker
    property string requestKey: ""
    onRunningChanged: if(running)airDeadline.restart();else airDeadline.stop()
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if(airWorker.requestKey!==root.viewedKey || !root.opened)return
        try {var data=JSON.parse(text);if(data.city_key===root.viewedKey&&data.air&&typeof data.air==="object"&&!Array.isArray(data.air))root.airEnvelope=data}catch(error){}
      }
    }
  }
  Timer { id: citySearchDelay; interval: 300; onTriggered: root.startSearch() }
  Process {
    id: citySearchWorker
    property int revision: -1
    property string query: ""
    onRunningChanged: if(running)searchDeadline.restart();else searchDeadline.stop()
    readonly property bool currentRequest: root.opened && root.searching && revision===root.searchRevision && query===root.searchQuery
    onExited: {
      root.searchInFlight=false
      if(root.searchQueued && !citySearchDelay.running) root.startSearch()
      else if(currentRequest && root.searchBusy && !root.searchQueued) {
        root.searchBusy=false
        root.searchMessage="Search unavailable. Please try again shortly."
      }
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if(!citySearchWorker.currentRequest) return
        root.searchBusy=false
        try {
          var parsed=JSON.parse(text)
          root.suggestions=Array.isArray(parsed.results)?parsed.results.slice(0,8):[]
          root.searchMessage=parsed.error?String(parsed.error).slice(0,200):(root.suggestions.length?"":"No cities found")
        } catch(error) {
          root.suggestions=[]
          root.searchMessage="Search unavailable. Please try again shortly."
        }
      }
    }
  }
  Timer { id: searchDeadline; interval: 12000; onTriggered: {citySearchWorker.running=false;root.searchBusy=false;root.searchMessage="Search timed out. Please try again."} }
  Component.onCompleted: root.refresh()
  Timer { interval: 900000; running: root.autoRefresh; repeat: true; onTriggered: root.refresh() }
  Timer { interval: 60000; running: root.autoRefresh && root.notificationConfig.enabled === true && root.primaryWeather.stale !== true; repeat: true; onTriggered: root.run("notify") }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    centerOnBar: false
    contentWidth: fittedContentWidth(Style.space(460))
    contentHeight: fittedContentHeight(root.pageContentHeight)
    focusTarget: popup.loadedContent
    content: FocusScope {
      id: scope
      implicitHeight: pageContentHeight
      function resetForOpening() { vertical.cancelFlick(); vertical.contentY = 0 }
      // Fit the card to the active page. Weather ends after the hourly
      // forecast; radar ends after the map. Other pages keep the old height.
      readonly property real pageContentHeight: {
        if (root.searching) return Style.space(760)
        if (root.activePage === "radar")
          return chrome.implicitHeight + Style.space(12) + radarPanel.implicitHeight + Style.space(8)
        if (root.activePage === "weather")
          return chrome.implicitHeight + Style.space(12) + heroSection.implicitHeight + weatherView.spacing + hourlySection.implicitHeight + Style.space(8)
        return Style.space(760)
      }
      function revealMeasurements() {
        vertical.cancelFlick()
        var top=measurementHeading.mapToItem(vertical,0,0).y+vertical.contentY
        vertical.contentY=Math.max(0,Math.min(Math.max(0,vertical.contentHeight-vertical.height),top))
      }
      Component.onCompleted: if (root.opened) resetForOpening()
      function textEntryFocused() {
        var item = scope.Window ? scope.Window.activeFocusItem : null
        while (item) {
          if (item.cursorPosition !== undefined || item.acceptableInput !== undefined) return true
          item = item.parent
        }
        return false
      }
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_PageDown) {
          vertical.contentY=Math.min(Math.max(0,vertical.contentHeight-vertical.height),vertical.contentY+vertical.height*0.8)
          event.accepted=true
          return
        }
        if (event.key === Qt.Key_PageUp) {
          vertical.contentY=Math.max(0,vertical.contentY-vertical.height*0.8)
          event.accepted=true
          return
        }
        if (root.searching || textEntryFocused()) return
        if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return
        var letter = event.text && event.text.length === 1 ? event.text.toUpperCase() : ""
        if (letter === "1") { root.showPage("weather"); event.accepted=true }
        else if (letter === "2") { root.showPage("radar"); event.accepted=true }
        else if (letter === "R") { root.showMapLayer("rain"); event.accepted=true }
        else if (letter === "W") { root.showMapLayer("wind"); event.accepted=true }
        else if (root.activePage === "radar" && (event.text === "+" || event.key === Qt.Key_Plus || event.key === Qt.Key_Equal)) {
          root.zoomRadar(1); event.accepted=true
        }
        else if (root.activePage === "radar" && (event.text === "-" || event.text === "−" || event.key === Qt.Key_Minus)) {
          root.zoomRadar(-1); event.accepted=true
        }
      }
      Keys.onEscapePressed: function(event) {
        if (root.searching) { root.searching=false; root.suggestions=[] }
        else if (root.activePage === "settings") root.showPage("weather")
        else root.close()
        event.accepted=true
      }
      Column {
        id: chrome
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        spacing: Style.space(8)
        Item {
          width: parent.width; height: Style.space(68)
          Column {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width-headerActions.width-Style.space(12))
            spacing: Style.space(3)
            PText { width: parent.width; text: "Viewing "+root.cityName; font.pixelSize: Style.font.heading; font.bold: true; elide: Text.ElideRight }
            Row {
              width: parent.width; spacing: Style.space(6)
              PText {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - (barCityAction.visible ? barCityAction.width + parent.spacing : 0))
                text: "Bar weather: "+root.primaryCityName
                color: root.mutedText; font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight
              }
              Ui.Button {
                id: barCityAction
                objectName: "use-in-bar"; text: "Use in bar"
                visible: !root.searching && !!root.result.city && !root.viewingPrimary
                enabled: !root.loading; focusable: true; bordered: true
                height: Style.space(24); fontSize: Style.font.bodySmall; horizontalPadding: Style.space(6)
                tooltipText: "Use the viewed city for bar weather and notifications"
                onClicked: root.run("primary",root.cityKey(root.result.city))
              }
            }
            PText {
              width: parent.width; text: root.freshness()
              color: root.result.stale === true ? Commons.Color.urgent : root.mutedText
              font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight
            }
          }
          Row {
            id: headerActions
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(8)
            Ui.Button {
              objectName: "open-cities"
              text: root.searching ? "Close" : "Cities"; focusable: true; bordered: true
              height: Style.space(34); fontSize: Style.font.bodySmall
              selected: root.searching
              Accessible.name: root.searching ? "Close city picker" : "Choose a city"
              onClicked: { root.searching=!root.searching; scope.resetForOpening(); if(root.searching) {cityInput.clear();Qt.callLater(function(){cityInput.forceActiveFocus()})} }
            }
            Ui.Button {
              objectName: "refresh-weather"
              width: Style.space(34); height: Style.space(34)
              focusable: true; bordered: true; enabled: !root.loading
              Accessible.name: "Refresh weather"
              tooltipText: root.loading ? "Updating weather…" : "Refresh weather · at most once per minute"
              MetricIcon { anchors.centerIn: parent; width: Style.space(18); height: width; kind: "refresh"; Accessible.ignored: true }
              onClicked: root.refresh()
            }
            Ui.Button {
              objectName: "nav-settings"
              width: Style.space(34); height: Style.space(34)
              focusable: true; bordered: true; selected: root.activePage === "settings"
              Accessible.name: "Weather settings"; tooltipText: "Weather settings"
              MetricIcon { anchors.centerIn: parent; width: Style.space(18); height: width; kind: "settings"; Accessible.ignored: true }
              onClicked: root.showPage(root.activePage === "settings" ? "weather" : "settings")
            }
          }
        }
        Item {
          width: parent.width; height: Style.space(38)
          Row {
            id: pageTabs
            spacing: Style.space(8)
            Ui.Button { objectName: "nav-weather"; text: "Weather"; height: Style.space(34); focusable: true; bordered: true; tooltipText: "Weather · 1"; selected: root.activePage === "weather" && !root.searching; onClicked: root.showPage("weather") }
            Ui.Button { objectName: "nav-radar"; text: "Radar"; height: Style.space(34); focusable: true; bordered: true; tooltipText: "Radar · 2"; selected: root.activePage === "radar" && !root.searching; onClicked: root.showPage("radar") }
          }
          FavoriteCities {
            objectName: "favorite-cities"
            anchors.left: pageTabs.right; anchors.leftMargin: Style.space(12)
            width: Math.max(0, parent.width-pageTabs.width-Style.space(12))
            cities: root.cities; currentCity: root.result.city; primaryCity: root.primaryCity; busy: root.loading
            onCitySelected: function(city) { root.chooseFavorite(city) }
          }
        }
        Rectangle { width: parent.width; height: 1; color: Commons.Color.foreground; opacity: 0.12 }
      }
      Flickable {
        id: vertical
        objectName: "weather-viewport"
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: chrome.bottom; anchors.topMargin: Style.space(12); anchors.bottom: parent.bottom
        clip: true; contentWidth: width; contentHeight: body.implicitHeight+Style.space(8)
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        Column {
          id: body
          width: vertical.width; spacing: Style.space(20)
          Column {
            width: parent.width; spacing: Style.space(12); visible: root.searching
            PText { text: "Change city"; font.pixelSize: Style.font.subtitle; font.bold: true }
            Ui.TextField {
              id: cityInput
              objectName: "city-input"
              width: parent.width
              placeholderText: "City or latitude, longitude"
              maximumLength: 80
              Accessible.name: "Search for a city"
              onTextEdited: root.queueSearch(text)
              onAccepted: root.search(text)
              Keys.onDownPressed: function(event) {
                if(root.suggestions.length && cityResults.itemAt(0)) {cityResults.itemAt(0).forceActiveFocus();event.accepted=true}
                else event.accepted=false
              }
            }
            PText { objectName: "city-search-status"; width: parent.width; text: root.searchQuery.length<2?"Type at least 2 characters.":root.searchBusy?"Searching…":root.searchMessage; visible: text!==""; font.pixelSize: Style.font.bodySmall; color: root.mutedText; wrapMode: Text.WordWrap }
            CityList {
              visible: root.searchQuery.length<2
              width: parent.width; cities: root.cities; currentCity: root.result.city || null; primaryCity: root.primaryCity; busy: root.loading
              onSelected: function(city) { root.choose(city) }
              onPrimaryRequested: function(key) { root.run("primary",key) }
              onMoveRequested: function(key,direction) { root.run("move-city",JSON.stringify({key:key,direction:direction})) }
              onRemoveRequested: function(key) { root.run("remove",key) }
            }
            PText { visible: root.suggestions.length>0; text: "Results"; font.pixelSize: Style.font.subtitle; font.bold: true }
            Repeater {
              id: cityResults
              model: root.suggestions
              delegate: Ui.Button {
                required property var modelData
                required property int index
                objectName: "city-result-"+index
                width: body.width; height: Style.space(44); focusable: true; bordered: true; leftAlign: true
                text: modelData.name + (modelData.admin1 ? ", " + modelData.admin1 : "") + (modelData.country ? ", " + modelData.country : "")
                onClicked: root.choose(modelData)
              }
            }
          }
          PText { width: parent.width; visible: root.errorText!==""; text: root.errorText; color: Commons.Color.urgent; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
          Column {
            id: weatherView
            width: parent.width; spacing: Style.space(20)
            visible: root.activePage === "weather" && !root.searching
            AnimatedSection {
              id: heroSection
              width: parent.width; progress: openingMotion.progress; start: 0
              Rectangle {
                id: hero
                objectName: "weather-hero"
                width: parent.width; height: Style.space(204)
                radius: Style.cornerRadius; color: root.accentSoft
                Column {
                  anchors.left: parent.left; anchors.leftMargin: Style.space(16)
                  anchors.top: parent.top; anchors.topMargin: Style.space(14)
                  width: parent.width*0.56; spacing: Style.space(3)
                  PText { width: parent.width; text: root.current ? "Now · "+root.description(root.current.weather_code) : root.loading ? "Refreshing…" : "Weather unavailable"; font.pixelSize: Style.font.subtitle; font.bold: true; elide: Text.ElideRight }
                  PText { text: root.barDegrees(); font.pixelSize: Style.font.displayLarge*2; font.weight: Font.Light }
                  PText { width: parent.width; text: root.current && root.current.apparent_temperature!=null ? "Feels like " + weatherFormats.number(root.deg(root.current.apparent_temperature)) + "°"+root.unit : "Feels-like temperature unavailable"; color: root.mutedText; font.pixelSize: Style.font.bodySmall }
                  PText { text: "Low " + root.degrees(root.daily?root.daily.temperature_2m_min:null,0) + "   High " + root.degrees(root.daily?root.daily.temperature_2m_max:null,0); color: root.mutedText; font.pixelSize: Style.font.bodySmall }
                }
                Sky {
                  anchors.right: parent.right; anchors.rightMargin: Style.space(12)
                  y: Style.space(8); width: Math.min(Style.space(172),parent.width*0.4); height: width*0.8
                  code: root.current ? root.current.weather_code : null
                  night: !!root.current && root.current.is_day===0
                  openingSerial: root.openingSerial
                  openingProgress: openingMotion.progress
                  active: root.opened && root.activePage === "weather" && !root.searching && weatherView.y+hero.y+hero.height>vertical.contentY && weatherView.y+hero.y<vertical.contentY+vertical.height
                }
                PText {
                  anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                  anchors.margins: Style.space(16); text: root.bulletin(); wrapMode: Text.WordWrap
                  maximumLineCount: 2; elide: Text.ElideRight; font.pixelSize: Style.font.bodySmall
                }
              }
            }
            AnimatedSection {
              id: hourlySection
              width: parent.width; progress: openingMotion.progress; start: 0.08
              HourlyForecast { objectName: "hourly-forecast"; width: parent.width; formats: weatherFormats; hourly: root.hourly; current: root.current; startIndex: root.hourStart(); unit: root.unit; stale: root.result.stale===true; scrollView: vertical }
            }
            AnimatedSection {
              width: parent.width; progress: openingMotion.progress; start: 0.16
              DailyForecast { objectName: "daily-forecast"; width: parent.width; formats: weatherFormats; daily: root.daily; hourly: root.hourly; currentDate: root.current && root.current.time ? String(root.current.time).slice(0,10) : ""; unit: root.unit; stale: root.result.stale===true }
            }
          }
          Column {
            width: parent.width; spacing: Style.space(16)
            visible: root.activePage === "radar" && !root.searching
            Radar {
              id: radarPanel
              objectName: "radar-panel"
              formats: weatherFormats; width: parent.width; city: Object.assign({},root.result.city || {},{timezone:root.result.data?root.result.data.timezone:""})
              windSummary: root.windSummary
              onWeatherRequested: root.showPage("weather")
              visible: true
              active: root.opened && root.activePage==="radar" && !root.searching
              preload: root.opened && root.activePage!=="radar" && !root.searching
            }
          }
          Column {
            width: parent.width; spacing: Style.space(16)
            visible: root.activePage==="settings" && !root.searching
            PText { text: "Settings"; font.pixelSize: Style.font.heading; font.bold: true }
            Ui.Toggle { width: parent.width; label: "Automatic refresh"; checked: root.autoRefresh; enabled: !root.loading; onClicked: root.setAutoRefresh(!root.autoRefresh) }
            Row {
              width: parent.width; spacing: Style.space(12)
              PText { anchors.verticalCenter: parent.verticalCenter; width: Math.max(0,parent.width-units.implicitWidth-Style.space(12)); text: "Temperatures"; font.pixelSize: Style.font.body }
              Ui.ButtonGroup { id: units; objectName: "unit-selector"; options: [{value:"system",label:"System"},{value:"C",label:"°C"},{value:"F",label:"°F"}]; value: root.temperatureMode; onChanged: function(value) {root.setTemperatureMode(value)} }
            }
            Row {
              width: parent.width; spacing: Style.space(12)
              PText { anchors.verticalCenter: parent.verticalCenter; width: Math.max(0,parent.width-formatsSelector.implicitWidth-Style.space(12)); text: "Date and number formats"; font.pixelSize: Style.font.body }
              Ui.ButtonGroup { id: formatsSelector; objectName: "format-selector"; options: [{value:"english",label:"English"},{value:"system",label:"System"}]; value: root.formatMode; onChanged: function(value) {root.setFormatMode(value)} }
            }
            PText { width: parent.width; text: "Interface stays in English. Forecast times follow the selected city."; color: root.mutedText; wrapMode: Text.WordWrap; font.pixelSize: Style.font.bodySmall }
            Ui.Button { objectName: "edit-cards"; text: root.editingCards?"Done customizing":"Customize cards"; focusable: true; bordered: true; onClicked: root.editingCards=!root.editingCards }
          }
          Column {
            width: parent.width; spacing: Style.space(10)
            visible: !root.searching && (root.activePage==="weather" || root.activePage==="settings" && root.editingCards)
            PText { id: measurementHeading; objectName: "measurements-heading"; width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.activePage==="settings"?"Visible cards and order":"Measurements"; font.pixelSize: Style.font.subtitle; font.bold: true }
            PText { width: parent.width; visible: root.airEnvelope.city_key===root.viewedKey ? root.airEnvelope.stale===true : !!root.result.data && root.result.data.air_stale===true; text: airWorker.running?"Air / pollen: updating separately…":"Air / pollen: cached or unavailable. Coverage varies by region."; color:root.mutedText; font.pixelSize:Style.font.bodySmall; wrapMode:Text.WordWrap }
            Ui.Button { objectName: "measurement-help"; text: root.measurementHelp?"Hide explanations":"Explain these measurements"; focusable: true; fontSize: Style.font.bodySmall; onClicked: {root.measurementHelp=!root.measurementHelp;Qt.callLater(scope.revealMeasurements)} }
            Column {
              width: parent.width; spacing: Style.space(10); visible: root.measurementHelp
              Repeater {
                model: root.cardOrder.filter(function(id){return root.hiddenCards.indexOf(id)<0})
                delegate: PText { required property string modelData; width: parent.width; text: root.card(modelData).title+": "+root.card(modelData).explanation; color: root.mutedText; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
              }
            }
            AnimatedSection {
              width: parent.width; progress: openingMotion.progress; start: 0.24
              WeatherCards {
                width: parent.width; order: root.cardOrder; hidden: root.hiddenCards
                editing: root.activePage==="settings" && root.editingCards
                busy: root.loading
                active: root.opened && !root.searching && (root.activePage==="weather" || root.activePage==="settings" && root.editingCards)
                scrollView: vertical
                cardInfo: function(id) {return root.card(id)}
                onReorderRequested: function(order) {root.run("cards",JSON.stringify({op:"reorder",order:order}))}
                onToggleRequested: function(id) {root.run("cards",JSON.stringify({op:"toggle",id:id}))}
              }
            }
          }
          Column {
            width: parent.width; spacing: Style.space(16)
            visible: root.activePage==="settings" && !root.searching
            NotificationSettings {
              width: parent.width; embedded: true
              config: root.notificationConfig; primaryCityName: root.primaryCityName; busy: root.loading; feedback: root.notificationFeedback
              onChanged: function(patch) {root.run("notifications",JSON.stringify(patch))}
              onTestRequested: {root.notificationFeedback="Sending…";root.run("notify-test")}
            }
            PText { width: parent.width; text: "OWEE " + root.pluginVersion; color: root.mutedText; font.pixelSize: Style.font.bodySmall }
            PText { width: parent.width; text: "Weather: Open-Meteo · Air: CAMS ENSEMBLE"; color: root.mutedText; font.pixelSize: Style.font.bodySmall; wrapMode: Text.WordWrap }
          }
        }
      }
    }
  }
}
