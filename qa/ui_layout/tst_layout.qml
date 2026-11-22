import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import qs.Commons as Commons
import "plugin" as Weather
import "plugin/WeatherModel.js" as WeatherModel

ShellRoot {
  id: suite
  property int checks: 0
  property int step: 0
  property int attempts: 0
  property var p: null
  property var scope: null
  property var viewport: null
  property var hourly: null
  property var daily: null
  property var previousChart: null
  property real previousX: 0
  property real previousY: 0
  property int zoomBeforeKeys: 0
  property bool legendShot: false
  property int legendWait: 0
  property string output: @@OUTPUT@@
  function check(ok, message) {
    if (!ok) throw new Error("QA_FAIL: " + message)
    checks++
    console.warn("QA_UI_CHECK", checks, message)
  }
  function find(item, name) {
    if (!item) return null
    if (item.objectName === name) return item
    for (var i=0; item.children && i<item.children.length; i++) {
      var found=find(item.children[i],name)
      if (found) return found
    }
    return null
  }
  function findCanvas(item) {
    if (!item) return null
    if (item instanceof Canvas) return item
    for (var i=0; item.children && i<item.children.length; i++) {
      var found=findCanvas(item.children[i]); if(found) return found
    }
    return null
  }
  function hasText(item, value) {
    if (!item) return false
    if (typeof item.text === "string" && item.text === value) return true
    for(var i=0;item.children&&i<item.children.length;i++) if(hasText(item.children[i],value)) return true
    return false
  }
  function findButton(item, text) {
    if (!item) return null
    if (typeof item.clicked === "function" && item.text === text) return item
    for(var i=0;item.children&&i<item.children.length;i++) {var v=findButton(item.children[i],text);if(v)return v}
    return null
  }
  function symbols(item) {
    if(!item)return 0
    var n=String(item).indexOf("WeatherMark")>=0?1:0
    for(var i=0;item.children&&i<item.children.length;i++)n+=symbols(item.children[i])
    return n
  }
  function plain(item) {
    if(!item)return true
    // Native buttons forward their text to a PlainText child; inspect actual renderers.
    if(item instanceof Text&&typeof item.text==="string"&&item.text.indexOf("<img")>=0&&item.textFormat!==Text.PlainText)return false
    for(var i=0;item.children&&i<item.children.length;i++)if(!plain(item.children[i]))return false
    return true
  }
  function click(item) {
    check(!!item,"click target exists")
    var layout=item.parent
    while(layout) {
      if(typeof layout.forceLayout === "function")layout.forceLayout()
      layout=layout.parent
    }
    var parent=item.parent
    while(parent&&parent!==viewport)parent=parent.parent
    if(parent===viewport) {
      viewport.cancelFlick()
      var point=item.mapToItem(viewport,0,0)
      if(point.y<0)viewport.contentY=Math.max(0,viewport.contentY+point.y)
      else if(point.y+item.height>viewport.height)viewport.contentY=Math.min(Math.max(0,viewport.contentHeight-viewport.height),viewport.contentY+point.y+item.height-viewport.height)
    }
    check(events.mouseClick(item,item.width/2,item.height/2,Qt.LeftButton,Qt.NoModifier,1),"real Qt click delivered")
  }
  function capture(name, after) {
    stage.grabToImage(function(result) {
      check(result.saveToFile(suite.output+"/"+name+".png"),"saved "+name)
      if(after)after()
    })
  }
  function finiteGeometry(item) {
    if(!item)return true
    if(!isFinite(item.x)||!isFinite(item.y)||!isFinite(item.width)||!isFinite(item.height))return false
    if(typeof item.text==="string"&&(item.text.indexOf("NaN")>=0||item.text.indexOf("Infinity")>=0))return false
    for(var i=0;item.children&&i<item.children.length;i++)if(!finiteGeometry(item.children[i]))return false
    return true
  }
  Window {
    id: window
    visible:true; width:460; height:760
    color:Qt.rgba(Commons.Color.background.r,Commons.Color.background.g,Commons.Color.background.b,1)
    Rectangle { id:stage; x:14;y:14;width:parent.width-28;height:parent.height-28;color:window.color }
    Item {
      id:probes
      x:14;y:14;width:parent.width-28;height:parent.height-28;visible:false
      Column {
        width:parent.width;spacing:20
        Weather.HourlyForecast {id:edgeHourly;width:parent.width}
        Weather.DailyForecast {id:edgeDaily;width:parent.width}
        Weather.RainTimeline {id:timezoneTimeline;width:parent.width}
      }
    }
    TestEvent {id:events}
    TestResult {id:images}
  }
  Loader {id:panelLoader;source:Qt.resolvedUrl("plugin/Panel.qml")}
  Timer {
    interval:180;repeat:true;running:true
    onTriggered: {
      try {
        if(step===0) {
          attempts++
          if(!panelLoader.item || !panelLoader.item.result.data || !panelLoader.item.qaScope) {
            if(attempts>35)throw new Error("QA_FAIL: panel did not initialize")
            return
          }
          p=panelLoader.item;scope=p.qaScope;scope.parent=stage;scope.width=stage.width;scope.height=stage.height;scope.visible=true
          Commons.Style.reduceMotion=true
          p.open();window.requestActivate()
          step=900;return
        }
        if(step===900) {
          if(p.loading)return
          viewport=find(scope,"weather-viewport")
          var refresh=find(scope,"refresh-weather"),settings=find(scope,"nav-settings")
          check(!!refresh&&refresh.visible&&refresh.enabled,"manual refresh is available in the fixed header")
          check(refresh.parent===settings.parent&&refresh.width===settings.width&&refresh.height===settings.height,"refresh matches Settings size and action row")
          check(Math.abs(settings.x-refresh.x-refresh.width-Commons.Style.space(8))<0.1,"refresh sits directly beside Settings")
          var position=refresh.mapToItem(stage,0,0)
          check(position.x>=0&&position.y>=0&&position.x+refresh.width<=stage.width&&position.y+refresh.height<=stage.height,"refresh fits inside the panel viewport")
          step=901
          click(refresh)
          check(p.loading&&!refresh.enabled,"mouse refresh starts the worker and disables repeated activation")
          events.mouseClick(refresh,refresh.width/2,refresh.height/2,Qt.LeftButton,Qt.NoModifier,1)
          check(p.pendingActions.length===0,"clicking while busy does not queue another refresh")
          return
        }
        if(step===901) {
          if(p.loading)return
          var keyboardRefresh=find(scope,"refresh-weather")
          check(keyboardRefresh.enabled&&p.activePage==="weather"&&p.cityName==="Paris"&&p.primaryCityName==="Lyon","refresh restores the control without changing the page or either city")
          keyboardRefresh.forceActiveFocus()
          step=902
          check(events.keyClick(Qt.Key_Return,Qt.NoModifier,1),"keyboard refresh activation delivered")
          check(p.loading&&!keyboardRefresh.enabled,"keyboard refresh uses the same busy state")
          return
        }
        if(step===902) {
          if(p.loading)return
          check(find(scope,"refresh-weather").enabled,"refresh is available again after keyboard loading completes")
          step=1;return
        }
        if(step===1) {
          viewport=find(scope,"weather-viewport");hourly=find(scope,"hourly-forecast");daily=find(scope,"daily-forecast")
          check(p.activePage==="weather","opening lands on Weather")
          check(p.opened,"test panel lifecycle open")
          check(!!viewport&&!!hourly&&!!daily,"forecast sections available")
          var hourlyBottom=hourly.mapToItem(scope,0,0).y+hourly.height
          var dailyTop=daily.mapToItem(scope,0,0).y
          check(Math.abs(p.pageContentHeight-(hourlyBottom+Commons.Style.space(8)))<1,"weather card ends after the hourly forecast")
          check(p.pageContentHeight<dailyTop,"weather card keeps the daily forecast below the fold")
          check(!p.qaRadar.active,"radar inactive on weather page")
          check(p.cityName==="Paris"&&p.primaryCityName==="Lyon"&&p.barTemperature==="3°","consulted and primary cities remain separate")
          check(hourly.samples.length===24&&daily.days.length===10,"24 hours and 10 days remain available")
          check(hasText(scope,"Weather")&&hasText(scope,"Radar")&&p.description(3)==="Overcast","English navigation and weather conditions")
          check(daily.days[0].label==="Today"&&p.date("2026-11-16")==="Mon","English day names independent of desktop language")
          check(daily.days[1].label==="Tomorrow"&&hasText(daily,"Low 3°C")&&hasText(daily,"High 12°C"),"daily forecast explains days and temperature bounds")
          check(hasText(daily,"00:00")&&hasText(daily,"12:00")&&hasText(daily,"24:00")&&hasText(daily,"Rain / snow chance by hour · city local time"),"daily timeline names local hours and midnight endpoints")
          check(daily.days[0].hours[19]===75&&daily.days[0].hours[0]===10&&daily.days[1].hours[23]===null&&daily.days[2].hours.length===0,"daily timeline uses city hourly forecasts and preserves missing horizon data")
          var mapped=WeatherModel.rainHours({time:["2026-01-02T00:00","2026-01-01T01:00","2026-01-01T01:00","2026-01-01T06:00","2026-01-01T08:00","2026-13-01T02:00"],precipitation_probability:[90,0,70,null,0,100]})
          check(mapped["2026-01-01"][23]===90&&mapped["2026-01-01"][0]===70&&mapped["2026-01-01"][5]===null&&mapped["2026-01-01"][7]===0&&!mapped["2026-13-01"],"rain periods respect preceding-hour semantics, midnight, repeated clock labels and missing values")
          var tenDays={time:[],precipitation_probability:[]}
          for(var h=0;h<=240;h++){tenDays.time.push(new Date(Date.UTC(2026,0,1)+h*3600000).toISOString().slice(0,16));tenDays.precipitation_probability.push(h===240?90:0)}
          check(WeatherModel.rainHours(tenDays)["2026-01-10"][23]===90&&WeatherModel.rainInterval("2026-01-01T00:00").date==="2025-12-31","last forecast day and year boundary keep their correct rain intervals")
          check(hourly.precipitationSummary.indexOf("Bars: rain / snow chance · peak 75%")===0,"hourly bars have a named quantity and calculated peak")
          check(hourly.precipitationSummary.indexOf("19:00–20:00")>=0,"hourly and daily views agree on the actual peak rain interval")
          check(hasText(scope,"Viewing Paris")&&hasText(scope,"Bar weather: Lyon"),"viewed city and bar city have explicit roles")
          check(p.card("air").detail==="Fair · EU AQI"&&p.card("precipitation").value==="0.1 mm","measurements explain AQI category and keep small precipitation amounts")
          check(WeatherModel.airCategory(0)==="Good"&&WeatherModel.airCategory(20)==="Good"&&WeatherModel.airCategory(20.1)==="Fair"&&WeatherModel.airCategory(40.1)==="Moderate"&&WeatherModel.airCategory(60.1)==="Poor"&&WeatherModel.airCategory(80.1)==="Very poor"&&WeatherModel.airCategory(100.1)==="Extremely poor"&&WeatherModel.airCategory(null)==="Unavailable","provider AQI categories and missing values remain distinct")
          check(symbols(hourly)>=24&&symbols(daily)>=5,"Horizon drawings in both forecast sections")
          check(!hasText(hourly,"Maint.")&&hasText(hourly,hourly.samples[0].time),"forecast timestamps remain distinct from current weather")
          check(!daily.showAll,"daily list starts compact")
          var firstBar=find(hourly,"hourly-precipitation-0"), secondBar=find(hourly,"hourly-precipitation-1")
          var temperature=find(hourly,"hourly-temperature-0")
          check(firstBar.width===Commons.Style.space(16)&&firstBar.height===Commons.Style.space(28)&&Math.abs(secondBar.mapToItem(hourly,0,0).x-firstBar.mapToItem(hourly,0,0).x-firstBar.width-Commons.Style.space(40))<0.1,"compact precipitation bars keep a regular gap and hourly alignment")
          check(firstBar.y-temperature.y-temperature.height>=Commons.Style.space(20),"temperature has extra space above precipitation bars")
          check(!findCanvas(hourly),"continuous temperature curve replaced by precipitation columns")
          var heading=find(scope,"measurements-heading"), humidityValue=find(p.qaCards,"value-humidity")
          check(heading.horizontalAlignment===Text.AlignHCenter&&humidityValue.horizontalAlignment===Text.AlignHCenter,"measurement heading and values are centered")
          check(find(p.qaCards,"visual-humidity").reading===p.current.relative_humidity_2m&&find(p.qaCards,"visual-wind").direction===p.current.wind_direction_10m,"measurement graphics receive current city readings")
          step=1000
          capture("weather", function() {
            viewport.contentY=Math.min(viewport.contentHeight-viewport.height,heading.mapToItem(viewport,0,0).y+viewport.contentY)
            step=1001
          })
          return
        }
        if(step===1001) {
          step=1002
          capture("measurements", function() {
            viewport.contentY=0
            previousX=find(hourly,"hourly-strip").contentX;previousY=viewport.contentY
            var strip=find(hourly,"hourly-strip")
            check(events.mouseWheel(strip,50,20,Qt.NoButton,Qt.NoModifier,0,-120,1),"vertical wheel event delivered over hourly strip")
            step=2
          })
          return
        }
        if(step===2) {
          check(find(hourly,"hourly-strip").contentX===previousX,"vertical wheel does not move hourly strip horizontally")
          check(viewport.contentY>previousY,"vertical wheel continues page scrolling")
          scope.forceActiveFocus()
          previousY=viewport.contentY
          check(events.keyClick(Qt.Key_PageDown,Qt.NoModifier,1),"PageDown delivered")
          check(viewport.contentY>previousY,"PageDown scrolls the panel")
          previousY=viewport.contentY
          check(events.keyClick(Qt.Key_PageUp,Qt.NoModifier,1),"PageUp delivered")
          check(viewport.contentY<previousY,"PageUp scrolls back")
          viewport.contentY=0
          click(find(hourly,"hourly-next"));step++;return
        }
        if(step===3) {
          check(find(hourly,"hourly-strip").contentX>0,"hourly arrow scrolls forecast")
          find(hourly,"hourly-strip").forceActiveFocus();previousX=find(hourly,"hourly-strip").contentX
          check(events.keyClick(Qt.Key_Right,Qt.NoModifier,1),"hourly keyboard event delivered")
          step++;return
        }
        if(step===4) {
          check(find(hourly,"hourly-strip").contentX>previousX,"keyboard arrow moves hourly forecast")
          click(find(daily,"daily-expand"))
          check(daily.showAll,"daily expansion exposes all ten days")
          click(find(daily,"daily-expand"))
          check(!daily.showAll,"daily list collapses again")
          var timeline=find(daily,"daily-rain-0")
          click(find(timeline,"rain-hour-band"))
          check(timeline.selectedHour===12&&timeline.detail==="12:00–13:00 · 45% chance","daily timeline pointer reveals the selected hour and probability")
          check(events.keyClick(Qt.Key_Right,Qt.NoModifier,1)&&timeline.selectedHour===13,"daily timeline arrow key explores the next hour")
          check(events.keyClick(Qt.Key_Home,Qt.NoModifier,1)&&timeline.selectedHour===0&&timeline.detail==="00:00–01:00 · 10% chance","daily timeline Home reaches midnight")
          check(events.keyClick(Qt.Key_End,Qt.NoModifier,1)&&timeline.selectedHour===23&&timeline.detail==="23:00–24:00 · 0% chance","daily timeline End reaches the final hour without changing day")
          timeline.selectedHour=-1;timeline.focus=false;scope.forceActiveFocus()
          viewport.contentY=Math.min(viewport.contentHeight-viewport.height,daily.mapToItem(viewport,0,0).y+viewport.contentY)
          step=400
          capture("daily",function(){click(find(scope,"nav-radar"));step=5})
          return
        }
        if(step===5) {
          check(p.activePage==="radar"&&p.qaRadar.mapLayer==="rain","Radar opens rain view")
          check(find(scope,"refresh-weather").visible,"manual refresh remains visible on Radar")
          check(p.qaRadar.active,"radar map active in rain view")
          var radarBottom=p.qaRadar.mapToItem(scope,0,0).y+p.qaRadar.height
          check(Math.abs(p.pageContentHeight-(radarBottom+Commons.Style.space(8)))<1,"radar card ends after the map")
          check(viewport.contentY===0,"navigation resets scroll")
          step=50;return
        }
        if(step===50) {
          if(p.qaRadar.busy||!p.qaRadar.imageReady||p.qaRadar.frames.length<2)return
          check(!p.qaRadar.playing,"radar opens paused")
          check(p.qaRadar.frameIndex===p.qaRadar.frames.length-1,"radar opens at the present observation")
          capture("radar-rain", function(){})
          var zoomIn=find(p.qaRadar,"radar-zoom-in"),zoomBefore=p.qaRadar.zoom
          click(zoomIn)
          check(p.qaRadar.zoom===zoomBefore+1,"zoom control changes the radar level")
          step++;return
        }
        if(step===51) {
          if(p.qaRadar.busy||!p.qaRadar.imageReady||p.qaRadar.frames.length<2)return
          var map=find(p.qaRadar,"radar-viewport")
          check(!!map&&map.activeFocus,"a clicked zoom control returns focus to the map")
          var wasPlaying=p.qaRadar.playing,zoomAfterFocus=p.qaRadar.zoom
          check(events.keyClick(Qt.Key_Space,Qt.NoModifier,1),"Space reaches the map after a control click")
          check(p.qaRadar.zoom===zoomAfterFocus,"Space does not reactivate the clicked control")
          if(Commons.Style.duration(1)>0)check(p.qaRadar.playing!==wasPlaying,"Space controls radar playback after a control click")
          zoomBeforeKeys=p.qaRadar.zoom
          check(events.keyClick(Qt.Key_Minus,Qt.NoModifier,1),"minus key delivered")
          check(p.qaRadar.zoom===zoomBeforeKeys-1,"minus key zooms the radar out")
          var legend=find(p.qaRadar,"radar-legend")
          check(!!legend&&!legend.visible,"the radar legend starts hidden")
          click(find(p.qaRadar,"radar-legend-toggle"))
          check(!!legend&&legend.visible,"the Legend button shows the legend picture")
          check(String(legend.source).indexOf("legend-rain.png")>=0,"the rain legend uses the rain picture")
          viewport.contentY=Math.max(0,viewport.contentHeight-viewport.height)
          step=53;return
        }
        if(step===53) {
          // Let the decoded legend grow the content before pinning the bottom.
          viewport.contentY=Math.max(0,viewport.contentHeight-viewport.height)
          legendWait++
          if(legendWait<3)return
          if(!legendShot) {legendShot=true;capture("radar-legend", function(){step=52})}
          return
        }
        if(step===52) {
          if(p.qaRadar.busy||!p.qaRadar.imageReady||p.qaRadar.frames.length<2)return
          check(events.keyClick(Qt.Key_Plus,Qt.ShiftModifier,1),"plus key delivered")
          check(p.qaRadar.zoom===zoomBeforeKeys,"plus key zooms the radar in")
          p.showMapLayer("wind");step=6;return
        }
        if(step===6) {
          if(p.qaRadar.mapLayer!=="wind")return
          check(p.qaRadar.mapLayer==="wind"&&p.qaRadar.active,"switching layer keeps one active map")
          check(String(find(p.qaRadar,"radar-legend").source).indexOf("legend-wind.png")>=0,"the wind legend uses the wind picture")
          capture("radar-wind", function(){click(find(scope,"nav-settings"))});step++;return
        }
        if(step===7) {
          check(p.activePage==="settings"&&!p.qaRadar.active,"Settings keeps the radar inactive")
          check(find(scope,"refresh-weather").visible,"manual refresh remains visible in Settings")
          capture("settings", function(){click(findButton(find(scope,"unit-selector"),"°F"))});step++;return
        }
        if(step===8) {
          if(p.loading)return
          check(p.unit==="F","native unit control updates preference through fixture process")
          click(find(scope,"edit-cards"));step++;return
        }
        if(step===9) {
          check(p.editingCards&&p.qaCards.editing&&p.qaCards.active,"shared cards enter editing in settings")
          click(find(scope,"open-cities"));step++;return
        }
        if(step===10) {
          check(p.searching&&!p.qaRadar.active,"city view suspends the radar")
          check(find(scope,"refresh-weather").visible,"manual refresh remains visible in the city picker")
          check(plain(scope),"markup-shaped city name remains plain text")
          capture("cities", function(){p.searching=false;p.showPage("radar");viewport.contentY=100;p.prepareOpening()});step++;return
        }
        if(step===11) {
          check(p.activePage==="weather"&&viewport.contentY===0&&!p.editingCards,"opening resets view, scroll and editor")
          p.close();check(!p.qaRadar.active&&!p.qaCards.active,"closing stops page activity")
          scope.visible=false;probes.visible=true
          edgeHourly.hourly={};edgeDaily.daily={};step++;return
        }
        if(step===12) {
          check(edgeHourly.samples.length===0&&edgeDaily.days.length===0,"missing forecasts show safe empty state")
          check(edgeHourly.precipitationSummary==="Rain / snow chance unavailable"&&WeatherModel.description(null)==="Weather unavailable","missing forecasts do not invent a peak or clear weather")
          check(finiteGeometry(probes),"missing data has finite geometry")
          edgeHourly.hourly={time:["2026-11-14T08:00","2026-11-14T09:00","2026-11-14T10:00"],temperature_2m:[-10,null,10],weather_code:[0,3,61],is_day:[1,1,0],precipitation_probability:[0,null,80]}
          edgeDaily.daily={time:["2026-11-14","2026-11-15","2026-11-16"],temperature_2m_min:[-5,null,0],temperature_2m_max:[5,10,0],weather_code:[3,61,0],precipitation_probability_max:[0,50,80]}
          step++;return
        }
        if(step===13) {
          check(edgeHourly.samples[0].temperature===-10&&edgeHourly.samples[1].temperature===null,"negative and missing hourly temperatures preserved")
          check(edgeHourly.samples[0].probability===0,"zero precipitation probability preserved")
          check(find(edgeHourly,"hourly-precipitation-fill-0").height===0&&find(edgeHourly,"hourly-precipitation-fill-1").height===0,"zero and missing precipitation do not invent a bar")
          check(Math.abs(find(edgeHourly,"hourly-precipitation-fill-2").height/find(edgeHourly,"hourly-precipitation-2").height-0.8)<0.001,"precipitation height follows probability rather than temperature")
          check(edgeDaily.days[1].low===null&&edgeDaily.days[2].low===0&&edgeDaily.days[2].high===0,"missing and equal daily bounds preserved")
          check(finiteGeometry(probes),"equal and missing daily ranges have finite geometry")
          edgeHourly.unit="F";edgeDaily.unit="F";step++;return
        }
        if(step===14) {
          check(edgeHourly.samples[0].temperature===14&&edgeHourly.samples[2].temperature===50,"hourly Fahrenheit conversion")
          check(edgeDaily.days[0].low===23&&edgeDaily.days[0].high===41&&edgeDaily.days[2].high===32,"daily Fahrenheit conversion")
          check(hasText(edgeHourly,"14°")&&hasText(edgeDaily,"High 32°F"),"converted values actually displayed")
          edgeHourly.hourly={time:["2026-11-14T08:00","2026-11-14T09:00","2026-11-14T10:00"],temperature_2m:[0,5,0],weather_code:[0,3,61],is_day:[1,1,0],precipitation_probability:[0,20,80]}
          step++;return
        }
        if(step===15) {
          step=150
          find(edgeHourly,"hourly-precipitation-1").grabToImage(function(result) {
            check(result.saveToFile(suite.output+"/precipitation-before.png"),"saved first precipitation bar")
            edgeHourly.hourly={time:["2026-11-14T08:00","2026-11-14T09:00","2026-11-14T10:00"],temperature_2m:[0,5,0],weather_code:[0,3,61],is_day:[1,1,0],precipitation_probability:[0,80,80]}
            step=16
          })
          return
        }
        if(step===16) {
          step=160
          find(edgeHourly,"hourly-precipitation-1").grabToImage(function(result) {
            check(result.saveToFile(suite.output+"/precipitation-after.png"),"saved changed precipitation bar")
            edgeHourly.hourly={time:["2026-11-14T23:00","2026-11-15T00:00"],temperature_2m:[10,10],weather_code:[3,61],precipitation_probability:[10,80]}
            edgeDaily.daily={time:["2026-11-14"],temperature_2m_min:[0],temperature_2m_max:[0],weather_code:[0],precipitation_probability_max:[0]}
            edgeDaily.hourly={time:["2026-11-15T00:00"],precipitation_probability:[90]}
            step=17
          })
          return
        }
        if(step===17) {
          var repeated={rain_intervals:[{date:"2026-11-01",hour:1,start_local:"2026-11-01T01:00",end_local:"2026-11-01T01:00",start_offset:-14400,end_offset:-18000,probability:70},{date:"2026-11-01",hour:1,start_local:"2026-11-01T01:00",end_local:"2026-11-01T02:00",start_offset:-18000,end_offset:-18000,probability:40}]}
          timezoneTimeline.hours=WeatherModel.rainHours(repeated)["2026-11-01"];timezoneTimeline.hourDetails=WeatherModel.rainDetails(repeated)["2026-11-01"];timezoneTimeline.selectedHour=1
          check(timezoneTimeline.hours[1]===70&&timezoneTimeline.detail.indexOf("UTC−04:00")>=0&&timezoneTimeline.detail.indexOf("UTC−05:00")>=0&&timezoneTimeline.detail.indexOf("40%")>=0,"repeated clock hours keep both probabilities and UTC offsets")
          var skipped={rain_intervals:[{date:"2026-03-29",hour:1,start_local:"2026-03-29T01:00",end_local:"2026-03-29T03:00",start_offset:3600,end_offset:7200,probability:80}]}
          timezoneTimeline.hours=WeatherModel.rainHours(skipped)["2026-03-29"];timezoneTimeline.hourDetails=WeatherModel.rainDetails(skipped)["2026-03-29"];timezoneTimeline.selectedHour=2
          check(timezoneTimeline.hours[2]===null&&timezoneTimeline.detail.indexOf("skipped by clock change")>=0,"a nonexistent local hour is identified rather than guessed dry")
          check(edgeDaily.days[0].low===edgeDaily.days[0].high&&finiteGeometry(edgeDaily),"equal daily temperatures remain valid without a temperature range bar")
          check(edgeDaily.days[0].hours[23]===90,"daily timeline receives a new hourly dataset")
          edgeDaily.hourly={time:["2026-11-14T10:00"],precipitation_probability:[0]}
          check(edgeDaily.days[0].hours[9]===0&&edgeDaily.days[0].hours[23]===null,"hourly refresh updates the daily timeline without preserving obsolete rain")
          check(edgeHourly.precipitationSummary.indexOf("peak 80% · 23:00–24:00")>=0,"rain probability at midnight covers the final hour of the preceding day")
          edgeHourly.stale=true
          check(edgeHourly.precipitationSummary.indexOf("tomorrow")<0&&edgeHourly.precipitationSummary.indexOf("Sat 14 Nov")>=0,"cached peak uses the actual interval date rather than its end timestamp date")
          edgeHourly.hourly={time:["2026-11-14T23:00"],temperature_2m:[10],precipitation_probability:[0]}
          check(edgeHourly.precipitationSummary==="Bars: rain / snow chance · 0% in available hours","zero chance stays distinct from unavailable data")
          probes.grabToImage(function(result){check(result.saveToFile(suite.output+"/edge-cases.png"),"saved edge-cases")})
          step++;return
        }
        if(step===18) {
          probes.visible=false;scope.visible=true;p.open();step++;return
        }
        if(step===19) {
          click(find(scope,"measurement-help"));step++;return
        }
        if(step===20) {
          check(p.measurementHelp&&hasText(scope,"Wind: "+p.card("wind").explanation),"native help button explains the visible measurements")
          step=2000
          capture("measurement-help",function(){click(find(scope,"measurement-help"));step=21})
          return
        }
        if(step===21) {
          check(!p.measurementHelp,"measurement explanations collapse without changing cards")
          click(find(scope,"use-in-bar"));step++;return
        }
        if(step===22) {
          if(p.loading)return
          check(p.viewingPrimary&&p.primaryCityName==="Paris"&&p.primaryCurrent.temperature_2m===22,"Use in bar updates the primary city through the fixture backend")
          check(!find(scope,"use-in-bar").visible&&hasText(scope,"Bar weather: Paris"),"city role and action update after choosing bar city")
          console.warn("QA_UI_LAYOUT_PASS",checks,"checks; real Quickshell controls, mouse, keyboard, wheel and captures")
          Qt.quit()
        }
      } catch(error) {console.error(error.message);Qt.exit(1)}
    }
  }
}
