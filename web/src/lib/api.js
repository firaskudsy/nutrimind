// Tiny API client. Token is stored in localStorage after login and sent as a
// Bearer header. All calls are same-origin /api/* (Vite proxies to the backend
// in dev; nginx proxies in prod).

const TOKEN_KEY = "nm-token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function req(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) {
    clearToken();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  config: () => req("GET", "/config"),
  login: (password) => req("POST", "/auth/login", { password }),
  googleLogin: (credential) => req("POST", "/auth/google", { credential }),
  me: () => req("GET", "/me"),
  adminUsers: () => req("GET", "/admin/users"),
  adminSetStatus: (id, action) => req("POST", `/admin/users/${id}/${action}`),
  getSettings: () => req("GET", "/settings"),
  putSettings: (values) => req("PUT", "/settings", { values }),
  chat: (message, image) =>
    req("POST", "/chat", {
      message,
      image_b64: image?.b64 || null,
      image_media_type: image?.mediaType || "image/jpeg",
    }),
  history: () => req("GET", "/chat/history"),
  dashboard: () => req("GET", "/dashboard"),
};
