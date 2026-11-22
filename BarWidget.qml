import QtQuick
import qs.Commons
import qs.Ui

// owee.weather 1.4.0 — the version stamp backs the manifest integrity check.
BarWidget {
  id: root
  moduleName: "owee.weather"
  function inject() {
    if (!loader.item) return
    loader.item.bar = root.bar
    loader.item.settings = root.settings
    loader.item.anchorItem = button
    loader.item.hostWidget = root
  }
  readonly property bool opened: loader.item ? loader.item.opened : false
  readonly property bool popoutSwitchClosing: loader.item ? loader.item.popoutSwitchClosing : false
  function open() { if (loader.item) loader.item.open() }
  function close() { if (loader.item) loader.item.close() }
  function closeForPopoutSwitch() { if (loader.item) loader.item.closeForPopoutSwitch() }
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onBarChanged: inject()
  onSettingsChanged: inject()
  Loader {
    id: loader
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: { root.inject(); Qt.callLater(root.inject) }
  }
  WidgetButton {
    id: button
    objectName: "weather-bar-button"
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    // The native status slot includes the icon canvas and its side bearings.
    readonly property real nativeBearings: Math.max(0, Style.bar.statusSlot - Style.bar.iconCanvas)
    implicitWidth: vertical ? barSize : weatherContent.implicitWidth + nativeBearings
    implicitHeight: vertical ? weatherContent.implicitHeight + nativeBearings : barSize
    tooltipText: loader.item ? loader.item.barTooltip : "Weather: —"
    Accessible.role: Accessible.Button
    Accessible.name: loader.item ? loader.item.barTooltip : "Weather"
    Accessible.onPressAction: if (loader.item) loader.item.toggle()
    Item {
      id: weatherContent
      anchors.centerIn: parent
      implicitWidth: optical.width
      implicitHeight: optical.height
      width: implicitWidth
      height: implicitHeight
      scale: button.pressScale
      BarIconContent {
        id: optical
        objectName: "weather-bar-optical"
        anchors.centerIn: parent
        width: Style.bar.iconCanvas; height: width
        sourceSize: Style.bar.iconCanvas
        sourceComponent: Component {
          WeatherMark {
            objectName: "weather-bar-icon"
            code: loader.item && loader.item.primaryCurrent ? loader.item.primaryCurrent.weather_code : null
            night: !!loader.item && !!loader.item.primaryCurrent && loader.item.primaryCurrent.is_day === 0
            ink: button.foreground
          }
        }
      }
    }
    onPressed: function(b) { if (loader.item) { if (b === Qt.MiddleButton) loader.item.refresh(); else loader.item.toggle() } }
  }
}
