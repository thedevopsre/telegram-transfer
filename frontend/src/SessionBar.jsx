/** Always-visible log out / clean session controls */
export default function SessionBar({ onLogout, onCleanSession }) {
  return (
    <div className="card session-bar">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: "0.5rem" }}>
        <strong>Account session</strong>
        <div className="row" style={{ marginBottom: 0 }}>
          <button type="button" className="secondary" onClick={onLogout}>
            Log out
          </button>
          <button type="button" className="danger" onClick={onCleanSession}>
            Clean session & log out
          </button>
        </div>
      </div>
      <p className="subtitle" style={{ margin: 0 }}>
        Log out keeps transfer history. Clean session also deletes local transfer DB and logs.
      </p>
    </div>
  );
}
