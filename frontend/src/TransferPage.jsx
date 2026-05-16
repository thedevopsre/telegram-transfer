import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import SessionBar from "./SessionBar";

function ConfirmModal({ open, title, body, onConfirm, onCancel }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h2>{title}</h2>
        <p>{body}</p>
        <div className="row">
          <button onClick={onConfirm}>Continue</button>
          <button className="secondary" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TransferPage({ user, onLogout, onCleanSession }) {
  const [dialogs, setDialogs] = useState([]);
  const [targetId, setTargetId] = useState("");
  const [messages, setMessages] = useState([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [filters, setFilters] = useState({
    date_from: "",
    date_to: "",
    search: "",
    media_only: false,
    text_only: false,
    forwarded_only: false,
  });
  const [copyMode, setCopyMode] = useState(false);
  const [silent, setSilent] = useState(true);
  const [job, setJob] = useState(null);
  const [jobErrors, setJobErrors] = useState([]);
  const [dryResult, setDryResult] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null);
  const [cleanConfirmOpen, setCleanConfirmOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogsLoading, setDialogsLoading] = useState(true);
  const limit = 50;

  const filterParams = useMemo(() => {
    const p = { page: String(page), limit: String(limit) };
    if (filters.date_from) p.date_from = filters.date_from;
    if (filters.date_to) p.date_to = filters.date_to;
    if (filters.search) p.search = filters.search;
    if (filters.media_only) p.media_only = "true";
    if (filters.text_only) p.text_only = "true";
    if (filters.forwarded_only) p.forwarded_only = "true";
    return p;
  }, [filters, page]);

  const loadDialogs = useCallback(async () => {
    setDialogsLoading(true);
    try {
      const res = await api.dialogs();
      const targets = res.dialogs.filter(
        (d) => !d.is_saved_messages && (d.is_channel || d.is_group)
      );
      setDialogs(targets);
      if (targets.length === 0) {
        setError(
          "No channels or groups found. Open your channel in Telegram once, then click Refresh list."
        );
      }
    } finally {
      setDialogsLoading(false);
    }
  }, []);

  const loadMessages = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const res = await api.messages(filterParams);
      setMessages(res.messages);
      setHasMore(res.has_more);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [filterParams]);

  useEffect(() => {
    loadDialogs().catch((e) => setError(e.message));
  }, [loadDialogs]);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  useEffect(() => {
    if (!job?.job_id) return;
    const interval = setInterval(async () => {
      try {
        const j = await api.getJob(job.job_id);
        setJob(j);
        if (["completed", "cancelled", "failed"].includes(j.status)) {
          const errs = await api.jobErrors(j.job_id);
          setJobErrors(errs.errors);
          clearInterval(interval);
        }
      } catch {
        clearInterval(interval);
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [job?.job_id]);

  const targetDialog = dialogs.find((d) => String(d.id) === targetId);

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllFiltered = async () => {
    setBusy(true);
    try {
      const params = { ...filterParams };
      delete params.page;
      delete params.limit;
      const res = await api.messageIds(params);
      setSelected(new Set(res.ids));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const selectedIds = useMemo(() => [...selected].sort((a, b) => a - b), [selected]);

  const runDryRun = async () => {
    if (!targetId || !selectedIds.length) {
      setError("Select a target channel and at least one message.");
      return;
    }
    setBusy(true);
    setDryResult(null);
    try {
      const res = await api.dryRun({
        target_chat_id: parseInt(targetId, 10),
        message_ids: selectedIds,
      });
      setDryResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const startTransfer = () => {
    if (!targetId || !selectedIds.length) {
      setError("Select a target channel and at least one message.");
      return;
    }
    setConfirmAction("transfer");
    setConfirmOpen(true);
  };

  const doTransfer = async () => {
    setConfirmOpen(false);
    setBusy(true);
    setError("");
    try {
      const res = await api.startJob({
        target_chat_id: parseInt(targetId, 10),
        message_ids: selectedIds,
        copy_instead_of_forward: copyMode,
        silent,
        batch_size: 50,
        batch_delay_seconds: 2,
      });
      const detail = await api.getJob(res.job_id);
      setJob(detail);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const progressPct =
    job && job.total > 0
      ? Math.round(((job.transferred + job.skipped + job.failed) / job.total) * 100)
      : 0;

  const jobFinished =
    job && ["completed", "cancelled", "failed"].includes(job.status);

  return (
    <>
      <SessionBar
        onLogout={onLogout}
        onCleanSession={() => setCleanConfirmOpen(true)}
      />
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>
            Logged in as{" "}
            {user.first_name?.trim() ||
              user.username ||
              user.phone ||
              (user.user_id ? `User ${user.user_id}` : "Telegram account")}
          </h2>
          <div className="row" style={{ marginBottom: 0 }}>
            {onLogout && (
              <button type="button" className="secondary" onClick={onLogout}>
                Log out
              </button>
            )}
            {onCleanSession && (
              <button type="button" className="danger" onClick={() => setCleanConfirmOpen(true)}>
                Clean session
              </button>
            )}
          </div>
        </div>
        <p className="subtitle" style={{ marginBottom: 0, marginTop: "0.75rem" }}>
          <strong>Log out</strong> — ends this app session. <strong>Clean session</strong> — also
          removes transfer history and logs from this Mac.
        </p>
      </div>

      <div className="card">
        <h2>Target channel</h2>
        <label>Select channel or group to post into</label>
        {dialogsLoading && (
          <p className="subtitle">Loading channels… (first load can take a few seconds)</p>
        )}
        <div className="row">
          <select
            style={{ flex: 1, minWidth: 240 }}
            value={targetId}
            onChange={(e) => setTargetId(e.target.value)}
            disabled={dialogsLoading}
          >
            <option value="">
              {dialogsLoading ? "Loading channels…" : "— choose channel —"}
            </option>
            {dialogs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}
                {d.username ? ` @${d.username}` : ""}
                {d.can_post ? "" : " (check post access)"} · id {d.id}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="secondary"
            onClick={() => loadDialogs().catch((e) => setError(e.message))}
          >
            Refresh list
          </button>
        </div>
        {targetDialog && (
          <p className="subtitle">
            Target: <strong>{targetDialog.title}</strong> · id {targetDialog.id}
          </p>
        )}
      </div>

      <div className="card">
        <h2>Saved Messages</h2>
        <div className="filters">
          <div>
            <label>Date from</label>
            <input
              type="datetime-local"
              value={filters.date_from}
              onChange={(e) =>
                setFilters((f) => ({ ...f, date_from: e.target.value }))
              }
            />
          </div>
          <div>
            <label>Date to</label>
            <input
              type="datetime-local"
              value={filters.date_to}
              onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
            />
          </div>
          <div>
            <label>Search</label>
            <input
              value={filters.search}
              onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
            />
          </div>
        </div>
        <div className="row">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={filters.media_only}
              onChange={(e) =>
                setFilters((f) => ({ ...f, media_only: e.target.checked }))
              }
            />
            Media only
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={filters.text_only}
              onChange={(e) =>
                setFilters((f) => ({ ...f, text_only: e.target.checked }))
              }
            />
            Text only
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={filters.forwarded_only}
              onChange={(e) =>
                setFilters((f) => ({ ...f, forwarded_only: e.target.checked }))
              }
            />
            Forwarded only
          </label>
        </div>
        <div className="row">
          <button type="button" onClick={() => { setPage(1); loadMessages(); }}>
            Apply filters
          </button>
          <button type="button" className="secondary" onClick={selectAllFiltered} disabled={busy}>
            Select all matching filter
          </button>
          <span className="subtitle">{selected.size} selected</span>
        </div>

        {error && <div className="error-box">{error}</div>}

        <table className="msg-table">
          <thead>
            <tr>
              <th></th>
              <th>ID</th>
              <th>Date</th>
              <th>Preview</th>
              <th>Media</th>
              <th>Fwd</th>
            </tr>
          </thead>
          <tbody>
            {messages.map((m) => (
              <tr key={m.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(m.id)}
                    onChange={() => toggleSelect(m.id)}
                  />
                </td>
                <td>{m.id}</td>
                <td>{new Date(m.date).toLocaleString()}</td>
                <td className="snippet" title={m.text_snippet}>
                  {m.text_snippet}
                </td>
                <td>
                  {m.media_type && <span className="badge">{m.media_type}</span>}
                  {m.is_album && <span className="badge">album</span>}
                </td>
                <td>{m.is_forwarded ? m.forward_from || "yes" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row">
          <button
            type="button"
            className="secondary"
            disabled={page <= 1 || busy}
            onClick={() => setPage((p) => p - 1)}
          >
            Previous
          </button>
          <span>Page {page}</span>
          <button
            type="button"
            className="secondary"
            disabled={!hasMore || busy}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Transfer</h2>
        <label className="checkbox-label">
          <input type="checkbox" checked={silent} onChange={(e) => setSilent(e.target.checked)} />
          Silent forward (no notification)
        </label>
        <label className="checkbox-label">
          <input type="checkbox" checked={copyMode} onChange={(e) => setCopyMode(e.target.checked)} />
          Copy instead of forward (drop author attribution)
        </label>
        <div className="row">
          <button type="button" className="secondary" onClick={runDryRun} disabled={busy}>
            Dry run
          </button>
          <button type="button" onClick={startTransfer} disabled={busy}>
            Start transfer
          </button>
        </div>
        {dryResult && (
          <div className="stats" style={{ marginTop: "0.75rem" }}>
            <span>
              Dry run: would transfer <strong>{dryResult.would_transfer}</strong> to{" "}
              {dryResult.target_title}
            </span>
            {dryResult.invalid_ids?.length > 0 && (
              <span className="subtitle">
                {dryResult.invalid_ids.length} invalid ID(s)
              </span>
            )}
            {dryResult.warnings?.map((w, i) => (
              <span key={i} className="subtitle">
                {w}
              </span>
            ))}
          </div>
        )}
        {job && (
          <>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${progressPct}%` }} />
            </div>
            <div className="stats">
              <span>
                Status: <strong>{job.status}</strong>
              </span>
              <span>
                Transferred: <strong>{job.transferred}</strong> / {job.total}
              </span>
              <span>Pending: {job.pending}</span>
              <span>Skipped: {job.skipped}</span>
              <span>Failed: {job.failed}</span>
            </div>
            <div className="row">
              {job.status === "running" && (
                <button type="button" className="secondary" onClick={() => api.pauseJob(job.job_id).then(setJob)}>
                  Pause
                </button>
              )}
              {job.status === "paused" && (
                <button type="button" onClick={() => api.resumeJob(job.job_id).then(() => api.getJob(job.job_id).then(setJob))}>
                  Resume
                </button>
              )}
              {["running", "paused", "pending"].includes(job.status) && (
                <button type="button" className="danger" onClick={() => api.cancelJob(job.job_id).then(setJob)}>
                  Cancel
                </button>
              )}
            </div>
            {job.error_message && <div className="error-box">{job.error_message}</div>}
          </>
        )}
        {jobFinished && (
          <div className="card" style={{ marginTop: "1rem", borderColor: "var(--accent)" }}>
            <h3 style={{ marginTop: 0 }}>Transfer finished</h3>
            <p className="subtitle" style={{ marginTop: 0 }}>
              {job.status === "completed"
                ? "All batches are done. Log out or clean the local session when you are finished."
                : `Job ${job.status}. You may start another transfer or end your session.`}
            </p>
            <div className="row">
              {onLogout && (
                <button type="button" className="secondary" onClick={onLogout}>
                  Log out
                </button>
              )}
              {onCleanSession && (
                <button type="button" className="danger" onClick={() => setCleanConfirmOpen(true)}>
                  Clean session & log out
                </button>
              )}
            </div>
          </div>
        )}
        {jobErrors.length > 0 && (
          <div style={{ marginTop: "1rem" }}>
            <h3>Errors / skipped</h3>
            <table className="msg-table">
              <thead>
                <tr>
                  <th>Message ID</th>
                  <th>Status</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {jobErrors.map((e) => (
                  <tr key={e.source_message_id}>
                    <td>{e.source_message_id}</td>
                    <td>{e.status}</td>
                    <td>{e.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmModal
        open={confirmOpen}
        title="Confirm transfer"
        body={
          confirmAction === "transfer"
            ? `You are about to forward ${selectedIds.length} message(s) from Saved Messages to ${targetDialog?.title || "the selected channel"}. Nothing will be deleted from Saved Messages. Continue?`
            : ""
        }
        onConfirm={doTransfer}
        onCancel={() => setConfirmOpen(false)}
      />
      <ConfirmModal
        open={cleanConfirmOpen}
        title="Clean session?"
        body="This logs out of Telegram in this app, deletes the local session file, and erases transfer history and logs on your Mac. Your Telegram account and chats are not affected."
        onConfirm={() => {
          setCleanConfirmOpen(false);
          onCleanSession?.();
        }}
        onCancel={() => setCleanConfirmOpen(false)}
      />
    </>
  );
}
