import React, { useEffect, useState } from "react";

import { fetchJson } from "./api.js?v=debug-log-1";
import {
  debugEventsUrl,
  debugExportUrl,
  debugSessionId,
  recordDebugEvent,
} from "./debug_event_log.js?v=debug-log-1";

const h = React.createElement;

export function DebugLogPanel() {
  const [events, setEvents] = useState([]);
  const [logPath, setLogPath] = useState("");
  const [allSessions, setAllSessions] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    const load = () => {
      fetchJson(debugEventsUrl({ allSessions, limit: 120 }))
        .then((data) => {
          if (!active) return;
          setEvents(data.events || []);
          setLogPath(data.log_path || "");
        })
        .catch((error) => {
          if (active) setMessage(String(error));
        });
    };
    load();
    const timer = window.setInterval(load, 2_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [allSessions, reloadToken]);

  const copyEvents = async () => {
    const content = events.map((event) => JSON.stringify(event)).join("\n");
    try {
      await navigator.clipboard.writeText(content);
      setMessage(`已复制 ${events.length} 条日志`);
      recordDebugEvent("debug_log.copied", { event_count: events.length });
    } catch (error) {
      setMessage(`复制失败：${error}`);
      recordDebugEvent("debug_log.copy_failed", { error: String(error) }, "error");
    }
  };

  return h("section", { className: "section debug-log" }, [
    h("div", { key: "head", className: "debug-log__head" }, [
      h("div", { key: "title" }, [
        h("h2", { key: "heading", className: "section__title" }, "操作与生成日志"),
        h("span", { key: "session", className: "debug-log__session" },
          allSessions ? "全部会话" : `本次会话 ${debugSessionId().slice(0, 8)}`,
        ),
      ]),
      h("span", { key: "count", className: "pill" }, `${events.length} 条`),
    ]),
    h("div", { key: "actions", className: "debug-log__actions" }, [
      h("button", {
        key: "scope",
        className: "button",
        onClick: () => {
          const next = !allSessions;
          setAllSessions(next);
          recordDebugEvent("debug_log.scope_changed", { all_sessions: next });
        },
      }, allSessions ? "只看本次" : "查看全部"),
      h("button", {
        key: "refresh",
        className: "button",
        onClick: () => {
          setReloadToken((value) => value + 1);
          recordDebugEvent("debug_log.refreshed");
        },
      }, "刷新"),
      h("button", { key: "copy", className: "button", onClick: copyEvents }, "复制"),
      h("a", {
        key: "export",
        className: "button debug-log__download",
        href: debugExportUrl({ allSessions }),
        download: "station_designer_debug.jsonl",
        onClick: () => recordDebugEvent("debug_log.exported", { all_sessions: allSessions }),
      }, "导出 JSONL"),
    ]),
    message ? h("div", { key: "message", className: "debug-log__message" }, message) : null,
    h("div", { key: "events", className: "debug-log__events" },
      events.length
        ? events.slice(-40).reverse().map((event) => h(DebugEventRow, { key: event.event_id, event }))
        : h("div", { className: "empty" }, "还没有操作日志。"),
    ),
    h("div", { key: "path", className: "debug-log__path", title: logPath },
      logPath || "日志文件尚未创建",
    ),
  ]);
}

function DebugEventRow({ event }) {
  const status = event.status || "info";
  return h("div", { className: `debug-event debug-event--${status}` }, [
    h("div", { key: "meta", className: "debug-event__meta" }, [
      h("time", { key: "time" }, displayTime(event.timestamp)),
      h("span", { key: "source" }, event.source || "-")
    ]),
    h("strong", { key: "action" }, event.action || "unknown"),
    h("code", { key: "details" }, compactDetails(event.details)),
  ]);
}

function displayTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString("zh-CN", { hour12: false });
}

function compactDetails(details) {
  const text = JSON.stringify(details || {});
  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}
