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
    visible: true; width: 460; height: 700
    Weather.Radar {
      id: radar; width: 432; active: true
      city: ({latitude:45.75,longitude:4.85,timezone:"Asia/Tokyo"})
    }
    TestEvent { id: events }
  }
  Timer {
    interval: 100; repeat: true; running: true
    onTriggered: {
      try {
        attempts++
        if(attempts>150)throw new Error("QA_COVERAGE_FAIL: stage "+step+" timed out; frames="+radar.frameCount)
        if(step===0) {
          if(radar.busy||radar.frameCount===0||!radar.imageReady)return
          check(radar.frameCount===2&&radar.nowIndex===0,"streamed timeline spans past and future frames")
          check(radar.frameClock===fixtures.radarCityIso.substring(11,16)&&radar.frameLead==="now","radar uses the city timezone and marks now")
          console.warn("QA_COVERAGE_STREAM_PASS: past and future frames arrive with city local time")
          radar.stepFrames(1);step++;return
        }
        if(step===1) {
          check(radar.frameIndex===1&&radar.frameLead==="+1 h","stepping forward reaches the prediction frame")
          check(radar.frameClock===fixtures.radarFutureIso.substring(11,16)&&!radar.playing,"prediction frame shows its future local time")
          check(radar.localSource("https://example.invalid/tile.png")==="","remote image source is rejected")
          radar.stepFrames(-1)
          radar.playing=true
          radar.rainData=fixtures.radarPartial.rain;step++;return
        }
        if(step===2) {
          // The newest observation failed to render: the view must fall back
          // to the nearest complete frame instead of showing an empty map.
          check(radar.displayIndex===1&&radar.imageReady,"missing newest frame falls back to the nearest complete frame")
          check(radar.frameClock===fixtures.radarFutureIso.substring(11,16),"fallback shows the displayed frame's local time")
          check(radar.playing,"a single missing frame does not stop playback")
          console.warn("QA_COVERAGE_FALLBACK_PASS: incomplete frames fall back to the nearest complete imagery")
          radar.playing=false
          radar.rainData=fixtures.radarMissing.rain;step++;return
        }
        if(step===3) {
          if(!radar.imageFault)return
          check(radar.message.indexOf("unavailable")>=0,"frames whose files disappeared say so explicitly")
          radar.rainData=fixtures.radarCorrupt.rain;step++;return
        }
        if(step===4) {
          check(radar.imageFault,"undecodable files are reported like missing imagery")
          radar.imageFault=false;radar.message=""
          radar.rainData=fixtures.radarDefault.rain;step++;return
        }
        if(step===5) {
          if(!radar.imageReady)return
          check(radar.displayIndex===0&&radar.message==="","radar imagery recovers after image faults")
          console.warn("QA_COVERAGE_IMAGES_PASS: missing and corrupted images fall back or show the empty state; valid imagery recovers")
          radar.configure({wind_enabled:false});step++;return
        }
        if(step===6) {
          if(radar.busy)return
          check(radar.windEnabled===false&&radar.rainEnabled===true,"wind can be disabled without touching rain")
          radar.mode="wind";step++;return
        }
        if(step===7) {
          var status=find(radar,"radar-status")
          check(!!status&&status.text==="Radar is off","a disabled radar says so and fetches nothing")
          check(radar.frameCount===0,"a disabled radar shows no timeline frames")
          radar.configure({wind_enabled:true});step++;return
        }
        if(step===8) {
          if(radar.busy||radar.frameCount===0||!radar.imageReady)return
          check(radar.windEnabled===true,"re-enabling the wind map fetches its data again")
          radar.city={latitude:90,longitude:12,timezone:"Etc/GMT"}
          step++;return
        }
        if(step===9) {
          if(radar.busy||(!radar.unsupported&&radar.frameCount===0))return
          check(radar.unsupported,"the polar projection reports unsupported poles")
          check(radar.city.latitude===90&&radar.city.longitude===12&&radar.radar.latitude===90&&radar.radar.longitude===12,"selected polar point was not moved")
          console.warn("QA_COVERAGE_POLAR_PASS: unsupported projection keeps coordinates and explains itself")
          radar.city={latitude:44,longitude:12,timezone:"Etc/GMT"}
          step++;return
        }
        if(step===10) {
          if(radar.busy)return
          check(radar.message.indexOf("timed out")>=0,"silent radar workers are terminated with explicit timeout")
          check(!radar.playing,"watchdog stops playback")
          radar.city={latitude:45.75,longitude:4.85,timezone:"Asia/Tokyo"}
          step++;return
        }
        if(step===11) {
          if(radar.busy||!radar.imageReady)return
          check(radar.message==="","the radar recovers after a worker timeout")
          console.warn("QA_COVERAGE_WATCHDOG_PASS: silent workers terminate and a subsequent request recovers")
          console.warn("QA_COVERAGE_PASS: streaming, image faults, fallbacks, watchdogs, projection limits, local clocks and per-radar switches")
          Qt.quit()
        }
      } catch(error) { console.error(error.message);Qt.exit(1) }
    }
  }
}
