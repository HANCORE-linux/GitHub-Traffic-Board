import QtQuick
import "Model.js" as Model

Rectangle {
  id: root

  property var model: null
  property string mode: "empty"
  property bool busy: false
  property string errorCode: ""
  property string errorMessage: ""
  property bool exporting: false
  property int shownCount: Model.TOP_REPOS
  property string viewMode: "traffic"
  property string lightUser: ""
  property var lightUsers: []
  readonly property int maxLightUsers: 10
  property var confirmInfo: null
  property bool hasToken: false
  property string confirmation: ""
  property string barDisplay: "both"
  property bool exportPrivate: false
  property bool optionsOpen: false
  property string repoMode: "all"
  property var selectedRepos: []
  property var availableRepos: []

  property color foreground: "#d3d7b5"
  property color background: "#040704"
  property color accent: "#e33d84"
  property color urgent: "#ee585d"
  property color tooltipBackground: background
  property color tooltipBorder: foreground
  property real cornerRadius: 4
  property string fontFamily: "monospace"

  readonly property bool editing: tokenInput.activeFocus || optionsTokenInput.activeFocus || lightField.input.activeFocus || optionsUserField.input.activeFocus || repoFilterInput.activeFocus

  signal refreshRequested()
  signal exportReportRequested()
  signal exportImageRequested()
  signal repoActivated(string name)
  signal tokenPageRequested()
  signal tokenSubmitted(string token)
  signal tokenRemovalRequested()
  signal barDisplayRequested(string value)
  signal exportPrivateRequested(bool value)
  signal viewModeRequested(string value)
  signal lightUserSubmitted(string user)
  signal lightUserSelected(string user)
  signal lightUserRemoved(string user)
  signal loadAnywayRequested()
  signal confirmDismissed()
  signal chooseReposRequested()
  signal repoModeRequested(string value)
  signal repoToggled(string name)
  signal reposSelected(var names)
  signal reposCleared()

  readonly property color dim: Qt.darker(foreground, 1.4)
  readonly property int pad: 14
  readonly property int nameW: 204
  readonly property int cell: 11
  readonly property int cellGap: 3
  readonly property int laneX: nameW + 12
  readonly property int laneW: 14 * cell + 13 * cellGap
  readonly property int viewsX: laneX + laneW + 14
  readonly property int viewsW: 54
  readonly property int clonesX: viewsX + viewsW + 8
  readonly property int clonesW: 43
  readonly property int contentW: clonesX + clonesW
  readonly property var trafficModel: model !== null && model.light !== true ? model : null
  readonly property var lightModel: model !== null && model.light === true ? model : null
  readonly property bool isLight: lightModel !== null
  readonly property bool hasData: model !== null && (mode === "data" || mode === "light")
  readonly property bool showData: hasData && !optionsOpen
  readonly property bool showTraffic: showData && !isLight
  readonly property bool showLight: showData && isLight
  readonly property var nextPage: hasData ? Model.nextStep(Math.min(shownCount, model.repoCount), model.repoCount) : null
  readonly property var shownRepos: hasData ? model.repos.slice(0, Math.min(shownCount, model.repos.length)) : []
  readonly property bool showNotice: errorCode !== "" && errorCode !== "no-token" && errorCode !== "confirm"
  readonly property var filteredRepos: {
    var q = repoFilterInput.text.trim().toLowerCase()
    return availableRepos.filter(function(r) { return q === "" || r.name.toLowerCase().indexOf(q) >= 0 })
  }
  readonly property string repoSummary: availableRepos.length === 0 ? "Your repositories show up here after the next refresh."
    : repoMode === "all" ? "All " + Model.fmt(availableRepos.length) + " repositories, about " + Model.fmt(Model.requestsFor(availableRepos.length)) + " API requests per refresh."
    : selectedRepos.length === 0 ? "Nothing selected yet, so all repositories load."
    : Model.fmt(selectedRepos.length) + " of " + Model.fmt(availableRepos.length) + " selected, about " + Model.fmt(Model.requestsFor(selectedRepos.length)) + " API requests per refresh."

  property int hoverRow: -1
  property int hoverDay: -1

  implicitWidth: contentW + pad * 2
  implicitHeight: body.implicitHeight + pad * 2
  color: exporting ? rgba(background, 1.0) : "transparent"
  radius: exporting ? cornerRadius : 0
  border.width: exporting ? 1 : 0
  border.color: rgba(foreground, 0.25)

  function rgba(c, a) {
    var q = Qt.lighter(c, 1.0)
    return Qt.rgba(q.r, q.g, q.b, a)
  }
  function dayX(i) { return laneX + i * (cell + cellGap) }
  function levelColor(l) {
    if (l <= 0) return rgba(foreground, 0.06)
    return rgba(accent, [0, 0.32, 0.52, 0.75, 1.0][l])
  }
  function normalizeUser(text) {
    var u = String(text || "").trim()
    u = u.replace(/^https?:\/\//i, "").replace(/^(www\.)?github\.com\//i, "").replace(/^@/, "")
    return u.split(/[\/?#\s]/)[0]
  }

  function submitUser(input, hint) {
    var u = root.normalizeUser(input.text)
    if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(u)) {
      hint.text = "That is not a GitHub username."
      return
    }
    hint.text = ""
    input.text = ""
    root.lightUserSubmitted(u)
  }

  function sameUser(a, b) {
    return String(a || "").toLowerCase() === String(b || "").toLowerCase()
  }

  function submitToken(input, hint) {
    var t = input.text.trim()
    if (!/^[A-Za-z0-9_]{20,255}$/.test(t)) {
      hint.text = "That does not look like a GitHub token."
      return
    }
    input.text = ""
    hint.text = ""
    root.tokenSubmitted(t)
  }

  component MoreRow: Item {
    height: 24
    visible: root.hasData && (root.nextPage !== null || root.shownCount > Model.TOP_REPOS)

    Text {
      visible: root.nextPage !== null
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      text: root.nextPage ? root.nextPage.label : ""
      color: nextMouse.containsMouse ? root.foreground : root.dim
      font.family: root.fontFamily
      font.pixelSize: 11

      MouseArea {
        id: nextMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: if (root.nextPage) root.shownCount = root.nextPage.count
      }
    }

    Text {
      visible: root.shownCount > Model.TOP_REPOS
      textFormat: Text.PlainText
      x: parent.width - width
      anchors.verticalCenter: parent.verticalCenter
      text: "Show top " + Model.TOP_REPOS
      color: topMouse.containsMouse ? root.foreground : root.dim
      font.family: root.fontFamily
      font.pixelSize: 11

      MouseArea {
        id: topMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.shownCount = Model.TOP_REPOS
      }
    }
  }

  component UserField: Rectangle {
    property alias input: field
    property alias text: field.text
    signal submitted()
    width: 262
    height: 28
    radius: root.cornerRadius
    color: root.rgba(root.foreground, 0.04)
    border.width: 1
    border.color: root.rgba(root.foreground, field.activeFocus ? 0.25 : 0.4)

    TextInput {
      id: field
      anchors.fill: parent
      anchors.leftMargin: 10
      anchors.rightMargin: 10
      verticalAlignment: TextInput.AlignVCenter
      clip: true
      maximumLength: 39
      color: root.foreground
      selectionColor: root.rgba(root.foreground, 0.35)
      font.family: root.fontFamily
      font.pixelSize: 12
      onAccepted: parent.submitted()
    }

    Text {
      visible: field.text === ""
      textFormat: Text.PlainText
      x: 10
      anchors.verticalCenter: parent.verticalCenter
      text: "GitHub username"
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: 12
    }
  }

  component Chip: Rectangle {
    id: chip
    property string label: ""
    property string glyph: ""
    property bool available: true
    property bool square: false
    property bool selected: false
    signal clicked()
    width: square ? 28 : chipRow.implicitWidth + 20
    height: 28
    radius: root.cornerRadius
    opacity: available ? 1 : 0.4
    color: root.rgba(root.foreground, selected ? 0.18 : chipMouse.containsMouse && available ? 0.08 : 0.04)
    border.width: selected ? 0 : 1
    border.color: root.rgba(root.foreground, chipMouse.containsMouse && available ? 0.25 : 0.4)

    Row {
      id: chipRow
      anchors.centerIn: parent
      spacing: 6

      Text {
        visible: chip.glyph !== ""
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: chip.glyph
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: chip.square ? 14 : 12
      }

      Text {
        visible: chip.label !== ""
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: chip.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 12
      }
    }

    MouseArea {
      id: chipMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: chip.available ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: if (chip.available) chip.clicked()
    }
  }

  Column {
    id: body
    x: root.pad
    y: root.pad
    width: root.contentW
    spacing: 14

    Item {
      width: parent.width
      height: 40

      Text {
        id: heroIcon
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        text: root.mode === "setup" ? "\uf43d" : root.viewMode === "light" ? "\uf41e" : "\uf441"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 24
      }

      Column {
        anchors.left: heroIcon.right
        anchors.leftMargin: 14
        anchors.right: actions.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: root.viewMode === "light" ? (root.hasData ? root.model.user : "GitHub") : "GitHub traffic"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 14
          font.bold: true
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: (root.busy ? "Refreshing" : root.mode === "setup" ? "Not connected"
                : root.isLight && root.hasData ? "Public data, updated " + root.model.updated
                : root.viewMode === "light" ? "Light mode"
                : root.hasData ? "Last 14 days, updated " + root.model.updated : "No data yet").toUpperCase()
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
          font.letterSpacing: 1.2
          elide: Text.ElideRight
        }
      }

      Row {
        id: actions
        visible: !root.exporting
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Rectangle {
          visible: root.showData
          width: pill.implicitWidth + 20
          height: 28
          radius: root.cornerRadius
          color: root.rgba(root.foreground, 0.04)
          border.width: 1
          border.color: root.rgba(root.foreground, 0.4)

          Text {
            id: pill
            textFormat: Text.PlainText
            anchors.centerIn: parent
            text: root.hasData ? root.model.repoCount + " repos" : ""
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 12
            font.bold: true
          }
        }

        Chip {
          square: true
          glyph: "\udb81\udc93"
          selected: root.optionsOpen
          onClicked: root.optionsOpen = !root.optionsOpen
        }

        Chip {
          visible: root.mode !== "setup"
          square: true
          glyph: "󰑐"
          available: !root.busy
          onClicked: root.refreshRequested()
        }
      }
    }

    Rectangle {
      visible: root.confirmation !== "" && !root.exporting
      width: parent.width
      height: 30
      radius: root.cornerRadius
      color: root.rgba(root.foreground, 0.06)

      Text {
        id: confirmGlyph
        textFormat: Text.PlainText
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        text: "\uf42e"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 12
      }

      Text {
        textFormat: Text.PlainText
        anchors.left: confirmGlyph.right
        anchors.leftMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        text: root.confirmation
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 11
        elide: Text.ElideRight
      }
    }

    Rectangle {
      visible: root.showNotice && !root.optionsOpen
      width: parent.width
      height: 30
      radius: root.cornerRadius
      color: root.rgba(root.urgent, 0.10)

      Rectangle {
        width: 2
        height: parent.height
        radius: 1
        color: root.urgent
      }

      Text {
        id: alertGlyph
        textFormat: Text.PlainText
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        text: ""
        color: root.urgent
        font.family: root.fontFamily
        font.pixelSize: 12
      }

      Text {
        textFormat: Text.PlainText
        anchors.left: alertGlyph.right
        anchors.leftMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        text: Model.errorText(root.errorCode, root.errorMessage)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 11
        elide: Text.ElideRight
      }
    }

    Rectangle {
      visible: root.showTraffic && root.trafficModel !== null && root.trafficModel.skippedText !== "" && !root.exporting
      width: parent.width
      height: skippedLabel.implicitHeight + 16
      radius: root.cornerRadius
      color: root.rgba(root.foreground, 0.06)

      Text {
        id: skippedGlyph
        textFormat: Text.PlainText
        x: 12
        y: 8
        text: ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: 12
      }

      Text {
        id: skippedLabel
        textFormat: Text.PlainText
        anchors.left: skippedGlyph.right
        anchors.leftMargin: 8
        anchors.right: parent.right
        anchors.rightMargin: 10
        y: 8
        text: root.trafficModel ? root.trafficModel.skippedText : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 11
        wrapMode: Text.WordWrap
        maximumLineCount: 2
        elide: Text.ElideRight
      }
    }

    Rectangle {
      visible: root.errorCode === "confirm" && root.confirmInfo !== null && !root.optionsOpen
      width: parent.width
      height: confirmCol.implicitHeight + 20
      radius: root.cornerRadius
      color: root.rgba(root.accent, 0.10)

      Rectangle {
        width: 2
        height: parent.height
        radius: 1
        color: root.accent
      }

      Column {
        id: confirmCol
        x: 12
        y: 10
        width: parent.width - 24
        spacing: 10

        Text {
          textFormat: Text.PlainText
          width: parent.width
          wrapMode: Text.WordWrap
          text: root.confirmInfo
            ? "Loading traffic for " + Model.fmt(root.confirmInfo.repoCount) + " repositories uses about " + Model.fmt(root.confirmInfo.requests) + " of your 5,000 GitHub API requests per hour."
            : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 12
          lineHeight: 1.25
        }

        Row {
          spacing: 8

          Chip {
            label: "Load anyway"
            glyph: "\udb81\udc50"
            available: !root.busy
            onClicked: root.loadAnywayRequested()
          }

          Chip {
            label: "Choose repositories"
            onClicked: root.chooseReposRequested()
          }

          Chip {
            label: "Cancel"
            onClicked: root.confirmDismissed()
          }
        }
      }
    }

    Flow {
      visible: root.viewMode === "light" && root.lightUsers.length > 1 && !root.optionsOpen && !root.exporting
      width: parent.width
      spacing: 8

      Repeater {
        model: root.lightUsers

        Chip {
          label: modelData
          selected: root.sameUser(modelData, root.lightUser)
          available: !root.busy
          onClicked: if (!root.sameUser(modelData, root.lightUser)) root.lightUserSelected(modelData)
        }
      }
    }

    Column {
      visible: root.mode === "light-empty" && !root.optionsOpen
      width: parent.width
      spacing: 12

      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.WordWrap
        text: root.lightUsers.length === 0
          ? "Show the public repositories of any GitHub user. No token needed."
          : "No data for " + root.lightUser + " yet."
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 12
        lineHeight: 1.25
      }

      Chip {
        visible: root.lightUsers.length > 0
        label: root.busy ? "Loading" : "Load"
        glyph: "\udb81\udc50"
        available: !root.busy
        onClicked: root.refreshRequested()
      }

      Row {
        visible: root.lightUsers.length === 0
        spacing: 8

        UserField {
          id: lightField
          onSubmitted: root.submitUser(lightField.input, lightHint)
        }

        Chip {
          label: root.busy ? "Loading" : "Load"
          glyph: "\udb81\udc50"
          available: !root.busy && lightField.text.trim() !== ""
          onClicked: root.submitUser(lightField.input, lightHint)
        }
      }

      Text {
        id: lightHint
        visible: text !== "" && root.lightUsers.length === 0
        textFormat: Text.PlainText
        color: root.urgent
        font.family: root.fontFamily
        font.pixelSize: 11
      }
    }

    Column {
      visible: root.mode === "empty" && !root.optionsOpen
      width: parent.width
      spacing: 12

      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.WordWrap
        text: "Load the last 14 days of views, clones and referrers for your own repositories."
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 12
        lineHeight: 1.25
      }

      Chip {
        label: root.busy ? "Loading" : "Load traffic"
        glyph: "󰑐"
        available: !root.busy
        onClicked: root.refreshRequested()
      }
    }

    Column {
      visible: root.showTraffic
      width: parent.width
      spacing: 6

      Item {
        width: parent.width
        height: 46

        Text {
          id: viewsNum
          textFormat: Text.PlainText
          y: -4
          text: root.trafficModel ? Model.fmt(root.trafficModel.views) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 26
        }

        Text {
          textFormat: Text.PlainText
          anchors.left: viewsNum.right
          anchors.leftMargin: 6
          anchors.baseline: viewsNum.baseline
          text: "views"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }

        Rectangle {
          x: root.laneX
          y: parent.height - 1
          width: root.laneW
          height: 1
          color: root.rgba(root.foreground, 0.12)
        }

        Repeater {
          model: root.showTraffic && root.trafficModel ? root.trafficModel.dailyViews : []

          Rectangle {
            visible: modelData > 0
            x: root.dayX(index)
            width: root.cell
            height: Math.max(2, Math.round(modelData / (root.trafficModel ? root.trafficModel.maxViews : 1) * 44))
            y: parent.height - 1 - height
            radius: 2
            color: root.accent
          }
        }

        Text {
          textFormat: Text.PlainText
          x: root.contentW - width
          y: 2
          text: root.trafficModel ? Model.trendText(root.trafficModel.viewsTrend) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 14
        }

        Text {
          textFormat: Text.PlainText
          x: root.contentW - width
          anchors.bottom: parent.bottom
          text: "vs prior week"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }
      }

      Item {
        width: parent.width
        height: 26

        Text {
          id: clonesNum
          textFormat: Text.PlainText
          anchors.bottom: parent.bottom
          anchors.bottomMargin: -2
          text: root.trafficModel ? Model.fmt(root.trafficModel.clones) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 16
        }

        Text {
          textFormat: Text.PlainText
          anchors.left: clonesNum.right
          anchors.leftMargin: 6
          anchors.bottom: parent.bottom
          text: "clones"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }

        Rectangle {
          x: root.laneX
          y: parent.height - 1
          width: root.laneW
          height: 1
          color: root.rgba(root.foreground, 0.12)
        }

        Repeater {
          model: root.showTraffic && root.trafficModel ? root.trafficModel.dailyClones : []

          Rectangle {
            visible: modelData > 0
            x: root.dayX(index)
            width: root.cell
            height: Math.max(2, Math.round(modelData / (root.trafficModel ? root.trafficModel.maxClones : 1) * 24))
            y: parent.height - 1 - height
            radius: 2
            color: root.rgba(root.foreground, 0.5)
          }
        }

        Text {
          textFormat: Text.PlainText
          x: root.contentW - width
          anchors.bottom: parent.bottom
          text: root.trafficModel ? Model.trendText(root.trafficModel.clonesTrend) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 12
        }
      }

      Item {
        width: parent.width
        height: 12

        Text {
          textFormat: Text.PlainText
          x: root.laneX
          text: root.trafficModel ? root.trafficModel.firstDay : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }

        Text {
          textFormat: Text.PlainText
          x: root.laneX + root.laneW - width
          text: root.trafficModel ? root.trafficModel.lastDay : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }
      }
    }

    Rectangle {
      visible: root.showTraffic
      width: parent.width
      height: 1
      color: root.rgba(root.foreground, 0.12)
    }

    Column {
      id: matrix
      visible: root.showTraffic
      width: parent.width

      Item {
        width: parent.width
        height: 18

        Text {
          textFormat: Text.PlainText
          text: "Repositories by views"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Row {
          x: root.laneX + root.laneW - width
          spacing: 3

          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            rightPadding: 3
            text: "less"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 10
          }

          Repeater {
            model: 5

            Rectangle {
              anchors.verticalCenter: parent.verticalCenter
              width: 8
              height: 8
              radius: 2
              color: root.levelColor(index)
            }
          }

          Text {
            textFormat: Text.PlainText
            anchors.verticalCenter: parent.verticalCenter
            leftPadding: 3
            text: "more"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 10
          }
        }

        Text {
          textFormat: Text.PlainText
          x: root.viewsX + root.viewsW - width
          text: "views"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }

        Text {
          textFormat: Text.PlainText
          x: root.clonesX + root.clonesW - width
          text: "clones"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }
      }

      Repeater {
        model: root.showTraffic && root.trafficModel ? root.trafficModel.repos.slice(0, Math.min(root.shownCount, root.trafficModel.repos.length)) : []

        Item {
          id: row
          readonly property var r: modelData
          readonly property bool hot: rowMouse.containsMouse
          width: matrix.width
          height: 22

          Rectangle {
            visible: row.hot && !root.exporting
            x: -6
            width: parent.width + 12
            height: parent.height
            radius: root.cornerRadius
            color: root.rgba(root.foreground, 0.08)
          }

          Text {
            id: lock
            visible: row.r.private === true
            textFormat: Text.PlainText
            x: root.nameW - width
            anchors.verticalCenter: parent.verticalCenter
            text: ""
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 11
          }

          Text {
            textFormat: Text.PlainText
            width: root.nameW - (row.r.private ? lock.width + 6 : 0)
            anchors.verticalCenter: parent.verticalCenter
            text: row.r.name
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 12
            elide: Text.ElideRight
          }

          Repeater {
            model: 14

            Rectangle {
              x: root.dayX(index)
              anchors.verticalCenter: parent.verticalCenter
              width: root.cell
              height: root.cell
              radius: 2
              color: root.levelColor(row.r.levels ? row.r.levels[index] : 0)
              border.width: row.hot && root.hoverRow === row.index && root.hoverDay === index && !root.exporting ? 1 : 0
              border.color: root.foreground
            }
          }

          Text {
            textFormat: Text.PlainText
            x: root.viewsX + root.viewsW - width
            anchors.verticalCenter: parent.verticalCenter
            text: Model.fmt(row.r.views)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 12
          }

          Text {
            textFormat: Text.PlainText
            x: root.clonesX + root.clonesW - width
            anchors.verticalCenter: parent.verticalCenter
            text: Model.fmt(row.r.clones)
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 12
          }

          MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onPositionChanged: function(mouse) {
              var d = Math.floor((mouse.x - root.laneX) / (root.cell + root.cellGap))
              root.hoverRow = index
              root.hoverDay = mouse.x >= root.laneX && mouse.x < root.laneX + root.laneW && d >= 0 && d < 14 ? d : -1
            }
            onExited: if (root.hoverRow === index) { root.hoverRow = -1; root.hoverDay = -1 }
            onClicked: root.repoActivated(row.r.name)
          }
        }
      }

      MoreRow {
        width: parent.width
      }
    }

    Rectangle {
      visible: root.showTraffic && root.trafficModel !== null && root.trafficModel.referrers.length > 0
      width: parent.width
      height: 1
      color: root.rgba(root.foreground, 0.12)
    }

    Column {
      id: refs
      visible: root.showTraffic && root.trafficModel !== null && root.trafficModel.referrers.length > 0
      width: parent.width

      Item {
        width: parent.width
        height: 18

        Text {
          textFormat: Text.PlainText
          text: "Referrers"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Text {
          textFormat: Text.PlainText
          x: root.viewsX + root.viewsW - width
          text: "views"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }
      }

      Repeater {
        model: root.showTraffic && root.trafficModel ? root.trafficModel.referrers : []

        Item {
          width: refs.width
          height: 20

          Text {
            textFormat: Text.PlainText
            width: root.nameW
            anchors.verticalCenter: parent.verticalCenter
            text: modelData.name
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 12
            elide: Text.ElideRight
          }

          Rectangle {
            x: root.laneX
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(4, Math.round(modelData.count / Math.max(1, root.trafficModel ? root.trafficModel.referrers[0].count : 1) * root.laneW))
            height: 4
            radius: 2
            color: root.rgba(root.foreground, 0.38)
          }

          Text {
            textFormat: Text.PlainText
            x: root.viewsX + root.viewsW - width
            anchors.verticalCenter: parent.verticalCenter
            text: Model.fmt(modelData.count)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 12
          }
        }
      }
    }

    Column {
      visible: root.showLight
      width: parent.width
      spacing: 6

      Item {
        width: parent.width
        height: 46

        Text {
          textFormat: Text.PlainText
          y: -4
          text: root.lightModel ? Model.fmt(root.lightModel.stars) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 26
        }

        Text {
          textFormat: Text.PlainText
          anchors.bottom: parent.bottom
          text: "stars"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }

        Text {
          textFormat: Text.PlainText
          x: root.contentW - width
          y: 2
          text: root.lightModel ? Model.fmt(root.lightModel.followers) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 14
        }

        Text {
          textFormat: Text.PlainText
          x: root.contentW - width
          anchors.bottom: parent.bottom
          text: "followers"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }
      }
    }

    Rectangle {
      visible: root.showLight
      width: parent.width
      height: 1
      color: root.rgba(root.foreground, 0.12)
    }

    Column {
      id: lightList
      visible: root.showLight
      width: parent.width

      Item {
        width: parent.width
        height: 18

        Text {
          textFormat: Text.PlainText
          text: "Repositories by stars"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Text {
          textFormat: Text.PlainText
          x: root.laneX + root.laneW - width
          text: "updated"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }

        Text {
          textFormat: Text.PlainText
          x: root.viewsX + root.viewsW - width
          text: "stars"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
        }
      }

      Repeater {
        model: root.showLight && root.lightModel ? root.lightModel.repos.slice(0, Math.min(root.shownCount, root.lightModel.repos.length)) : []

        Item {
          id: lightRow
          readonly property var r: modelData
          width: lightList.width
          height: 22

          Rectangle {
            visible: lightMouse.containsMouse && !root.exporting
            x: -6
            width: parent.width + 12
            height: parent.height
            radius: root.cornerRadius
            color: root.rgba(root.foreground, 0.08)
          }

          Text {
            textFormat: Text.PlainText
            width: root.nameW
            anchors.verticalCenter: parent.verticalCenter
            text: lightRow.r.name
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 12
            elide: Text.ElideRight
          }

          Text {
            textFormat: Text.PlainText
            x: root.laneX
            width: root.laneW - 70
            anchors.verticalCenter: parent.verticalCenter
            text: lightRow.r.language
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 11
            elide: Text.ElideRight
          }

          Text {
            textFormat: Text.PlainText
            x: root.laneX + root.laneW - width
            anchors.verticalCenter: parent.verticalCenter
            text: lightRow.r.updated
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 11
          }

          Text {
            textFormat: Text.PlainText
            x: root.viewsX + root.viewsW - width
            anchors.verticalCenter: parent.verticalCenter
            text: Model.fmt(lightRow.r.stars)
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 12
          }

          MouseArea {
            id: lightMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.repoActivated(lightRow.r.name)
          }
        }
      }

      MoreRow {
        width: parent.width
      }
    }

    Column {
      id: options
      visible: root.optionsOpen && !root.exporting
      width: parent.width
      spacing: 16

      Column {
        width: parent.width
        spacing: 8

        Text {
          textFormat: Text.PlainText
          text: "Mode"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Row {
          spacing: 8

          Chip {
            label: "Traffic"
            selected: root.viewMode === "traffic"
            onClicked: root.viewModeRequested("traffic")
          }

          Chip {
            label: "Light"
            selected: root.viewMode === "light"
            onClicked: root.viewModeRequested("light")
          }
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          wrapMode: Text.WordWrap
          text: root.viewMode === "light"
            ? "Public repositories and stars of any GitHub user. No token, about 2 API requests per refresh."
            : "Views, clones and referrers of your own repositories. Needs a token."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }

        Column {
          visible: root.viewMode === "light"
          width: parent.width
          spacing: 6
          topPadding: 4

          Repeater {
            model: root.lightUsers

            Item {
              id: userItem
              readonly property bool active: root.sameUser(modelData, root.lightUser)
              width: parent.width
              height: 28

              Rectangle {
                width: parent.width - 36
                height: 28
                radius: root.cornerRadius
                color: root.rgba(root.foreground, userItem.active ? 0.18 : userMouse.containsMouse ? 0.08 : 0.04)
                border.width: userItem.active ? 0 : 1
                border.color: root.rgba(root.foreground, 0.4)

                Text {
                  textFormat: Text.PlainText
                  x: 10
                  width: parent.width - 20
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: 12
                  elide: Text.ElideRight
                }

                MouseArea {
                  id: userMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: if (!userItem.active) root.lightUserSelected(modelData)
                }
              }

              Chip {
                x: parent.width - width
                square: true
                glyph: "\uf48e"
                available: !root.busy
                onClicked: root.lightUserRemoved(modelData)
              }
            }
          }

          Row {
            spacing: 8

            UserField {
              id: optionsUserField
              onSubmitted: if (root.lightUsers.length < root.maxLightUsers) root.submitUser(optionsUserField.input, optionsHint)
            }

            Chip {
              label: "Add"
              available: optionsUserField.text.trim() !== "" && root.lightUsers.length < root.maxLightUsers
              onClicked: root.submitUser(optionsUserField.input, optionsHint)
            }
          }

          Text {
            id: optionsHint
            visible: text !== ""
            textFormat: Text.PlainText
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: 11
          }

          Text {
            visible: root.lightUsers.length >= root.maxLightUsers
            textFormat: Text.PlainText
            text: "Up to " + root.maxLightUsers + " users. Remove one to add another."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 11
          }
        }
      }

      Rectangle {
        visible: root.viewMode === "traffic"
        width: parent.width
        height: 1
        color: root.rgba(root.foreground, 0.12)
      }

      Column {
        visible: root.viewMode === "traffic"
        width: parent.width
        spacing: 8

        Text {
          textFormat: Text.PlainText
          text: "Repositories"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Row {
          spacing: 8

          Chip {
            label: "All"
            selected: root.repoMode === "all"
            onClicked: root.repoModeRequested("all")
          }

          Chip {
            label: "Selected"
            selected: root.repoMode === "selected"
            onClicked: root.repoModeRequested("selected")
          }
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          wrapMode: Text.WordWrap
          text: root.repoSummary
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }

        Row {
          visible: root.repoMode === "selected" && root.availableRepos.length > 0
          spacing: 8

          Rectangle {
            width: 262
            height: 28
            radius: root.cornerRadius
            color: root.rgba(root.foreground, 0.04)
            border.width: 1
            border.color: root.rgba(root.foreground, repoFilterInput.activeFocus ? 0.25 : 0.4)

            TextInput {
              id: repoFilterInput
              anchors.fill: parent
              anchors.leftMargin: 10
              anchors.rightMargin: 10
              verticalAlignment: TextInput.AlignVCenter
              clip: true
              maximumLength: 100
              color: root.foreground
              selectionColor: root.rgba(root.foreground, 0.35)
              font.family: root.fontFamily
              font.pixelSize: 12
            }

            Text {
              visible: repoFilterInput.text === ""
              textFormat: Text.PlainText
              x: 10
              anchors.verticalCenter: parent.verticalCenter
              text: "Filter repositories"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: 12
            }
          }

          Chip {
            label: "Select shown"
            available: root.filteredRepos.length > 0
            onClicked: root.reposSelected(root.filteredRepos.map(function(r) { return r.name }))
          }

          Chip {
            label: "Clear"
            available: root.selectedRepos.length > 0
            onClicked: root.reposCleared()
          }
        }

        Rectangle {
          visible: root.repoMode === "selected" && root.filteredRepos.length > 0
          width: parent.width
          height: Math.min(root.filteredRepos.length, 10) * 24 + 2
          radius: root.cornerRadius
          color: "transparent"
          border.width: 1
          border.color: root.rgba(root.foreground, 0.4)

          ListView {
            id: repoList
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.filteredRepos

            delegate: Item {
              id: repoRow
              readonly property bool chosen: root.selectedRepos.indexOf(modelData.name) >= 0
              width: repoList.width
              height: 24

              Rectangle {
                anchors.fill: parent
                color: root.rgba(root.foreground, repoMouse.containsMouse ? 0.08 : 0)
              }

              Text {
                id: repoCheck
                textFormat: Text.PlainText
                x: 10
                width: 14
                anchors.verticalCenter: parent.verticalCenter
                text: repoRow.chosen ? "\uf42e" : ""
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: 12
              }

              Text {
                textFormat: Text.PlainText
                anchors.left: repoCheck.right
                anchors.leftMargin: 8
                anchors.right: repoLock.left
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.name
                color: repoRow.chosen ? root.foreground : root.dim
                font.family: root.fontFamily
                font.pixelSize: 12
                elide: Text.ElideRight
              }

              Text {
                id: repoLock
                textFormat: Text.PlainText
                x: parent.width - width - 12
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.private ? "\uf456" : ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: 11
              }

              MouseArea {
                id: repoMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.repoToggled(modelData.name)
              }
            }
          }

          Rectangle {
            visible: repoList.contentHeight > repoList.height
            x: parent.width - 5
            y: 1 + repoList.visibleArea.yPosition * repoList.height
            width: 2
            height: repoList.visibleArea.heightRatio * repoList.height
            radius: 1
            color: root.rgba(root.foreground, 0.35)
          }
        }

        Text {
          visible: root.repoMode === "selected" && root.availableRepos.length > 0 && root.filteredRepos.length === 0
          textFormat: Text.PlainText
          text: "No repository matches."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }
      }

      Rectangle {
        width: parent.width
        height: 1
        color: root.rgba(root.foreground, 0.12)
      }

      Column {
        width: parent.width
        spacing: 8

        Text {
          textFormat: Text.PlainText
          text: "Bar widget"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Row {
          spacing: 8

          Repeater {
            model: [
              { value: "icon", label: "Icon" },
              { value: "text", label: "Text" },
              { value: "both", label: "Icon and text" }
            ]

            Chip {
              label: modelData.label
              selected: root.barDisplay === modelData.value
              onClicked: root.barDisplayRequested(modelData.value)
            }
          }
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: "Vertical bars always show the icon."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 11
        }
      }

      Rectangle {
        width: parent.width
        height: 1
        color: root.rgba(root.foreground, 0.12)
      }

      Column {
        width: parent.width
        spacing: 8

        Text {
          textFormat: Text.PlainText
          text: "Token"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: 10
          font.bold: true
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: root.hasToken ? "Saved in ~/.config/gh-traffic/token" : "No token saved. Traffic needs a fine-grained token with Administration: Read-only."
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: 12
          wrapMode: Text.WordWrap
          lineHeight: 1.2
        }

        Chip {
          visible: root.hasToken
          label: "Remove token"
          available: !root.busy
          onClicked: root.tokenRemovalRequested()
        }

        Chip {
          visible: !root.hasToken
          label: "Open token page"
          glyph: "\udb80\udfcc"
          onClicked: root.tokenPageRequested()
        }

        Row {
          visible: !root.hasToken
          spacing: 8

          Rectangle {
            width: 262
            height: 28
            radius: root.cornerRadius
            color: root.rgba(root.foreground, 0.04)
            border.width: 1
            border.color: root.rgba(root.foreground, optionsTokenInput.activeFocus ? 0.25 : 0.4)

            TextInput {
              id: optionsTokenInput
              anchors.fill: parent
              anchors.leftMargin: 10
              anchors.rightMargin: 10
              verticalAlignment: TextInput.AlignVCenter
              echoMode: TextInput.Password
              clip: true
              color: root.foreground
              selectionColor: root.rgba(root.foreground, 0.35)
              font.family: root.fontFamily
              font.pixelSize: 12
              onAccepted: root.submitToken(optionsTokenInput, optionsTokenHint)
            }

            Text {
              visible: optionsTokenInput.text === ""
              textFormat: Text.PlainText
              x: 10
              anchors.verticalCenter: parent.verticalCenter
              text: "github_pat_..."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: 12
            }
          }

          Chip {
            label: "Save"
            available: optionsTokenInput.text.trim() !== "" && !root.busy
            onClicked: root.submitToken(optionsTokenInput, optionsTokenHint)
          }
        }

        Text {
          id: optionsTokenHint
          visible: text !== "" && !root.hasToken
          textFormat: Text.PlainText
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: 11
        }
      }
    }

    Column {
      id: setup
      visible: root.mode === "setup" && !root.optionsOpen
      width: parent.width
      spacing: 16

      Text {
        textFormat: Text.PlainText
        width: parent.width
        wrapMode: Text.WordWrap
        text: "Add a GitHub token to see who views and clones your repositories."
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 12
        lineHeight: 1.25
      }

      Repeater {
        model: [
          { title: "Open GitHub's fine-grained token page", hint: "", action: "page" },
          { title: "Name it, for example gh-traffic, and pick an expiration", hint: "", action: "" },
          { title: "Repository access: All repositories", hint: "Or only the repositories you want to see", action: "" },
          { title: "Repository permissions: Administration, Read-only", hint: "Nothing else is needed", action: "" }
        ]

        Item {
          width: setup.width
          height: stepCol.implicitHeight

          Rectangle {
            width: 20
            height: 20
            radius: root.cornerRadius
            color: "transparent"
            border.width: 1
            border.color: root.rgba(root.foreground, 0.4)

            Text {
              textFormat: Text.PlainText
              anchors.centerIn: parent
              text: String(index + 1)
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: 11
              font.bold: true
            }
          }

          Column {
            id: stepCol
            x: 32
            width: parent.width - 32
            spacing: 6

            Item {
              width: parent.width
              height: 20

              Text {
                textFormat: Text.PlainText
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                text: modelData.title
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: 12
                font.bold: true
                elide: Text.ElideRight
              }
            }

            Text {
              visible: modelData.hint !== ""
              textFormat: Text.PlainText
              width: parent.width
              text: modelData.hint
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: 11
            }

            Chip {
              visible: modelData.action === "page"
              label: "Open token page"
              glyph: "\udb80\udfcc"
              onClicked: root.tokenPageRequested()
            }
          }
        }
      }

      Item {
        width: setup.width
        height: stepFive.implicitHeight

        Rectangle {
          width: 20
          height: 20
          radius: root.cornerRadius
          color: "transparent"
          border.width: 1
          border.color: root.rgba(root.foreground, 0.4)

          Text {
            textFormat: Text.PlainText
            anchors.centerIn: parent
            text: "5"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: 11
            font.bold: true
          }
        }

        Column {
          id: stepFive
          x: 32
          width: parent.width - 32
          spacing: 6

          Item {
            width: parent.width
            height: 20

            Text {
              textFormat: Text.PlainText
              anchors.verticalCenter: parent.verticalCenter
              width: parent.width
              text: "Generate the token, copy it and paste it here"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: 12
              font.bold: true
              elide: Text.ElideRight
            }
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            text: "Saved to ~/.config/gh-traffic/token, readable only by you"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: 11
          }

          Row {
            spacing: 8

            Rectangle {
              width: 262
              height: 28
              radius: root.cornerRadius
              color: root.rgba(root.foreground, 0.04)
              border.width: 1
              border.color: root.rgba(root.foreground, tokenInput.activeFocus ? 0.25 : 0.4)

              TextInput {
                id: tokenInput
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                verticalAlignment: TextInput.AlignVCenter
                echoMode: TextInput.Password
                clip: true
                color: root.foreground
                selectionColor: root.rgba(root.foreground, 0.35)
                font.family: root.fontFamily
                font.pixelSize: 12
                onAccepted: root.submitToken(tokenInput, tokenHint)
              }

              Text {
                visible: tokenInput.text === ""
                textFormat: Text.PlainText
                x: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "github_pat_..."
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: 12
              }
            }

            Chip {
              label: "Save"
              available: tokenInput.text.trim() !== ""
              onClicked: root.submitToken(tokenInput, tokenHint)
            }
          }

          Text {
            id: tokenHint
            visible: text !== ""
            textFormat: Text.PlainText
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: 11
          }
        }
      }
    }

    Rectangle {
      width: parent.width
      height: 1
      color: root.rgba(root.foreground, 0.12)
    }

    Column {
      width: parent.width
      spacing: 8

      Item {
        visible: (root.showData || root.optionsOpen) && !root.exporting
        width: parent.width
        height: 28

        Chip {
          visible: root.optionsOpen
          label: "Done"
          onClicked: root.optionsOpen = false
        }

        Row {
          visible: root.showData
          spacing: 8

          Chip {
            label: "Export report"
            glyph: "\udb80\udfcc"
            available: !root.busy
            onClicked: root.exportReportRequested()
          }

          Chip {
            label: "Export image"
            glyph: "\udb80\udee9"
            onClicked: root.exportImageRequested()
          }
        }

        Chip {
          visible: root.showTraffic
          x: parent.width - width
          label: "Include private"
          glyph: "\uf456"
          selected: root.exportPrivate
          onClicked: root.exportPrivateRequested(!root.exportPrivate)
        }

      }

      Text {
        visible: !root.optionsOpen
        textFormat: Text.PlainText
        width: parent.width
        text: root.exporting && root.hasData ? root.model.user + ", exported " + root.model.updated
            : root.hasData && root.isLight ? "Refresh uses " + root.model.requests + " API requests, no token"
            : root.hasData ? "Refresh uses " + root.model.requests + " API requests"
            : "Nothing runs in the background. You refresh with a click."
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: 10
        elide: Text.ElideRight
      }
    }
  }

  Item {
    id: tip
    visible: root.showTraffic && root.trafficModel !== null && root.hoverRow >= 0 && root.hoverDay >= 0 && !root.exporting && root.hoverRow < Math.min(root.shownCount, root.trafficModel.repos.length)
    readonly property var r: visible && root.trafficModel ? root.trafficModel.repos[root.hoverRow] : null
    readonly property real anchorX: root.pad + root.dayX(Math.max(0, root.hoverDay)) + root.cell / 2
    readonly property real rowY: root.pad + matrix.y + 18 + Math.max(0, root.hoverRow) * 22
    width: tipCol.implicitWidth + 16
    height: tipCol.implicitHeight + 12
    x: Math.round(Math.max(0, Math.min(root.width - width, anchorX - width / 2)))
    y: Math.round(rowY - height - 4)
    z: 10

    Rectangle {
      anchors.fill: parent
      radius: root.cornerRadius
      color: root.rgba(root.tooltipBackground, 0.97)
      border.width: 1
      border.color: root.tooltipBorder
    }

    Column {
      id: tipCol
      x: 8
      y: 6
      spacing: 2

      Text {
        textFormat: Text.PlainText
        text: tip.r && root.trafficModel ? tip.r.name + "   " + root.trafficModel.dayLabels[root.hoverDay] : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: 10
        font.bold: true
      }

      Text {
        textFormat: Text.PlainText
        text: tip.r ? Model.fmt(tip.r.daily[root.hoverDay]) + " views, " + Model.fmt(tip.r.dailyUniques[root.hoverDay]) + " unique" : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 11
      }

      Text {
        textFormat: Text.PlainText
        text: tip.r ? Model.fmt(tip.r.dailyClones[root.hoverDay]) + " clones" : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: 11
      }
    }
  }
}
