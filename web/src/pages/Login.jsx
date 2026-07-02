import { motion } from "framer-motion";
import { ArrowRight, Leaf, Lock } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, setToken } from "../lib/api.js";

export default function Login({ onAuthed }) {
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const btnRef = useRef(null);

  useEffect(() => {
    api.config().then(setCfg).catch(() => setCfg({ google_enabled: false, password_login: true }));
  }, []);

  // Render the Google button once GSI + config are ready.
  useEffect(() => {
    if (!cfg?.google_enabled || !btnRef.current) return;
    let tries = 0;
    const timer = setInterval(() => {
      if (!window.google?.accounts?.id) {
        if (++tries > 40) clearInterval(timer);
        return;
      }
      clearInterval(timer);
      window.google.accounts.id.initialize({
        client_id: cfg.google_client_id,
        callback: async ({ credential }) => {
          setBusy(true);
          setError("");
          try {
            const { token, user } = await api.googleLogin(credential);
            setToken(token);
            onAuthed(user);
          } catch {
            setError("Google sign-in failed.");
          } finally {
            setBusy(false);
          }
        },
      });
      window.google.accounts.id.renderButton(btnRef.current, {
        theme: document.documentElement.classList.contains("dark") ? "filled_black" : "outline",
        size: "large",
        shape: "pill",
        width: 280,
        text: "continue_with",
      });
    }, 100);
    return () => clearInterval(timer);
  }, [cfg, onAuthed]);

  const passwordLogin = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { token, user } = await api.login(password);
      setToken(token);
      onAuthed(user);
    } catch {
      setError("Wrong password.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="w-full max-w-sm"
      >
        <div className="mb-8 text-center">
          <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-accent text-bg shadow-glow">
            <Leaf size={24} />
          </div>
          <h1 className="font-display text-4xl tracking-tight">
            Nutri<span className="italic text-accent">Mind</span>
          </h1>
          <p className="mt-2 text-sm text-muted">Your 24/7 nutrition &amp; health assistant.</p>
        </div>

        <div className="card space-y-5 p-6">
          {cfg?.google_enabled && (
            <div className="flex justify-center">
              <div ref={btnRef} />
            </div>
          )}

          {error && <p className="text-center text-sm text-amber">{error}</p>}

          {cfg?.password_login && (
            <>
              {cfg?.google_enabled && (
                <div className="flex items-center gap-3 text-xs text-muted">
                  <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
                </div>
              )}
              {!showPw ? (
                <button onClick={() => setShowPw(true)} className="btn-ghost w-full">
                  <Lock size={15} /> Sign in as owner
                </button>
              ) : (
                <form onSubmit={passwordLogin} className="space-y-3">
                  <input
                    type="password"
                    autoFocus
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Owner password"
                    className="field"
                  />
                  <button type="submit" disabled={busy} className="btn-primary w-full">
                    {busy ? "Signing in…" : "Enter"} {!busy && <ArrowRight size={16} />}
                  </button>
                </form>
              )}
            </>
          )}
        </div>

        <p className="mt-4 text-center text-xs text-muted">
          Family members sign in with Google; the admin approves access.
        </p>
      </motion.div>
    </div>
  );
}
