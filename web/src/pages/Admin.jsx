import { motion } from "framer-motion";
import { Check, ShieldCheck, UserCog, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

const STATUS_STYLE = {
  approved: { color: "rgb(var(--accent))", border: "rgb(var(--accent) / 0.4)" },
  pending: { color: "rgb(var(--amber))", border: "rgb(var(--amber) / 0.4)" },
  rejected: { color: "rgb(var(--muted))", border: "rgb(var(--line))" },
};

function Avatar({ user }) {
  const [broken, setBroken] = useState(false);
  if (user.picture && !broken) {
    return (
      <img
        src={user.picture}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className="h-10 w-10 rounded-full object-cover"
      />
    );
  }
  const initial = (user.name || user.email || "?")[0].toUpperCase();
  return (
    <div className="grid h-10 w-10 place-items-center rounded-full bg-accent/15 font-display text-accent">
      {initial}
    </div>
  );
}

export default function Admin() {
  const [users, setUsers] = useState([]);
  const [busy, setBusy] = useState(null);

  const load = () => api.adminUsers().then((r) => setUsers(r.users)).catch(() => {});
  useEffect(() => {
    load();
  }, []);

  const act = async (id, action) => {
    setBusy(id);
    try {
      await api.adminSetStatus(id, action);
      await load();
    } finally {
      setBusy(null);
    }
  };

  const pending = users.filter((u) => u.status === "pending");

  return (
    <div className="pb-10">
      <header className="mb-6 flex items-center gap-2.5">
        <ShieldCheck size={20} className="text-accent" />
        <div>
          <h1 className="font-display text-3xl tracking-tight">Members</h1>
          <p className="text-sm text-muted">Approve family members. Strangers stay out.</p>
        </div>
      </header>

      {pending.length > 0 && (
        <div className="mb-4 flex items-center gap-2 text-sm">
          <span className="chip" style={{ color: "rgb(var(--amber))", borderColor: "rgb(var(--amber) / 0.4)" }}>
            {pending.length} awaiting approval
          </span>
        </div>
      )}

      <div className="space-y-2.5">
        {users.map((u, i) => (
          <motion.div
            key={u.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04 }}
            className="card flex items-center gap-3 p-3.5"
          >
            <Avatar user={u} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium">{u.name || u.email}</span>
                {u.role === "admin" && (
                  <span className="chip gap-1 text-accent" style={{ borderColor: "rgb(var(--accent) / 0.4)" }}>
                    <UserCog size={12} /> admin
                  </span>
                )}
              </div>
              <div className="truncate text-xs text-muted">{u.email}</div>
            </div>

            <span className="chip capitalize" style={STATUS_STYLE[u.status]}>
              {u.status}
            </span>

            {u.role !== "admin" && (
              <div className="flex gap-1.5">
                {u.status !== "approved" && (
                  <button
                    onClick={() => act(u.id, "approve")}
                    disabled={busy === u.id}
                    className="btn-primary h-9 w-9 p-0"
                    title="Approve"
                  >
                    <Check size={16} />
                  </button>
                )}
                {u.status !== "rejected" && (
                  <button
                    onClick={() => act(u.id, "reject")}
                    disabled={busy === u.id}
                    className="btn-ghost h-9 w-9 p-0"
                    title="Reject"
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </div>
  );
}
