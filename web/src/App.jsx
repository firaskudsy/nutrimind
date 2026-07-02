import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Admin from "./pages/Admin.jsx";
import Chat from "./pages/Chat.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Login from "./pages/Login.jsx";
import Pending from "./pages/Pending.jsx";
import Prompts from "./pages/Prompts.jsx";
import Settings from "./pages/Settings.jsx";
import { api, clearToken, getToken } from "./lib/api.js";

export default function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!!getToken());

  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then((r) => setUser(r.user))
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  const logout = () => {
    clearToken();
    setUser(null);
  };

  if (loading) {
    return <div className="grid min-h-screen place-items-center text-muted">Loading…</div>;
  }

  if (!user) return <Login onAuthed={setUser} />;
  if (user.status !== "approved") return <Pending user={user} onLogout={logout} />;

  return (
    <Layout user={user} onLogout={logout}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/settings" element={<Settings />} />
        {user.role === "admin" && <Route path="/members" element={<Admin />} />}
        {user.role === "admin" && <Route path="/prompts" element={<Prompts />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
