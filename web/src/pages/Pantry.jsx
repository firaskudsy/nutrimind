import { motion } from "framer-motion";
import { Check, Pencil, Plus, Search, ShoppingBasket, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";

const fade = {
  hidden: { opacity: 0, y: 8 },
  show: (i) => ({ opacity: 1, y: 0, transition: { delay: i * 0.03, duration: 0.35 } }),
};

function FoodNameInput({ value, onChange, placeholder, autoFocus }) {
  const [suggestions, setSuggestions] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    const query = value.trim();
    if (query.length < 2) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const r = await api.searchFoods(query);
        setSuggestions(r.foods || []);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => clearTimeout(debounceRef.current);
  }, [value]);

  const pick = (foodName) => {
    onChange(foodName);
    setSuggestions([]);
    setOpen(false);
  };

  const showDropdown = open && value.trim().length >= 2 && (loading || suggestions.length > 0);

  return (
    <div className="relative flex-1">
      <div className="relative">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          className="field w-full pl-8"
          placeholder={placeholder}
          value={value}
          autoFocus={autoFocus}
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      </div>
      {showDropdown && (
        <div className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-xl border bg-surface shadow-soft">
          {loading ? (
            <div className="px-3.5 py-2 text-xs text-muted">Searching…</div>
          ) : (
            suggestions.map((foodName) => (
              <button
                key={foodName}
                type="button"
                onMouseDown={() => pick(foodName)}
                className="block w-full truncate px-3.5 py-2 text-left text-sm hover:bg-bg"
              >
                {foodName}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function AddItemForm({ onAdd }) {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await onAdd(name.trim(), notes.trim());
      setName("");
      setNotes("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card flex flex-col gap-2.5 p-4 sm:flex-row sm:items-center">
      <FoodNameInput
        value={name}
        onChange={setName}
        placeholder="Food item (e.g. Chicken breast) — search Cronometer's database"
      />
      <input
        className="field flex-1"
        placeholder="Notes (optional) — e.g. always frozen, buy weekly"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      <button type="submit" disabled={!name.trim() || busy} className="btn-primary h-11 shrink-0 px-4">
        <Plus size={16} /> Add
      </button>
    </form>
  );
}

function PantryRow({ item, i, onSave, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(item.name);
  const [notes, setNotes] = useState(item.notes || "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await onSave(item.id, { name: name.trim(), notes: notes.trim() });
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const cancel = () => {
    setName(item.name);
    setNotes(item.notes || "");
    setEditing(false);
  };

  return (
    <motion.div
      custom={i}
      variants={fade}
      initial="hidden"
      animate="show"
      className="card flex items-center gap-3 p-3.5"
    >
      {editing ? (
        <>
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <FoodNameInput value={name} onChange={setName} autoFocus />
            <input
              className="field flex-1"
              placeholder="Notes (optional)"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <div className="flex shrink-0 gap-1.5">
            <button onClick={save} disabled={busy} className="btn-primary h-9 w-9 p-0" title="Save">
              <Check size={15} />
            </button>
            <button onClick={cancel} className="btn-ghost h-9 w-9 p-0" title="Cancel">
              <X size={15} />
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{item.name}</div>
            {item.notes && <div className="truncate text-xs text-muted">{item.notes}</div>}
          </div>
          <div className="flex shrink-0 gap-1.5">
            <button onClick={() => setEditing(true)} className="btn-ghost h-9 w-9 p-0" title="Edit">
              <Pencil size={15} />
            </button>
            <button onClick={() => onDelete(item.id)} className="btn-ghost h-9 w-9 p-0" title="Remove">
              <Trash2 size={15} />
            </button>
          </div>
        </>
      )}
    </motion.div>
  );
}

export default function Pantry() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  const load = () => api.getPantry().then((r) => setItems(r.items)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const add = async (name, notes) => {
    await api.addPantryItem(name, notes);
    await load();
  };

  const save = async (id, values) => {
    await api.updatePantryItem(id, values);
    await load();
  };

  const remove = async (id) => {
    await api.deletePantryItem(id);
    setItems((cur) => cur.filter((i) => i.id !== id));
  };

  return (
    <div className="pb-10">
      <header className="mb-6 flex items-center gap-2.5">
        <ShoppingBasket size={20} className="text-accent" />
        <div>
          <h1 className="font-display text-3xl tracking-tight">Pantry</h1>
          <p className="text-sm text-muted">
            Foods you actually have or can buy — the assistant prefers these first when
            suggesting a meal or building a plan.
          </p>
        </div>
      </header>

      {error && <div className="card mb-4 p-4 text-sm text-amber">Couldn't load: {error}</div>}

      <div className="mb-4">
        <AddItemForm onAdd={add} />
      </div>

      {items === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : items.length === 0 ? (
        <div className="card p-8 text-center text-sm text-muted">
          Nothing here yet — add what's in your fridge or pantry above.
        </div>
      ) : (
        <div className="space-y-2.5">
          {items.map((item, i) => (
            <PantryRow key={item.id} item={item} i={i} onSave={save} onDelete={remove} />
          ))}
        </div>
      )}
    </div>
  );
}
