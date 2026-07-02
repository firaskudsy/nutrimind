import { motion } from "framer-motion";
import { Check, Cpu, KeyRound, Moon, Save, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { useTheme } from "../lib/theme.jsx";

const GROUP_META = {
  LLM: { icon: Cpu, blurb: "Choose the model and set the provider key. Applies immediately." },
  Cronometer: { icon: KeyRound, blurb: "Used by the Cronometer service. Restart to apply." },
  Telegram: { icon: KeyRound, blurb: "Used by the Telegram bot. Restart to apply." },
};

function Badge({ live }) {
  return (
    <span
      className="chip"
      style={live ? { color: "rgb(var(--accent))", borderColor: "rgb(var(--accent) / 0.4)" } : { color: "rgb(var(--amber))", borderColor: "rgb(var(--amber) / 0.4)" }}
    >
      {live ? "applies now" : "restart required"}
    </span>
  );
}

function ThemeCard() {
  const { theme, toggle } = useTheme();
  return (
    <div className="card p-5">
      <h3 className="font-display text-lg tracking-tight">Appearance</h3>
      <p className="mb-4 text-xs text-muted">Choose your theme.</p>
      <div className="grid grid-cols-2 gap-2">
        {[
          { id: "light", label: "Light", icon: Sun },
          { id: "dark", label: "Dark", icon: Moon },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => theme !== id && toggle()}
            className={`btn h-11 border ${theme === id ? "border-accent bg-accent/10 text-ink" : "text-muted hover:bg-raised"}`}
          >
            <Icon size={16} /> {label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Settings() {
  const [settings, setSettings] = useState([]);
  const [models, setModels] = useState([]);
  const [form, setForm] = useState({});
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = (data) => {
    setSettings(data.settings);
    setModels(data.models);
    setForm(Object.fromEntries(data.settings.map((s) => [s.key, s.value])));
  };

  useEffect(() => {
    api.getSettings().then(load).catch(() => {});
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const res = await api.putSettings(form);
      load({ settings: res.settings, models });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setBusy(false);
    }
  };

  const groups = ["LLM", "Cronometer", "Telegram"];
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  return (
    <div className="pb-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-display text-3xl tracking-tight">Settings</h1>
          <p className="text-sm text-muted">Integrations, model, and appearance.</p>
        </div>
        <button onClick={save} disabled={busy} className="btn-primary">
          {saved ? <Check size={16} /> : <Save size={16} />}
          {saved ? "Saved" : busy ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {groups.map((group, gi) => {
            const items = settings.filter((s) => s.group === group);
            if (!items.length) return null;
            const Meta = GROUP_META[group];
            return (
              <motion.div
                key={group}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: gi * 0.06, duration: 0.4 }}
                className="card p-5"
              >
                <div className="mb-4 flex items-center gap-2.5">
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/10 text-accent">
                    <Meta.icon size={16} />
                  </span>
                  <div>
                    <h3 className="font-display text-lg leading-tight tracking-tight">{group}</h3>
                    <p className="text-xs text-muted">{Meta.blurb}</p>
                  </div>
                </div>
                <div className="space-y-4">
                  {items.map((s) => (
                    <div key={s.key}>
                      <div className="mb-1.5 flex items-center justify-between">
                        <label className="label">{s.label}</label>
                        <Badge live={s.live} />
                      </div>
                      {s.key === "agent_model" ? (
                        <select className="field" value={form[s.key] ?? ""} onChange={(e) => set(s.key, e.target.value)}>
                          {!models.some((m) => m.value === form[s.key]) && form[s.key] && (
                            <option value={form[s.key]}>{form[s.key]}</option>
                          )}
                          {models.map((m) => (
                            <option key={m.value} value={m.value}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={s.secret ? "password" : "text"}
                          className="field"
                          value={form[s.key] ?? ""}
                          onChange={(e) => set(s.key, e.target.value)}
                          placeholder={s.configured ? "" : "not set"}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </motion.div>
            );
          })}
        </div>

        <div className="space-y-4">
          <ThemeCard />
          <div className="card p-5 text-sm text-muted">
            <p className="mb-2 font-semibold text-ink">Good to know</p>
            <ul className="list-disc space-y-1.5 pl-4">
              <li>Secrets are masked; leave a field as dots to keep it unchanged.</li>
              <li>Clear a field to fall back to the value from <code className="text-ink">.env</code>.</li>
              <li>Model &amp; provider key changes take effect on your next message.</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
