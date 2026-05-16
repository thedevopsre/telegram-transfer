const BASE = "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    }
    throw new Error(detail || data.message || `HTTP ${res.status}`);
  }
  return data;
}

export const api = {
  appInfo: () => request("/api/app-info"),
  envDefaults: () => request("/api/env-defaults"),
  authStatus: () => request("/auth/status"),
  authStart: (body) =>
    request("/auth/start", { method: "POST", body: JSON.stringify(body) }),
  authResend: () => request("/auth/resend", { method: "POST" }),
  authReset: () => request("/auth/reset", { method: "POST" }),
  authLogout: () => request("/auth/logout", { method: "POST" }),
  authCleanSession: () => request("/auth/clean-session", { method: "POST" }),
  authCode: (code) =>
    request("/auth/code", { method: "POST", body: JSON.stringify({ code }) }),
  authPassword: (password) =>
    request("/auth/password", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  dialogs: () => request("/dialogs"),
  messages: (params) => {
    const q = new URLSearchParams({ saved: "true", ...params });
    return request(`/messages?${q}`);
  },
  messageIds: (params) => {
    const q = new URLSearchParams(params);
    return request(`/messages/ids?${q}`);
  },
  dryRun: (body) =>
    request("/jobs/dry-run", { method: "POST", body: JSON.stringify(body) }),
  startJob: (body) =>
    request("/jobs/start", { method: "POST", body: JSON.stringify(body) }),
  getJob: (id) => request(`/jobs/${id}`),
  jobErrors: (id) => request(`/jobs/${id}/errors`),
  pauseJob: (id) => request(`/jobs/${id}/pause`, { method: "POST" }),
  resumeJob: (id) => request(`/jobs/${id}/resume`, { method: "POST" }),
  cancelJob: (id) => request(`/jobs/${id}/cancel`, { method: "POST" }),
};
