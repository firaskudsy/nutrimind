import { motion } from "framer-motion";
import { Clock, ImagePlus, SendHorizontal, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

const SUGGESTIONS = [
  "About to eat 3 eggs and 2 toast at 8am — good?",
  "How many calories have I logged today?",
  "My weight is 82.5 kg",
  "How did I sleep this week?",
];

const COMMANDS = [
  { cmd: "/plan", label: "Plan" },
  { cmd: "/analyze", label: "Analyze" },
  { cmd: "/macros", label: "Macros" },
  { cmd: "/trends", label: "Trends" },
  { cmd: "/review", label: "Review" },
  { cmd: "/usage", label: "Usage" },
];

function readImage(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const b64 = String(r.result).split(",")[1];
      resolve({ b64, mediaType: file.type || "image/jpeg", url: r.result });
    };
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

function Bubble({ role, content, image, elapsed }) {
  const user = role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className={`flex flex-col ${user ? "items-end" : "items-start"}`}
    >
      <div
        className={`max-w-[78%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          user
            ? "rounded-br-md bg-accent text-bg"
            : "rounded-bl-md border bg-surface text-ink"
        }`}
      >
        {image && <img src={image} alt="" className="mb-2 rounded-xl" />}
        {content}
      </div>
      {elapsed != null && (
        <span className="mt-1 flex items-center gap-1 px-1 text-[10px] text-muted">
          <Clock size={10} /> {elapsed.toFixed(1)}s
        </span>
      )}
    </motion.div>
  );
}

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [image, setImage] = useState(null);
  const [busy, setBusy] = useState(false);
  const scroller = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    api.history().then((r) => setMessages(r.messages || [])).catch(() => {});
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if ((!msg && !image) || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: msg || "(photo)" }]);
    const img = image;
    setImage(null);
    try {
      const { reply, image_b64, elapsed_seconds } = await api.chat(msg, img);
      const replyImage = image_b64 ? `data:image/png;base64,${image_b64}` : null;
      setMessages((m) => [
        ...m,
        { role: "assistant", content: reply, image: replyImage, elapsed: elapsed_seconds },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠ ${e.message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (file) setImage(await readImage(file));
    e.target.value = "";
  };

  return (
    <div className="flex h-[calc(100vh-2.5rem)] flex-col pt-1 md:h-[calc(100vh-2.5rem)]">
      <header className="mb-3 flex items-center gap-2">
        <Sparkles size={18} className="text-accent" />
        <h1 className="font-display text-2xl tracking-tight">Chat</h1>
      </header>

      <div ref={scroller} className="card flex-1 space-y-3 overflow-y-auto p-4 md:p-6">
        {messages.length === 0 && (
          <div className="grid h-full place-content-center gap-4 text-center">
            <p className="font-display text-xl text-muted">What are you eating?</p>
            <div className="mx-auto flex max-w-md flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => send(s)} className="chip hover:border-accent hover:text-ink">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <Bubble key={i} role={m.role} content={m.content} image={m.image} elapsed={m.elapsed} />
        ))}
        {busy && (
          <div className="flex justify-start">
            <div className="flex gap-1 rounded-2xl rounded-bl-md border bg-surface px-4 py-3">
              {[0, 1, 2].map((d) => (
                <motion.span
                  key={d}
                  className="h-1.5 w-1.5 rounded-full bg-muted"
                  animate={{ opacity: [0.3, 1, 0.3] }}
                  transition={{ duration: 1, repeat: Infinity, delay: d * 0.2 }}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {image && (
        <div className="mt-3 flex items-center gap-2">
          <div className="relative">
            <img src={image.url} alt="attachment" className="h-16 w-16 rounded-xl border object-cover" />
            <button
              onClick={() => setImage(null)}
              className="absolute -right-2 -top-2 grid h-6 w-6 place-items-center rounded-full bg-surface shadow-soft"
            >
              <X size={12} />
            </button>
          </div>
          <span className="text-xs text-muted">Photo attached</span>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-1.5">
        {COMMANDS.map(({ cmd, label }) => (
          <button
            key={cmd}
            onClick={() => send(cmd)}
            disabled={busy}
            className="chip hover:border-accent hover:text-ink"
          >
            {label}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="mt-2 flex items-end gap-2"
      >
        <input ref={fileRef} type="file" accept="image/*" hidden onChange={onFile} />
        <button type="button" onClick={() => fileRef.current?.click()} className="btn-ghost h-11 w-11 p-0" aria-label="Attach photo">
          <ImagePlus size={18} />
        </button>
        <textarea
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Tell me what you're eating…"
          className="field max-h-32 flex-1 resize-none py-3"
        />
        <button type="submit" disabled={busy} className="btn-primary h-11 w-11 p-0" aria-label="Send">
          <SendHorizontal size={18} />
        </button>
      </form>
    </div>
  );
}
