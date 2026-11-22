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
  property var field: null
  property int step: 0
  property int checks: 0
  // TestEvent delivers input through a nested event loop, so the repeat timer
  // can fire again while a step is still running. Without this guard one
  // step advances twice and skips the next one.
  property bool qaBusy: false
  property double since: Date.now()
  property string output: @@OUTPUT@@
  function check(ok,label) {
    if(!ok) {console.error("QA_FAIL: "+label);Qt.exit(1);throw new Error(label)}
    checks++;console.warn("QA_SEARCH_CHECK",checks,label)
  }
  function find(item,name) {
    if(!item)return null
    if(item.objectName===name)return item
    for(var i=0;item.children&&i<item.children.length;i++){var found=find(item.children[i],name);if(found)return found}
    return null
  }
  function click(item) {check(!!item,"control exists");check(events.mouseClick(item,item.width/2,item.height/2,Qt.LeftButton,Qt.NoModifier,1),"mouse click delivered")}
  function type(text) {
    field.forceActiveFocus()
    events.keyClick(Qt.Key_A,Qt.ControlModifier,1)
    events.keyClick(Qt.Key_Backspace,Qt.NoModifier,1)
    for(var i=0;i<text.length;i++) {
      var c=text[i]
      events.keyClickChar(c,Qt.NoModifier,1)
    }
    check(field.text===text,"typed "+text+" without Enter (got "+field.text+")")
    since=Date.now()
  }
  function advance() {step++;since=Date.now()}
  function ready() {return !p.searchBusy&&!p.searchInFlight}
  Window {
    id: window
    width:460;height:760;visible:true
    color:Commons.Color.background
    Rectangle {id:stage;x:14;y:14;width:parent.width-28;height:parent.height-28;color:window.color}
    TestEvent {id:events}
  }
  Loader {id:loader;source:Qt.resolvedUrl("plugin/Panel.qml")}
  Connections {
    target:suite.p
    function onSuggestionsChanged() {
      if(p.suggestions.length)check(p.searching&&p.suggestions[0].name===p.searchQuery,"only latest active query can populate results")
    }
  }
  Timer {
    interval:50;repeat:true;running:true
    onTriggered: {
      if(qaBusy)return
      qaBusy=true
      try {
        if(step===0) {
          if(!loader.item||!loader.item.result.data||!loader.item.qaScope)return
          p=loader.item;scope=p.qaScope;scope.parent=stage;scope.width=stage.width;scope.height=stage.height
          p.open();window.requestActivate();step=100;return
        }
        if(step===100) {
          click(find(scope,"open-cities"));field=find(scope,"city-input")
          check(p.searching,"city chooser opened by real click")
          step=101;return
        }
        if(step===101) {
          type("P");step=1;since=Date.now();return
        }
        if(step===1) {
          if(Date.now()-since<400)return
          check(!p.searchBusy&&!p.searchInFlight&&p.suggestions.length===0,"single character never starts a search")
          type("Paris");advance();return
        }
        if(step===2) {
          check(p.searchBusy&&!p.searchInFlight,"typing waits for debounce: "+p.searchBusy+","+p.searchInFlight+","+p.searchQuery+","+p.searching+","+p.opened)
          advance();return
        }
        if(step===3) {
          if(!ready())return
          check(p.suggestions.length===1&&p.suggestions[0].name==="Paris","results appear without Enter")
          step=30
          stage.grabToImage(function(result) {
            check(result.saveToFile(suite.output+"/live-search.png"),"saved search preview")
            type("Pa");step=4;since=Date.now()
          })
          return
        }
        if(step===4) {
          if(!p.searchInFlight)return
          type("Rome");advance();return
        }
        if(step===5) {
          if(!ready())return
          check(p.suggestions.length===1&&p.suggestions[0].name==="Rome","slow obsolete reply cannot replace new results")
          type("Slow");advance();return
        }
        if(step===6) {
          if(!p.searchInFlight)return
          p.refresh();advance();return
        }
        if(step===7) {
          if(Date.now()-since<150)return
          if(p.loading&&Date.now()-since<1500)return
          check(!p.loading&&p.searchInFlight,"weather refresh is independent of city search (weather="+p.loading+", search="+p.searchInFlight+", elapsed="+(Date.now()-since)+"ms)")
          type("");advance();return
        }
        if(step===8) {
          if(Date.now()-since<2150)return
          check(!p.searchBusy&&p.suggestions.length===0&&p.searchMessage==="","clearing in-flight query ignores late reply")
          type("Never");click(find(scope,"open-cities"));advance();return
        }
        if(step===9) {
          if(Date.now()-since<400)return
          check(!p.searching&&!p.searchBusy&&p.suggestions.length===0,"closing cancels a debounced search")
          click(find(scope,"open-cities"));check(field.text==="","reopening starts with empty search")
          type("zz");advance();return
        }
        if(step===10) {
          if(!ready())return
          check(p.searchMessage==="No cities found"&&p.suggestions.length===0,"empty result has a clear status")
          type("error");advance();return
        }
        if(step===11) {
          if(!ready())return
          check(p.searchMessage.indexOf("unavailable")>=0&&p.errorText===""&&!!p.current,"search error does not invalidate weather")
          type("Paris");advance();return
        }
        if(step===12) {
          if(!ready())return
          check(p.suggestions.length===1&&p.searchMessage==="","typing recovers from search error")
          field.forceActiveFocus();events.keyClick(Qt.Key_Down,Qt.NoModifier,1);events.keyClick(Qt.Key_Return,Qt.NoModifier,1)
          advance();return
        }
        if(step===13) {
          if(p.loading)return
          check(!p.searching&&p.cityName==="Paris"&&p.primaryCityName==="Lyon","keyboard selection consults city without changing primary")
          click(find(scope,"open-cities"));type("Pa");advance();return
        }
        if(step===14) {
          if(!p.searchInFlight)return
          p.close();advance();return
        }
        if(step===15) {
          if(Date.now()-since<850)return
          check(!p.opened&&!p.searching&&!p.searchBusy&&p.suggestions.length===0&&p.searchMessage==="","closing panel cancels and discards pending results")
          console.warn("QA_SEARCH_PASS",checks,"checks; real typing, debounce, cancellation, stale replies and selection")
          Qt.quit()
        }
      } catch(error) {console.error("QA_FAIL:",error.message);Qt.exit(1)}
      finally {qaBusy=false}
    }
  }
}
