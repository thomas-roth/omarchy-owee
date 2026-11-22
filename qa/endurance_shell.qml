import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons as Commons
import "plugin" as Weather

ShellRoot {
  id: suite
  property var panel: null
  property var scope: null
  property int phase: -2
  property int cycle: 0
  property double phaseSince: Date.now()
  property int previousRadarFrame: -1

  function note(event, extra) {
    var data=extra||{}
    data.event=event; data.cycle=cycle; data.phase=phase; data.time_ms=Date.now()
    console.warn("OWEE_ENDURANCE_EVENT "+JSON.stringify(data))
  }
  function require(ok, message) {
    if (!ok) throw new Error("QA_FAIL: endurance "+message)
  }
  function next(value) { phase=value; phaseSince=Date.now() }
  function finite(item) {
    if(!item)return true
    if(!isFinite(item.x)||!isFinite(item.y)||!isFinite(item.width)||!isFinite(item.height))return false
    if(typeof item.text==="string"&&(item.text.indexOf("NaN")>=0||item.text.indexOf("Infinity")>=0))return false
    for(var i=0;item.children&&i<item.children.length;i++)if(!finite(item.children[i]))return false
    return true
  }
  function activeSky(item) {
    if(!item)return false
    if(String(item).indexOf("Sky")>=0&&item.active===true)return true
    for(var i=0;item.children&&i<item.children.length;i++)if(activeSky(item.children[i]))return true
    return false
  }
  function begin() {
    cycle++
    Commons.Style.reduceMotion=(cycle%2===0)
    panel.open();scope.visible=true
    note("cycle_started",{motion:!Commons.Style.reduceMotion})
    next(0)
  }
  function advance() {
    try {
      if(phase===-2) {
        if(!loader.item || !loader.item.result.data || !loader.item.qaScope)return
        panel=loader.item;scope=panel.qaScope
        scope.parent=stage;scope.width=stage.width;scope.height=stage.height
        require(!!panel.qaCards&&!!panel.qaRadar,"all production components instantiated")
        note("ready")
        begin();return
      }
      if(phase===0) {
        var modes=["qa-offline","qa-partial","qa-malformed","qa-exit"]
        panel.run("load",modes[(cycle-1)%modes.length]);next(1);return
      }
      if(phase===1) {
        if(panel.loading)return
        require(finite(scope),"fault response kept finite geometry")
        panel.refresh();next(2);return
      }
      if(phase===2) {
        if(panel.loading)return
        require(!!panel.result.data,"weather recovers after a simulated backend fault")
        var city=panel.cities[(cycle-1)%Math.min(2,panel.cities.length)]
        panel.choose(city);next(3);return
      }
      if(phase===3) {
        if(panel.loading)return
        var changed=JSON.parse(JSON.stringify(panel.result))
        changed.data.current.temperature_2m=(cycle%45)-15
        changed.data.current.relative_humidity_2m=cycle%101
        changed.data.current.weather_code=[0,2,3,61,71,95,45][cycle%7]
        panel.result=changed
        panel.showPage("settings");panel.editingCards=true
        require(panel.qaCards.editing&&panel.qaCards.active,"settings editor stays available")
        panel.searching=true;panel.queueSearch("Paris");next(4);return
      }
      if(phase===4) {
        if(Date.now()-phaseSince<450)return
        panel.searching=false
        panel.showMapLayer("rain")
        next(5);return
      }
      if(phase===5) {
        if(panel.qaRadar.busy||panel.qaRadar.frames.length<2)return
        panel.qaRadar.step(1)
        previousRadarFrame=panel.qaRadar.frameIndex
        panel.qaRadar.playing=!Commons.Style.reduceMotion
        next(6);return
      }
      if(phase===6) {
        if(!Commons.Style.reduceMotion&&Date.now()-phaseSince<950)return
        if(!Commons.Style.reduceMotion)require(panel.qaRadar.frameIndex!==previousRadarFrame,"radar animation advances with local fixtures")
        panel.showMapLayer("wind")
        require(!panel.qaRadar.playing&&panel.qaRadar.mapLayer==="wind","switching to wind stops playback")
        next(7);return
      }
      if(phase===7) {
        if(panel.qaRadar.busy||!panel.qaRadar.imageReady||panel.qaRadar.frames.length<2)return
        panel.qaRadar.step(1);next(8);return
      }
      if(phase===8) {
        if(panel.qaRadar.busy||!panel.qaRadar.imageReady)return
        panel.qaRadar.togglePlayback();next(9);return
      }
      if(phase===9) {
        if(panel.qaRadar.playing&&Date.now()-phaseSince<3100)return
        require(finite(scope),"navigation and measurements kept finite geometry")
        panel.close();scope.visible=false
        require(!panel.qaRadar.active&&!panel.qaCards.active,"closed panel deactivates all page work")
        require(!panel.qaRadar.playing,"closed panel stops both animations")
        require(!activeSky(scope),"closed panel stops the weather illustration")
        note("closed")
        next(10);return
      }
      if(phase===10) {
        if((panel.loading||panel.searchInFlight||panel.qaRadar.busy||panel.qaRadar.busy)&&Date.now()-phaseSince<2500)return
        require(!panel.loading&&!panel.searchInFlight&&!panel.qaRadar.busy&&!panel.qaRadar.busy,"closed panel settles every fixture worker")
        note("cycle_complete",{closed:true})
        next(-1);return
      }
    } catch(error) {
      note("failed",{message:error.message})
      console.error(error.message);Qt.exit(1)
    }
  }
  Window {
    id: window
    visible:true;width:460;height:760
    color:Commons.Color.background
    Rectangle {id:stage;x:14;y:14;width:parent.width-28;height:parent.height-28;color:window.color}
  }
  Loader {id:loader;source:Qt.resolvedUrl("plugin/Panel.qml")}
  Timer {interval:100;repeat:true;running:suite.phase!==-1;onTriggered:suite.advance()}
  Timer {interval:@@INTERVAL_MS@@;repeat:true;running:true;onTriggered:if(suite.phase===-1)suite.begin()}
}
