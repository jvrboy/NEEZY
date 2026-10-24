"use client";

import { useEffect, useRef, useState } from "react";

export default function CommandPalette({ onNavigate, onRefresh, paused, onPause }) {
  const dialog = useRef(null);
  const [query, setQuery] = useState("");
  const actions = [
    ["Overview", () => onNavigate("overview")],
    ["Research library", () => onNavigate("library")],
    ["Executor diagnostics", () => onNavigate("diagnostics")],
    ["Workspace settings", () => onNavigate("settings")],
    [paused ? "Resume updates" : "Pause updates", onPause],
    ...(!paused ? [["Refresh snapshot", onRefresh]] : []),
  ];
  useEffect(() => {
    function keys(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuery("");
        if (dialog.current?.open) dialog.current.close(); else dialog.current?.showModal();
      }
      if (event.altKey && ["1", "2", "3", "4"].includes(event.key)) {
        event.preventDefault();
        onNavigate(["overview", "library", "diagnostics", "settings"][Number(event.key) - 1]);
      }
    }
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, [onNavigate]);
  const filtered = actions.filter(([label]) => label.toLowerCase().includes(query.toLowerCase()));
  return <>
    <button type="button" className="command-launch" onClick={() => { setQuery(""); dialog.current?.showModal(); }}>Commands <kbd>Ctrl K</kbd></button>
    <dialog ref={dialog} className="command-dialog" aria-labelledby="command-heading">
      <div className="panel-heading"><h2 id="command-heading">Workspace commands</h2><button type="button" onClick={() => dialog.current.close()} aria-label="Close command palette">Esc</button></div>
      <label className="field">Find a command<input autoFocus type="search" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && filtered.length) { filtered[0][1](); dialog.current.close(); } }} /></label>
      <div className="command-results">{filtered.map(([label, action]) => <button type="button" key={label} onClick={() => { action(); dialog.current.close(); }}>{label}<span aria-hidden="true">↗</span></button>)}</div>
      {!filtered.length && <p className="empty">No matching commands.</p>}
      <p className="muted">Alt+1–4 switches workspace sections. All commands here are read-only.</p>
    </dialog>
  </>;
}
