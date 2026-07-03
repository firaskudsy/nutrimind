import { motion } from "framer-motion";
import { CheckCircle2, ClipboardList, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

const fade = {
  hidden: { opacity: 0, y: 8 },
  show: (i) => ({ opacity: 1, y: 0, transition: { delay: i * 0.02, duration: 0.3 } }),
};

const TOOL_LABELS = {
  log_weight: "Log weight",
  add_food_entry: "Add food entry",
  remove_food_entry: "Remove food entry",
  unverified_claim: "Claimed a change without making one",
};

const SOURCE_LABELS = {
  web: "Web chat",
  chat: "Chat",
  proactive: "Proactive check-in",
  plan: "/plan",
  analyze: "/analyze",
  review: "Weekly review",
};

function argSummary(toolName, args) {
  if (toolName === "log_weight") {
    return [args.value != null ? `${args.value} ${args.unit || "lbs"}` : null, args.date]
      .filter(Boolean)
      .join(" · ");
  }
  if (toolName === "add_food_entry") {
    return [
      args.grams != null ? `${args.grams} g` : null,
      args.diary_group,
      args.date,
      args.time,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  if (toolName === "remove_food_entry") {
    return [
      Array.isArray(args.entry_ids) ? `${args.entry_ids.length} entry(s)` : null,
      args.date,
    ]
      .filter(Boolean)
      .join(" · ");
  }
  return Object.entries(args)
    .map(([k, v]) => `${k}=${v}`)
    .join(" · ");
}

function ActionRow({ action, i }) {
  const ok = action.success;
  return (
    <motion.div
      custom={i}
      variants={fade}
      initial="hidden"
      animate="show"
      className="card flex items-start gap-3 p-3.5"
    >
      {ok ? (
        <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-500" />
      ) : (
        <XCircle size={18} className="mt-0.5 shrink-0 text-rose-500" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">
            {TOOL_LABELS[action.tool_name] || action.tool_name}
          </span>
          <span className="chip">{SOURCE_LABELS[action.source] || action.source}</span>
          <span className="text-xs text-muted">
            {new Date(action.created_at).toLocaleString()}
          </span>
        </div>
        <div className="mt-1 truncate text-sm text-muted">
          {argSummary(action.tool_name, action.arguments)}
        </div>
        {!ok && (
          <div className="mt-1.5 rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-xs text-rose-500">
            {action.detail}
          </div>
        )}
      </div>
    </motion.div>
  );
}

export default function Activity() {
  const [actions, setActions] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getActions()
      .then((r) => setActions(r.actions))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="pb-10">
      <header className="mb-6 flex items-center gap-2.5">
        <ClipboardList size={20} className="text-accent" />
        <div>
          <h1 className="font-display text-3xl tracking-tight">Activity Log</h1>
          <p className="text-sm text-muted">
            Every Cronometer write the assistant attempted — verified against Cronometer itself,
            independent of what it said in chat.
          </p>
        </div>
      </header>

      {error && <div className="card mb-4 p-4 text-sm text-amber">Couldn't load: {error}</div>}

      {actions === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : actions.length === 0 ? (
        <div className="card p-8 text-center text-sm text-muted">
          No actions logged yet — this fills in as the assistant logs weight or food for you.
        </div>
      ) : (
        <div className="space-y-2.5">
          {actions.map((action, i) => (
            <ActionRow key={action.id} action={action} i={i} />
          ))}
        </div>
      )}
    </div>
  );
}
