import { useEffect, useState } from "react";
import { api } from "./api";

export default function LoginPage({ onLoggedIn, initialStep = "credentials", initialMessage = "" }) {
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [step, setStep] = useState(initialStep);
  const [error, setError] = useState("");
  const [info, setInfo] = useState(initialMessage);
  const [busy, setBusy] = useState(false);
  const [hashFromEnv, setHashFromEnv] = useState(false);

  useEffect(() => {
    api.envDefaults().then((d) => {
      if (d.api_id) setApiId(String(d.api_id));
      if (d.phone) setPhone(d.phone);
      setHashFromEnv(Boolean(d.api_hash_configured));
    }).catch(() => {});
  }, []);

  const sendCode = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
    setBusy(true);
    try {
      const body = {
        api_id: parseInt(apiId, 10),
        phone,
      };
      if (apiHash.trim()) body.api_hash = apiHash.trim();
      const res = await api.authStart(body);
      if (res.status === "connected") {
        onLoggedIn();
      } else {
        setStep("code");
        setInfo(res.message || "Check Telegram for your login code.");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const res = await api.authCode(code);
      if (res.status === "password_required") {
        setStep("password");
        setInfo(
          res.message ||
            "Login code accepted. Enter your Telegram Two-Step Verification (cloud) password."
        );
        setCode("");
      } else {
        onLoggedIn();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const submitPassword = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api.authPassword(password);
      onLoggedIn();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>Login to Telegram</h2>
      <p className="subtitle" style={{ marginBottom: "1rem" }}>
        Get <code>api_id</code> and <code>api_hash</code> from{" "}
        <a href="https://my.telegram.org/apps" target="_blank" rel="noreferrer">
          my.telegram.org
        </a>
      </p>
      {error && <div className="error-box">{error}</div>}
      {info && !error && <p className="subtitle">{info}</p>}

      {step === "credentials" && (
        <form onSubmit={sendCode}>
          <label>API ID</label>
          <input value={apiId} onChange={(e) => setApiId(e.target.value)} required />
          <label>API Hash</label>
          <input
            value={apiHash}
            onChange={(e) => setApiHash(e.target.value)}
            required={!hashFromEnv}
            type="password"
            autoComplete="off"
            placeholder={hashFromEnv ? "Loaded from .env (optional to override)" : ""}
          />
          {hashFromEnv && (
            <p className="subtitle" style={{ marginTop: "-0.5rem" }}>
              API hash is read from your local <code>.env</code> file (not sent to the browser).
            </p>
          )}
          <label>Phone (international, e.g. +1234567890)</label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} required />
          <button type="submit" disabled={busy}>
            {busy ? "Sending…" : "Send login code"}
          </button>
        </form>
      )}

      {step === "code" && (
        <form onSubmit={submitCode}>
          <label>Code from Telegram</label>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Open Telegram → chat from <strong>Telegram</strong> → numeric <strong>Login code</strong>
            (not 2FA). Each code works once.
          </p>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\s/g, ""))}
            required
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="12345"
          />
          <div className="row">
            <button type="submit" disabled={busy}>
              {busy ? "Verifying…" : "Submit code"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={async () => {
                setCode("");
                setError("");
                setInfo("");
                setBusy(true);
                try {
                  const res = await api.authResend();
                  setInfo(res.message || "New code sent.");
                } catch (err) {
                  setError(err.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Resend code
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={async () => {
                setError("");
                setInfo("");
                setBusy(true);
                try {
                  await api.authReset();
                  setStep("credentials");
                  setCode("");
                  setInfo("Login cleared. Wait a few minutes, then send a new code.");
                } catch (err) {
                  setError(err.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Reset login
            </button>
            <button type="button" className="secondary" onClick={() => setStep("credentials")}>
              Back
            </button>
          </div>
        </form>
      )}

      {step === "password" && (
        <form onSubmit={submitPassword}>
          <h3 style={{ marginTop: 0 }}>Two-Step Verification required</h3>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Telegram confirmed your <strong>login code</strong>. This account also has a{" "}
            <strong>cloud password</strong> (2FA). Enter that password here to finish login.
          </p>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Find it in Telegram: <strong>Settings → Privacy and Security → Two-Step Verification</strong>.
            It is <em>not</em> the 5-digit login code.
          </p>
          <label>Telegram cloud password (2FA)</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            placeholder="Your Two-Step Verification password"
          />
          <div className="row">
            <button type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Complete login"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setStep("code");
                setPassword("");
                setError("");
              }}
            >
              Back to code
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
