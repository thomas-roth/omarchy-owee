import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import "plugin" as Weather

ShellRoot {
  id: suite
  property var fixtures: @@FIXTURES@@
  property int step: 0
  property int attempts: 0
  property int forecastRequests: 0
  function check(ok, message) { if(!ok)throw new Error("QA_COVERAGE_FAIL: "+message) }
  function find(item, name) {
    if(!item)return null
    if(item.objectName===name)return item
    for(var i=0;item.children&&i<item.children.length;i++) {
      var found=find(item.children[i],name)
      if(found)return found
    }
    return null
  }
  Window {
    id: window
    visible: true; width: 460; height: 1200
    Weather.Radar {
      id: radar; width: 432; active: true
      city: ({latitude:45.75,longitude:4.85,timezone:"Asia/Tokyo"})
      onWeatherRequested: suite.forecastRequests++
    }
    TestEvent { id: events }
  }
  Timer {
    interval: 100; repeat: true; running: true
    onTriggered: {
      try {
        attempts++
        if(attempts>150)throw new Error("QA_COVERAGE_FAIL: stage "+step+" timed out; coverage="+radar.coverageState)
        if(step===0) {
          if(radar.busy||radar.coverageState!=="uncovered")return
          check(radar.frames.length===1,"transparent rain tiles preserve observations without implying dry weather")
          check(radar.frameTime===fixtures.radarCityClock,"radar uses the city timezone")
          console.warn("QA_COVERAGE_OPAQUE_PASS: opaque mask means outside radar coverage")
          radar.radar=fixtures.clear;step++;return
        }
        if(step===1) {
          if(radar.coverageState!=="covered")return
          console.warn("QA_COVERAGE_TRANSPARENT_PASS: transparent mask means covered")
          radar.radar=fixtures.partial;step++;return
        }
        if(step===2) {
          check(radar.coverageState==="unknown","one missing mask prevents a coverage claim")
          check(radar.frames.length===1,"a missing mask does not suppress valid observations")
          radar.radar=fixtures.unknown;step++;return
        }
        if(step===3) {
          check(radar.coverageState==="unknown","unverified coverage remains unknown despite valid opaque imagery")
          check(radar.localSource("https://example.invalid/mask.png")==="","remote image source is rejected")
          console.warn("QA_COVERAGE_UNKNOWN_PASS: partial and unverified masks remain unknown")
          radar.radar=fixtures.fallback;step++;return
        }
        if(step===4) {
          check(radar.frameTime===fixtures.radarDesktopClock,"invalid local radar timestamp is explicitly desktop time")
          console.warn("QA_COVERAGE_CITY_TIME_PASS: radar times use Tokyo independently of desktop UTC")
          radar.city={latitude:90,longitude:12,timezone:"Etc/GMT"}
          radar.radar=fixtures.polar
          step++;return
        }
        if(step===5) {
          if(radar.busy)return
          check(radar.projectionUnsupported,"map projection reports unsupported poles")
          check(radar.city.latitude===90&&radar.city.longitude===12&&radar.radar.latitude===90&&radar.radar.longitude===12,"selected polar point was not moved")
          var action=find(radar,"radar-forecast-cta")
          check(!!action&&action.visible&&action.text==="See weather forecast","polar fallback action points to numeric weather")
          check(events.mouseClick(action,action.width/2,action.height/2,Qt.LeftButton,Qt.NoModifier,1),"native fallback button receives a real click")
          check(forecastRequests===1,"fallback signal is emitted exactly once")
          console.warn("QA_COVERAGE_POLAR_PASS: unsupported projection keeps coordinates and emits native fallback action")
          radar.active=false;radar.radar=fixtures.clear
          step++;return
        }
        if(step===6) {
          if(!radar.imageReady)return
          radar.playing=true
          radar.radar=fixtures.radarMissing
          step++;return
        }
        if(step===7) {
          if(!radar.imageError)return
          check(!radar.imageReady,"missing files are never marked ready")
          check(!radar.playing,"missing imagery stops playback")
          check(radar.message.indexOf("unavailable")>=0,"missing imagery has explicit recovery message")
          radar.radar=fixtures.radarCorrupt
          step++;return
        }
        if(step===8) {
          if(!radar.imageError)return
          check(!radar.imageReady,"undecodable files are never marked ready")
          radar.radar=fixtures.clear
          step++;return
        }
        if(step===9) {
          if(!radar.imageReady)return
          console.warn("QA_COVERAGE_IMAGES_PASS: missing and corrupted images stop playback; valid imagery recovers")
          radar.city={latitude:44,longitude:12};radar.active=true
          step++;return
        }
        if(step===10) {
          if(radar.busy)return
          check(radar.message.indexOf("timed out")>=0,"silent map workers are terminated with explicit timeout")
          check(!radar.playing,"watchdog stops playback")
          radar.city={latitude:45.75,longitude:4.85}
          step++;return
        }
        if(step===11) {
          if(radar.busy||!radar.imageReady)return
          check(radar.message==="","maps recover after a worker timeout")
          console.warn("QA_COVERAGE_WATCHDOG_PASS: silent workers terminate and a subsequent request recovers")
          console.warn("QA_COVERAGE_PASS: masks, image faults, watchdogs, projection limits, local clocks and fallback action")
          Qt.quit()
        }
      } catch(error) { console.error(error.message);Qt.exit(1) }
    }
  }
}
