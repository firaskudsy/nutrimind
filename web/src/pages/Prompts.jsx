import { motion } from "framer-motion";
import { Check, RotateCcw, Save, ScrollText } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api.js";

function PromptCard({ prompt, index, onSaved }) {
  const [value, setValue] = useState(prompt.value);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const dirty = value !== prompt.value;
  const isDefault = value === prompt.default;

  const save = async (nextValue) => {
    setBusy(true);
    try {
      const { prompts } = await api.putPrompts({ [prompt.key]: nextValue });
      const updated = prompts.find((p) => p.key === prompt.key);
      setValue(updated.value);
      onSaved(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05, duration: 0.4 }}
      className="card p-5"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-display text-lg leading-tight tracking-tight">{prompt.label}</h3>
            <span
              className="chip"
              style={
                isDefault
                  ? {}
                  : { color: "rgb(var(--accent))", borderColor: "rgb(var(--accent) / 0.4)" }
              }
            >
              {isDefault ? "default" : "customized"}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted">{prompt.description}</p>
          {prompt.placeholders.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {prompt.placeholders.map((p) => (
                <span key={p} className="chip font-mono text-[10px]">
                  {`{${p}}`}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex shrink-0 gap-1.5">
          <button
            onClick={() => save("")}
            disabled={busy || isDefault}
            className="btn-ghost h-9 w-9 p-0"
            title="Reset to default"
          >
            <RotateCcw size={15} />
          </button>
          <button
            onClick={() => save(value)}
            disabled={busy || !dirty}
            className="btn-primary h-9 px-3"
          >
            {saved ? <Check size={15} /> : <Save size={15} />}
            {saved ? "Saved" : busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={prompt.key === "system_core" ? 16 : 8}
        className="field font-mono text-xs leading-relaxed"
        spellCheck={false}
      />
    </motion.div>
  );
}

export default function Prompts() {
  const [prompts, setPrompts] = useState(null);

  useEffect(() => {
    api.getPrompts().then((r) => setPrompts(r.prompts)).catch(() => setPrompts([]));
  }, []);

  const onSaved = (updated) => {
    setPrompts((all) => all.map((p) => (p.key === updated.key ? updated : p)));
  };

  return (
    <div className="pb-10">
      <header className="mb-6 flex items-center gap-2.5">
        <ScrollText size={20} className="text-accent" />
        <div>
          <h1 className="font-display text-3xl tracking-tight">Prompts</h1>
          <p className="text-sm text-muted">
            The instructions sent to the LLM. These are global — a change applies to every
            approved member's assistant, not just yours.
          </p>
        </div>
      </header>

      {prompts === null && <p className="text-sm text-muted">Loading…</p>}
      {prompts?.length === 0 && <p className="text-sm text-muted">Couldn't load prompts.</p>}

      <div className="space-y-4">
        {prompts?.map((p, i) => (
          <PromptCard key={p.key} prompt={p} index={i} onSaved={onSaved} />
        ))}
      </div>
    </div>
  );
}
