import QtQuick
import QtQuick.Window
import QtTest
import Quickshell
import qs.Commons as Commons
import "plugin" as Weather

ShellRoot {
  id: suite
  property var p: null
  property var scope: null
  property var favorites: null
  property int checks: 0
  property int step: 0
  property bool inTick: false
  property double since: Date.now()
  property string primaryBefore: ""
  property string barBefore: ""
  property var originalCities: []
  function check(ok, message) {
    if (!ok) throw new Error("QA_FAIL: " + message)
    checks++
    console.warn("QA_FAVORITE_CITIES_CHECK", checks, message)
  }
  function advance(next) { step=next;since=Date.now();console.warn("QA_FAVORITE_CITIES_STEP",step) }
  function finish(code) { testTimer.stop();Qt.callLater(function() { Qt.exit(code) }) }
  function state() {
    return JSON.stringify({step:step,loader:loader.status,city:p?p.cityName:null,
      page:p?p.activePage:null,loading:p?p.loading:null,pending:p?p.pendingActions:null,
      searching:p?p.searching:null,error:p?p.errorText:null,windowActive:window.active})
  }
  function settled() { return p&&!p.loading&&!p.pendingActions.length&&Date.now()-since>200 }
  function find(item, name) {
    if (!item) return null
    if (item.objectName===name) return item
    for (var i=0;item.children&&i<item.children.length;i++) {
      var child=find(item.children[i],name)
      if (child) return child
    }
    return null
  }
  function chip(index) { return find(favorites,"favorite-city-"+index) }
  function scroller(item) {
    if (!item) return null
    if (typeof item.contentX==="number"&&typeof item.contentWidth==="number") return item
    for (var i=0;item.children&&i<item.children.length;i++) {
      var child=scroller(item.children[i])
      if (child) return child
    }
    return null
  }
  function reveal(item) {
    var scroll=scroller(favorites)
    if (!scroll) return
    var point=item.mapToItem(scroll,0,0)
    if (point.x<0) scroll.contentX+=point.x
    else if(point.x+item.width>scroll.width) scroll.contentX+=point.x+item.width-scroll.width
    scroll.contentX=Math.max(0,Math.min(scroll.contentX,scroll.contentWidth-scroll.width))
  }
  function click(item) {
    check(!!item,"native control found")
    if (String(item.objectName).indexOf("favorite-city-")===0) reveal(item)
    check(events.mouseClick(item,item.width/2,item.height/2,Qt.LeftButton,Qt.NoModifier,1),"real QtTest mouse click delivered")
  }
  function primaryPreserved() {
    check(JSON.stringify(p.primaryCity)===primaryBefore&&p.barTemperature===barBefore,"favorite navigation preserves primary city and bar temperature")
  }
  function geometry() {
    var nav=find(scope,"nav-radar")
    var origin=favorites.mapToItem(stage,0,0)
    var maps=nav.mapToItem(stage,0,0)
    check(isFinite(favorites.width)&&isFinite(favorites.height)&&favorites.width>=0&&favorites.height>=0,"favorite strip has finite geometry")
    check(origin.x>=maps.x+nav.width-0.5&&Math.abs(origin.y-maps.y)<4,"favorites sit directly beside fixed Weather and Radar controls")
    check(origin.x+favorites.width<=stage.width+0.5,"favorite overflow stays inside panel width")
  }
  function plainLabels(item) {
    var found=0
    if (item instanceof Text&&item.text===originalCities[3].name) {
      check(item.textFormat===Text.PlainText,"markup-shaped city name stays plain text")
      found++
    }
    for (var i=0;item.children&&i<item.children.length;i++) found+=plainLabels(item.children[i])
    return found
  }
  QtObject { id:nativeBar;property color barForeground:Commons.Color.foreground }
  Window {
    id:window
    visible:true;width:460;height:760;color:Commons.Color.background
    Rectangle { id:stage;x:14;y:14;width:parent.width-28;height:parent.height-28;color:window.color }
    TestEvent { id:events }
  }
  Loader { id:loader;active:false }
  Component.onCompleted: {
    loader.setSource(Qt.resolvedUrl("plugin/Panel.qml"),{bar:nativeBar})
    loader.active=true
  }
  Timer {
    id:testTimer
    interval:50;repeat:true;running:true
    onTriggered: {
      // QtTest input delivery runs a nested event loop. Ignore reentrant timer
      // delivery until this step has finished its clicks and advanced state.
      if(inTick)return
      inTick=true
      try {
        if(Date.now()-since>8000)throw new Error("QA_FAIL: favorite step exceeded 8 seconds: "+state())
        if (step===0) {
          if(!loader.item||!loader.item.result.data||!loader.item.qaScope)return
          p=loader.item;scope=p.qaScope
          scope.parent=stage;scope.width=stage.width;scope.height=stage.height
          favorites=find(scope,"favorite-cities")
          check(!!favorites,"real Panel embeds favorite strip")
          originalCities=p.cities.slice()
          primaryBefore=JSON.stringify(p.primaryCity);barBefore=p.barTemperature
          p.open();window.requestActivate()
          advance(1);return
        }
        if (step===1) {
          if(!settled()||!chip(29))return
          geometry()
          check(p.cities.length===30&&chip(29).text===originalCities[29].name,"all thirty favorites retain native button labels")
          check(chip(3).text===originalCities[3].name,"markup-shaped city name remains literal")
          check(plainLabels(chip(3))>0,"native favorite text renderer inspected")
          check(chip(1).selected&&!chip(0).selected,"initial selection follows viewed city")
          click(chip(0))
          check(p.loading&&!chip(0).enabled&&!chip(1).enabled,"pending request disables favorite controls")
          check(chip(1).selected&&!chip(0).selected,"selection waits for weather response")
          click(chip(1))
          check(!p.pendingActions.length,"clicking disabled favorite queues no selection")
          advance(2);return
        }
        if (step===2) {
          if(!settled()||p.cityName!=="Lyon")return
          check(p.activePage==="weather"&&chip(0).selected&&!chip(1).selected,"one click updates viewed weather and selected favorite")
          primaryPreserved()
          click(chip(0))
          check(!p.loading&&!p.pendingActions.length,"clicking current favorite starts no request")
          click(find(scope,"nav-radar"));click(chip(1))
          advance(3);return
        }
        if (step===3) {
          if(!settled()||p.cityName!=="Paris")return
          check(p.activePage==="radar"&&!p.searching,"favorite preserves Radar view")
          primaryPreserved()
          click(find(scope,"nav-settings"));click(chip(0))
          advance(4);return
        }
        if (step===4) {
          if(!settled()||p.cityName!=="Lyon")return
          check(p.activePage==="weather"&&!p.searching,"favorite from Settings opens Weather")
          click(find(scope,"open-cities"))
          check(p.searching,"native city search opens")
          p.queueSearch("Pa")
          click(chip(1))
          check(!p.searching&&p.searchQuery===""&&!p.searchQueued&&!p.searchBusy,"favorite closes and cancels city search")
          advance(5);return
        }
        if (step===5) {
          if(!settled()||p.cityName!=="Paris")return
          primaryPreserved()
          click(chip(2))
          advance(6);return
        }
        if (step===6) {
          if(!settled()||p.errorText!=="Fixture favorite selection failure")return
          check(p.cityName==="Paris"&&chip(1).selected&&!chip(2).selected,"failed favorite preserves viewed city and selected state")
          primaryPreserved()
          var scroll=scroller(favorites)
          check(!!scroll&&scroll.contentWidth>scroll.width,"thirty favorites overflow horizontally")
          scroll.contentX=0
          chip(0).forceActiveFocus(Qt.TabFocusReason)
          for(var i=0;i<29;i++)check(events.keyClick(Qt.Key_Tab,Qt.NoModifier,1),"native Tab key delivered")
          advance(7);return
        }
        if (step===7) {
          if(Date.now()-since<250)return
          check(chip(29).activeFocus,"keyboard traverses all favorite controls")
          var scroll=scroller(favorites)
          var point=chip(29).mapToItem(scroll,0,0)
          check(scroll.contentX>0&&point.x>=-0.5&&point.x+chip(29).width<=scroll.width+0.5,"keyboard focus reveals offscreen favorite")
          geometry()
          p.result=Object.assign({},p.result,{cities:[originalCities[29],originalCities[1]]})
          advance(8);return
        }
        if (step===8) {
          if(Date.now()-since<200)return
          check(chip(0).text===originalCities[29].name&&chip(1).text==="Paris"&&!chip(2),"reorder and removal update favorite delegates")
          check(chip(1).selected,"reorder keeps selection attached to city identity")
          geometry()
          p.result=Object.assign({},p.result,{cities:[]})
          advance(9);return
        }
        if (step===9) {
          if(Date.now()-since<200)return
          check(!chip(0),"empty favorite list removes delegates")
          check(isFinite(favorites.width)&&isFinite(favorites.height)&&favorites.width>=0&&favorites.height>=0,"empty list retains finite geometry")
          var weather=find(scope,"nav-weather"),maps=find(scope,"nav-radar")
          check(weather.visible&&maps.visible&&weather.width>0&&maps.width>0,"empty list preserves fixed navigation")
          console.warn("QA_FAVORITE_CITIES_PASS",checks)
          finish(0)
        }
      } catch(error) { console.error(String(error),state());finish(1) }
      finally { inTick=false }
    }
  }
}
