import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import LoginPage from "./LoginPage";
import TransferPage from "./TransferPage";

export default function App() {
  const [auth, setAuth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refreshAuth = useCallback(async () => {
    try {
      const status = await api.authStatus();
      setAuth(status);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshAuth();
    api.appInfo?.().catch(() => {});
  }, [refreshAuth]);

  const handleLogout = async () => {
    setError("");
    try {
      await api.authLogout();
    } catch (e) {
      setError(e.message);
    }
    setAuth({ status: "disconnected" });
  };

  const handleCleanSession = async () => {
    if (
      !window.confirm(
        "Clean session will:\n• Log out of Telegram on this app\n• Delete the local session file\n• Erase transfer history and logs on this Mac\n\nYour Telegram account and chats are not deleted. Continue?"
      )
    ) {
      return;
    }
    setError("");
    try {
      await api.authCleanSession();
    } catch (e) {
      setError(e.message);
    }
    setAuth({ status: "disconnected" });
  };

  if (loading) {
    return <p className="subtitle">Loading…</p>;
  }

  const connected = auth?.status === "connected";

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ marginBottom: "0.25rem" }}>Telegram Saved Messages Transfer</h1>
          <p className="subtitle" style={{ margin: 0 }}>
            Local-only · 127.0.0.1 · Session stays on your machine
          </p>
        </div>
        {connected && (
          <div className="row" style={{ marginBottom: 0 }}>
            <button type="button" className="secondary" onClick={handleLogout}>
              Log out
            </button>
            <button type="button" className="danger" onClick={handleCleanSession}>
              Clean session
            </button>
          </div>
        )}
      </div>
      {error && <div className="error-box">{error}</div>}
      {!connected ? (
        <LoginPage
          onLoggedIn={refreshAuth}
          initialStep={
            auth?.status === "password_required" ? "password" : "credentials"
          }
          initialMessage={
            auth?.status === "password_required"
              ? "Login code was accepted. Enter your Telegram Two-Step Verification password."
              : ""
          }
        />
      ) : (
        <TransferPage
          user={auth}
          onLogout={handleLogout}
          onCleanSession={handleCleanSession}
        />
      )}
    </>
  );
}
