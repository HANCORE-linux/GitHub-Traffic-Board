import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.hancore-linux.traffic-board"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property string home: Quickshell.env("HOME")
  readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") || (home + "/.config")
  readonly property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  readonly property string tokenDir: configHome + "/gh-traffic"
  readonly property string settingsPath: tokenDir + "/plugin.json"
  readonly property string dataDir: home + "/gh-traffic"
  readonly property string trafficPath: dataDir + "/panel.json"
  readonly property string lightDir: dataDir + "/light"
  readonly property string lightPath: lightUser !== "" ? lightDir + "/" + lightUser.toLowerCase() + ".json" : ""
  readonly property string exportDir: dataDir + "/exports"
  readonly property string scriptPath: decodeURIComponent(String(Qt.resolvedUrl("../gh_traffic.py")).replace(/^file:\/\//, ""))

  property var trafficSnapshot: null
  property var lightSnapshot: null
  property string errorCode: ""
  property string errorMessage: ""
  property var confirmInfo: null
  property bool fetchHandled: true
  property string pendingToken: ""
  property string imagePath: ""
  property string reportPath: ""
  property bool hasToken: false
  property bool tokenChecked: false
  property string confirmation: ""
  property string barDisplay: "both"
  property bool exportPrivate: false
  property string viewMode: "traffic"
  property string lightUser: ""
  property var lightUsers: []
  property string pendingSettings: ""

  readonly property bool lightMode: viewMode === "light"
  readonly property bool lightMatches: lightSnapshot !== null && String(lightSnapshot.user || "").toLowerCase() === lightUser.toLowerCase()
  readonly property var view: lightMode ? (lightMatches ? Model.buildLight(lightSnapshot) : null) : Model.build(trafficSnapshot)
  readonly property var publicView: lightMode ? view : Model.build(publicSnapshot(trafficSnapshot))
  readonly property var exportView: exportPrivate || lightMode ? view : publicView
  readonly property bool busy: fetcher.running || tokenWriter.running
  readonly property string mode: lightMode ? (view ? "light" : "light-empty")
    : errorCode === "no-token" || errorCode === "unauthorized" ? "setup"
    : tokenChecked && !hasToken ? "setup"
    : view ? "data" : "empty"
  readonly property bool barAlert: errorCode !== "" && ["no-token", "confirm", "invalid-user"].indexOf(errorCode) < 0
  readonly property bool spike: view !== null && view.spike === true && errorCode === ""
  readonly property bool vertical: bar ? bar.vertical === true : false
  readonly property string barGlyph: mode === "setup" ? "" : lightMode ? "" : ""
  readonly property string barCount: view ? view.barLabel : ""
  readonly property string barText: mode === "setup" || vertical || barCount === "" || barDisplay === "icon" ? barGlyph
    : barDisplay === "text" ? barCount
    : barGlyph + " " + barCount
  readonly property string barTooltip: busy ? "Refreshing GitHub data"
    : mode === "setup" ? "GitHub traffic: add a token"
    : barAlert ? Model.errorText(errorCode, errorMessage)
    : view && lightMode ? Model.fmt(view.stars) + " stars across " + Model.fmt(view.repoCount) + " public repositories of " + view.user
    : view ? Model.fmt(view.views) + " views and " + Model.fmt(view.clones) + " clones in 14 days"
    : "GitHub traffic"

  function open() { root.controller.show() }
  function openFromHotkey() { root.controller.show() }
  function close() { root.controller.hide() }
  function toggle() { if (root.opened) root.close(); else root.open() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function stamp() {
    return Qt.formatDateTime(new Date(), "yyyyMMdd-HHmmss")
  }

  function notify(headline, description, path) {
    var helper = root.omarchyPath !== "" ? root.omarchyPath + "/bin/omarchy-notification-send" : "omarchy-notification-send"
    var args = [helper, "-g", root.lightMode ? "" : "", headline, description]
    if (path) args = args.concat(["--exec", "xdg-open", path])
    Quickshell.execDetached(args)
  }

  function publicSnapshot(snapshot) {
    if (!snapshot || !Array.isArray(snapshot.repos)) return null
    return {
      ok: snapshot.ok,
      user: snapshot.user,
      generated: snapshot.generated,
      window_days: snapshot.window_days,
      repos: snapshot.repos.filter(function(r) { return r.private !== true }),
      skipped: [],
    }
  }

  function clearError() {
    root.errorCode = ""
    root.errorMessage = ""
    root.confirmInfo = null
  }

  function refresh(force) {
    if (fetcher.running) return
    if (root.lightMode && root.lightUser === "") return
    fetcher.mode = root.viewMode
    fetcher.command = root.lightMode
      ? ["sh", "-c", "mkdir -p \"$1\" && exec python3 \"$2\" --json --public \"$3\"", "sh", root.lightDir, root.scriptPath, root.lightUser]
      : ["sh", "-c", "mkdir -p \"$1\" && exec python3 \"$2\" --json --confirm-above \"$3\"", "sh", root.dataDir, root.scriptPath,
         force === true ? "0" : String(Model.WARN_REQUESTS)]
    root.fetchHandled = false
    fetcher.running = true
  }

  function finishFetch(text) {
    if (root.fetchHandled) return
    root.fetchHandled = true
    var payload = null
    try {
      payload = JSON.parse(String(text || ""))
    } catch (e) {
      payload = null
    }
    if (payload && payload.ok === true && Array.isArray(payload.repos)) {
      if (payload.light === true) {
        if (!root.sameUser(payload.user, root.lightUser)) return
        if (payload.user !== root.lightUser) root.renameLightUser(root.lightUser, String(payload.user))
        root.lightSnapshot = payload
        lightFile.setText(JSON.stringify(payload) + "\n")
      } else {
        root.trafficSnapshot = payload
        trafficFile.setText(JSON.stringify(payload) + "\n")
      }
      if (fetcher.mode === root.viewMode) root.clearError()
      return
    }
    if (fetcher.mode !== root.viewMode) return
    if (payload && payload.error === "confirm") {
      root.errorCode = "confirm"
      root.errorMessage = String(payload.message || "")
      root.confirmInfo = { repoCount: Number(payload.repoCount) || 0, requests: Number(payload.requests) || 0 }
    } else if (payload && typeof payload.error === "string") {
      root.errorCode = payload.error
      root.errorMessage = String(payload.message || "")
      root.confirmInfo = null
    } else {
      root.errorCode = "helper"
      root.errorMessage = ""
      root.confirmInfo = null
    }
  }

  function loadAnyway() {
    root.clearError()
    root.refresh(true)
  }

  function exportImage() {
    if (!root.view || imageDir.running) return
    root.imagePath = root.exportDir + "/gh-" + (root.lightMode ? "public" : "traffic") + "-" + root.stamp() + ".png"
    imageDir.running = true
  }

  function exportReport() {
    if (!root.view || reporter.running) return
    root.reportPath = root.exportDir + "/gh-" + (root.lightMode ? "public" : "traffic") + "-" + root.stamp() + ".html"
    reporter.command = ["sh", "-c", "mkdir -p \"$1\" && exec python3 \"$2\" --from-json \"$3\" --out \"$4\" $5", "sh",
                        root.exportDir, root.scriptPath, root.lightMode ? root.lightPath : root.trafficPath, root.reportPath,
                        root.exportPrivate && !root.lightMode ? "--include-private" : ""]
    reporter.running = true
  }

  function probeToken() {
    if (!tokenProbe.running) tokenProbe.running = true
  }

  function settingsJson() {
    return JSON.stringify({ barDisplay: root.barDisplay, viewMode: root.viewMode, lightUsers: root.lightUsers, lightUser: root.lightUser, exportPrivate: root.exportPrivate })
  }

  function sameUser(a, b) {
    return String(a || "").toLowerCase() === String(b || "").toLowerCase()
  }

  function validUser(user) {
    return /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(String(user || ""))
  }

  function indexOfUser(user) {
    for (var i = 0; i < root.lightUsers.length; i++)
      if (root.sameUser(root.lightUsers[i], user)) return i
    return -1
  }

  function renameLightUser(from, to) {
    var list = root.lightUsers.slice()
    var i = root.indexOfUser(from)
    if (i < 0) return
    list[i] = to
    root.lightUsers = list
    if (root.sameUser(root.lightUser, from)) root.lightUser = to
    root.saveSettings()
  }

  function saveSettings() {
    root.pendingSettings = root.settingsJson()
    root.writeSettings()
  }

  function writeSettings() {
    if (settingsWriter.running) return
    settingsWriter.written = root.pendingSettings
    settingsWriter.command = ["sh", "-c", "mkdir -p \"$1\" && printf '%s\\n' \"$2\" > \"$1/plugin.json.tmp\" && mv -f \"$1/plugin.json.tmp\" \"$1/plugin.json\"", "sh",
                              root.tokenDir, settingsWriter.written]
    settingsWriter.running = true
  }

  function setBarDisplay(value) {
    if (["icon", "text", "both"].indexOf(value) < 0 || value === root.barDisplay) return
    root.barDisplay = value
    root.saveSettings()
  }

  function setExportPrivate(value) {
    if (value === root.exportPrivate) return
    root.exportPrivate = value === true
    root.saveSettings()
  }

  function setViewMode(value) {
    if (["traffic", "light"].indexOf(value) < 0 || value === root.viewMode) return
    root.viewMode = value
    root.clearError()
    trafficView.shownCount = Model.TOP_REPOS
    root.saveSettings()
  }

  function selectLightUser(user) {
    if (root.indexOfUser(user) < 0 || root.sameUser(user, root.lightUser)) return
    root.lightSnapshot = null
    root.lightUser = root.lightUsers[root.indexOfUser(user)]
    root.clearError()
    trafficView.shownCount = Model.TOP_REPOS
    root.saveSettings()
  }

  function addLightUser(user) {
    if (!root.validUser(user)) return
    var i = root.indexOfUser(user)
    if (i >= 0) {
      if (!root.sameUser(user, root.lightUser)) root.selectLightUser(root.lightUsers[i])
      root.showConfirmation(root.lightUsers[i] + " is already saved")
      if (root.lightSnapshot === null) root.refresh()
      return
    }
    if (root.lightUsers.length >= trafficView.maxLightUsers) return
    root.lightUsers = root.lightUsers.concat([user])
    root.lightSnapshot = null
    root.lightUser = user
    root.clearError()
    trafficView.shownCount = Model.TOP_REPOS
    root.saveSettings()
    root.showConfirmation("Added " + user)
    root.refresh()
  }

  function showConfirmation(text) {
    root.confirmation = text
    confirmTimer.restart()
  }

  function removeLightUser(user) {
    var i = root.indexOfUser(user)
    if (i < 0) return
    var gone = root.lightUsers[i]
    var list = root.lightUsers.slice()
    list.splice(i, 1)
    root.lightUsers = list
    cacheRemover.command = ["rm", "-f", root.lightDir + "/" + gone.toLowerCase() + ".json"]
    cacheRemover.running = true
    if (root.sameUser(gone, root.lightUser)) {
      root.lightSnapshot = null
      root.lightUser = list.length > 0 ? list[0] : ""
      root.clearError()
    }
    root.saveSettings()
  }

  function removeToken() {
    if (!tokenRemover.running) tokenRemover.running = true
  }

  function saveToken(token) {
    if (tokenWriter.running) return
    root.pendingToken = token
    tokenWriter.stdinEnabled = true
    tokenWriter.running = true
  }

  Process {
    id: fetcher
    property string mode: "traffic"
    stdout: StdioCollector {
      id: fetchOut
      waitForEnd: true
      onStreamFinished: root.finishFetch(text)
    }
    onRunningChanged: if (!running) Qt.callLater(function() { root.finishFetch(fetchOut.text) })
  }

  Process {
    id: reporter
    onExited: function(code) {
      if (code === 0) root.notify("Report exported", root.reportPath, root.reportPath)
      else root.notify("Report export failed", "The helper exited with code " + code, "")
    }
  }

  Process {
    id: imageDir
    command: ["mkdir", "-p", root.exportDir]
    onExited: function(code) {
      if (code !== 0) {
        root.notify("Image export failed", "Could not create " + root.exportDir, "")
        return
      }
      trafficView.exporting = true
      var target = root.imagePath
      trafficView.grabToImage(function(result) {
        var saved = result.saveToFile(target)
        trafficView.exporting = false
        if (saved) root.notify("Image exported", target, target)
        else root.notify("Image export failed", target, "")
      })
    }
  }

  Process {
    id: tokenWriter
    command: ["sh", "-c", "umask 077 && mkdir -p \"$1\" && cat > \"$1/token.tmp\" && mv -f \"$1/token.tmp\" \"$1/token\"", "sh", root.tokenDir]
    stdinEnabled: true
    onStarted: {
      write(root.pendingToken + "\n")
      root.pendingToken = ""
      stdinEnabled = false
    }
    onExited: function(code) {
      if (code === 0) {
        root.clearError()
        if (root.lightMode) root.setViewMode("traffic")
        trafficView.optionsOpen = false
        root.hasToken = true
        root.probeToken()
        root.showConfirmation("Token saved")
        root.refresh()
      } else {
        root.notify("Token not saved", "Could not write " + root.tokenDir + "/token", "")
      }
    }
  }

  Process {
    id: tokenProbe
    command: ["sh", "-c", "test -n \"$GITHUB_TOKEN\" || test -s \"$1/token\"", "sh", root.tokenDir]
    onExited: function(code) {
      root.hasToken = code === 0
      root.tokenChecked = true
    }
  }

  Process {
    id: tokenRemover
    command: ["rm", "-f", root.tokenDir + "/token"]
    onExited: function(code) {
      root.probeToken()
      if (code === 0) {
        root.clearError()
        if (!root.lightMode) root.errorCode = "no-token"
        root.confirmation = "Token removed"
        confirmTimer.restart()
      } else {
        root.notify("Token not removed", "Could not delete " + root.tokenDir + "/token", "")
      }
    }
  }

  Process {
    id: cacheRemover
  }

  Process {
    id: settingsWriter
    property string written: ""
    onExited: function(code) {
      if (code !== 0) root.notify("Settings not saved", "Could not write " + root.settingsPath, "")
      else if (written !== root.pendingSettings) Qt.callLater(root.writeSettings)
    }
  }

  FileView {
    id: settingsFile
    path: root.settingsPath
    watchChanges: false
    printErrors: false
    onLoaded: {
      try {
        var p = JSON.parse(text())
        if (!p) return
        if (["icon", "text", "both"].indexOf(p.barDisplay) >= 0) root.barDisplay = p.barDisplay
        if (["traffic", "light"].indexOf(p.viewMode) >= 0) root.viewMode = p.viewMode
        root.exportPrivate = p.exportPrivate === true
        var users = []
        var source = Array.isArray(p.lightUsers) ? p.lightUsers : (typeof p.lightUser === "string" ? [p.lightUser] : [])
        source.forEach(function(u) {
          if (root.validUser(u) && users.length < 10 && !users.some(function(x) { return root.sameUser(x, u) })) users.push(String(u))
        })
        root.lightUsers = users
        var active = users.filter(function(u) { return root.sameUser(u, p.lightUser) })
        root.lightUser = active.length > 0 ? active[0] : (users.length > 0 ? users[0] : "")
      } catch (e) {
      }
    }
  }

  FileView {
    id: trafficFile
    path: root.trafficPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
    onLoaded: {
      if (root.trafficSnapshot !== null) return
      try {
        var p = JSON.parse(text())
        if (p && p.ok === true && p.light !== true) root.trafficSnapshot = p
      } catch (e) {
      }
    }
  }

  FileView {
    id: lightFile
    path: root.lightPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
    onLoaded: {
      if (root.lightSnapshot !== null) return
      try {
        var p = JSON.parse(text())
        if (p && p.ok === true && p.light === true) root.lightSnapshot = p
      } catch (e) {
      }
    }
  }

  Timer {
    id: confirmTimer
    interval: 4000
    onTriggered: root.confirmation = ""
  }

  onOpenedChanged: {
    if (opened) {
      root.probeToken()
    } else {
      trafficView.optionsOpen = false
      trafficView.shownCount = Model.TOP_REPOS
    }
  }
  Component.onCompleted: root.probeToken()

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    padding: 0
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(trafficView.implicitWidth)
    contentHeight: panel.fittedContentHeight(trafficView.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: trafficView.editing
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) {
        if (text === "r") root.refresh()
      }

      Flickable {
        id: scroller
        anchors.fill: parent
        contentWidth: width
        contentHeight: trafficView.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        TrafficView {
          id: trafficView
          width: implicitWidth
          height: implicitHeight
          model: trafficView.exporting ? root.exportView : root.view
          mode: root.mode
          busy: root.busy
          errorCode: root.errorCode
          errorMessage: root.errorMessage
          confirmInfo: root.confirmInfo
          viewMode: root.viewMode
          lightUser: root.lightUser
          lightUsers: root.lightUsers
          foreground: Color.popups.text
          background: Color.popups.background
          accent: Color.accent
          urgent: Color.urgent
          tooltipBackground: Color.tooltip.background
          tooltipBorder: Color.tooltip.border
          hasToken: root.hasToken
          confirmation: root.confirmation
          barDisplay: root.barDisplay
          exportPrivate: root.exportPrivate
          cornerRadius: Style.cornerRadius
          fontFamily: Style.font.family
          onRefreshRequested: root.refresh()
          onLoadAnywayRequested: root.loadAnyway()
          onConfirmDismissed: root.clearError()
          onExportReportRequested: root.exportReport()
          onExportImageRequested: root.exportImage()
          onRepoActivated: function(name) {
            var base = "https://github.com/" + encodeURIComponent(root.view.user) + "/" + encodeURIComponent(name)
            Qt.openUrlExternally(root.lightMode ? base : base + "/graphs/traffic")
          }
          onTokenPageRequested: Qt.openUrlExternally("https://github.com/settings/personal-access-tokens/new")
          onTokenSubmitted: function(token) { root.saveToken(token) }
          onTokenRemovalRequested: root.removeToken()
          onBarDisplayRequested: function(value) { root.setBarDisplay(value) }
          onExportPrivateRequested: function(value) { root.setExportPrivate(value) }
          onViewModeRequested: function(value) { root.setViewMode(value) }
          onLightUserSubmitted: function(user) { root.addLightUser(user) }
          onLightUserSelected: function(user) { root.selectLightUser(user) }
          onLightUserRemoved: function(user) { root.removeLightUser(user) }
        }
      }
    }
  }
}
