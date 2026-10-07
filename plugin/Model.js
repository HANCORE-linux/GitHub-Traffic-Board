.pragma library

var STEPS = [1, 4, 16, 64]
var TOP_REPOS = 16
var MORE_REPOS = 36
var WARN_REQUESTS = 200
var TOP_REFERRERS = 3
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
var DAY_MS = 86400000

function pad2(n) {
  return n < 10 ? "0" + n : String(n)
}

function isoDay(d) {
  return d.getUTCFullYear() + "-" + pad2(d.getUTCMonth() + 1) + "-" + pad2(d.getUTCDate())
}

function parseDay(s) {
  var p = String(s).split("-")
  return new Date(Date.UTC(Number(p[0]), Number(p[1]) - 1, Number(p[2])))
}

function dayLabel(d) {
  return MONTHS[d.getUTCMonth()] + " " + d.getUTCDate()
}

function fmt(n) {
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

function compact(n) {
  n = Number(n) || 0
  if (n < 1000) return String(n)
  var s = n >= 100000 ? Math.round(n / 1000) + "k" : (Math.round(n / 100) / 10).toFixed(1) + "k"
  return s.replace(".0k", "k")
}

function level(x) {
  var l = 0
  for (var i = 0; i < STEPS.length; i++) if (x >= STEPS[i]) l++
  return l
}

function sum(list) {
  var t = 0
  for (var i = 0; i < list.length; i++) t += list[i]
  return t
}

function trend(series) {
  var prior = sum(series.slice(0, 7))
  var recent = sum(series.slice(7))
  if (prior === 0) return null
  return Math.round((recent - prior) * 100 / prior)
}

function updatedText(generated, now) {
  var g = new Date(generated)
  if (isNaN(g.getTime())) return ""
  var time = pad2(g.getHours()) + ":" + pad2(g.getMinutes())
  var n = now || new Date()
  var sameDay = g.getFullYear() === n.getFullYear() && g.getMonth() === n.getMonth() && g.getDate() === n.getDate()
  return sameDay ? time : MONTHS[g.getMonth()] + " " + g.getDate() + ", " + time
}

function requestsFor(count) {
  return 3 * count + Math.floor(count / 100) + 2
}

function relTime(iso, now) {
  var t = new Date(iso).getTime()
  if (!iso || isNaN(t)) return ""
  var d = Math.floor(((now || new Date()).getTime() - t) / DAY_MS)
  if (d <= 0) return "today"
  if (d === 1) return "yesterday"
  if (d < 30) return d + "d ago"
  if (d < 365) return Math.floor(d / 30) + "mo ago"
  return Math.floor(d / 365) + "y ago"
}

function nextStep(shown, total) {
  if (shown >= total) return null
  if (shown <= TOP_REPOS && total - shown > MORE_REPOS) return { count: shown + MORE_REPOS, label: "Show " + MORE_REPOS + " more" }
  return { count: total, label: "Show all " + total + " repositories" }
}

function buildLight(snapshot, now) {
  if (!snapshot || snapshot.ok !== true || snapshot.light !== true || !Array.isArray(snapshot.repos)) return null
  var repos = snapshot.repos.map(function(r) {
    return {
      name: String(r.name),
      stars: Number(r.stars) || 0,
      language: String(r.language || ""),
      pushed: String(r.pushed_at || ""),
      updated: relTime(r.pushed_at, now),
    }
  })
  repos.sort(function(a, b) {
    return (b.stars - a.stars) || (a.pushed < b.pushed ? 1 : a.pushed > b.pushed ? -1 : 0) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)
  })
  var stars = sum(repos.map(function(r) { return r.stars }))
  return {
    light: true,
    user: String(snapshot.user || ""),
    updated: updatedText(snapshot.generated, now),
    stars: stars,
    followers: Number(snapshot.followers) || 0,
    repoCount: repos.length,
    repos: repos,
    requests: Math.floor(repos.length / 100) + 2,
    barLabel: compact(stars),
    spike: false,
  }
}

function build(snapshot, now) {
  if (!snapshot || snapshot.ok !== true || snapshot.light === true || !Array.isArray(snapshot.repos)) return null
  var generated = new Date(snapshot.generated)
  if (isNaN(generated.getTime())) return null
  var today = parseDay(isoDay(generated))

  var last = null
  snapshot.repos.forEach(function(r) {
    ["views", "clones"].forEach(function(kind) {
      ((r[kind] && r[kind].daily) || []).forEach(function(e) {
        var d = parseDay(e.date)
        if (!isNaN(d.getTime()) && (last === null || d > last)) last = d
      })
    })
  })
  if (last === null || last >= today) last = new Date(today.getTime() - DAY_MS)

  var days = []
  for (var i = 0; i < 14; i++) days.push(new Date(last.getTime() - (13 - i) * DAY_MS))
  var keys = days.map(isoDay)

  function perDay(entries, field) {
    var m = {}
    ;(entries || []).forEach(function(e) { m[e.date] = Number(e[field]) || 0 })
    return keys.map(function(k) { return m[k] || 0 })
  }

  var repos = snapshot.repos.map(function(r) {
    var views = perDay(r.views && r.views.daily, "count")
    var uniques = perDay(r.views && r.views.daily, "uniques")
    var clones = perDay(r.clones && r.clones.daily, "count")
    return {
      name: String(r.name),
      private: r.private === true,
      views: sum(views),
      clones: sum(clones),
      daily: views,
      dailyUniques: uniques,
      dailyClones: clones,
      levels: views.map(level),
    }
  })
  repos.sort(function(a, b) {
    return (b.views - a.views) || (b.clones - a.clones) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)
  })

  var dailyViews = keys.map(function(_, i) { return sum(repos.map(function(r) { return r.daily[i] })) })
  var dailyClones = keys.map(function(_, i) { return sum(repos.map(function(r) { return r.dailyClones[i] })) })

  var refs = {}
  snapshot.repos.forEach(function(r) {
    ;(r.referrers || []).forEach(function(x) {
      var name = String(x.referrer)
      refs[name] = (refs[name] || 0) + (Number(x.count) || 0)
    })
  })
  var ranked = Object.keys(refs).map(function(k) { return { name: k, count: refs[k] } })
  ranked.sort(function(a, b) { return (b.count - a.count) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0) })

  var prev = dailyViews.slice(0, 13).slice().sort(function(a, b) { return a - b })
  var median = prev.length ? prev[Math.floor(prev.length / 2)] : 0
  var views = sum(dailyViews)
  var skipped = Array.isArray(snapshot.skipped) ? snapshot.skipped.length : 0

  return {
    user: String(snapshot.user || ""),
    updated: updatedText(snapshot.generated, now),
    firstDay: dayLabel(days[0]),
    lastDay: dayLabel(days[13]),
    dayLabels: days.map(dayLabel),
    views: views,
    clones: sum(dailyClones),
    viewsTrend: trend(dailyViews),
    clonesTrend: trend(dailyClones),
    dailyViews: dailyViews,
    dailyClones: dailyClones,
    maxViews: Math.max.apply(null, dailyViews.concat([1])),
    maxClones: Math.max.apply(null, dailyClones.concat([1])),
    repoCount: repos.length,
    repos: repos,
    referrers: ranked.slice(0, TOP_REFERRERS),
    referrerCount: ranked.length,
    requests: requestsFor(repos.length + skipped),
    barLabel: compact(views),
    spike: median > 0 && dailyViews[13] >= 2 * median,
  }
}

function trendText(p) {
  if (p === null || p === undefined) return "new"
  return (p >= 0 ? "▴ " : "▾ ") + Math.abs(p) + "%"
}

function errorText(code, message) {
  if (code === "rate-limited") return "GitHub rate limit reached. Showing the last data."
  if (code === "unauthorized") return "The saved token is invalid or expired."
  if (code === "network") return "GitHub is not reachable right now."
  if (code === "helper") return "The python3 helper could not run."
  if (code === "not-found") return String(message || "That GitHub user does not exist.")
  if (code === "invalid-user") return "Enter a GitHub username in Options."
  if (code === "api-error") return "GitHub returned an error. " + String(message || "")
  return String(message || "Something went wrong.")
}
