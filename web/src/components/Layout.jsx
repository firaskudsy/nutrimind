import { motion } from "framer-motion";
import {
  LayoutGrid,
  LogOut,
  MessageCircle,
  Moon,
  ScrollText,
  Settings2,
  ShieldCheck,
  Sun,
} from "lucide-react";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useTheme } from "../lib/theme.jsx";

const BASE_NAV = [
  { to: "/", label: "Dashboard", icon: LayoutGrid, end: true },
  { to: "/chat", label: "Chat", icon: MessageCircle },
  { to: "/settings", label: "Settings", icon: Settings2 },
];

function Wordmark() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-accent text-bg shadow-glow">
        <span className="font-display text-lg font-semibold leading-none">N</span>
      </div>
      <div className="leading-tight">
        <div className="font-display text-lg tracking-tight">
          Nutri<span className="italic text-accent">Mind</span>
        </div>
        <div className="text-[10px] uppercase tracking-[0.2em] text-muted">health assistant</div>
      </div>
    </div>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      onClick={toggle}
      className="btn-ghost h-10 w-full justify-start px-3"
      aria-label="Toggle theme"
    >
      <span className="grid h-6 w-6 place-items-center rounded-md border">
        {dark ? <Moon size={14} /> : <Sun size={14} />}
      </span>
      <span className="text-sm">{dark ? "Dark" : "Light"} mode</span>
    </button>
  );
}

function UserAvatar({ user }) {
  const [broken, setBroken] = useState(false);
  if (user.picture && !broken) {
    return (
      <img
        src={user.picture}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className="h-8 w-8 rounded-full object-cover"
      />
    );
  }
  return (
    <div className="grid h-8 w-8 place-items-center rounded-full bg-accent/15 font-display text-accent">
      {(user.name || user.email || "?")[0].toUpperCase()}
    </div>
  );
}

export default function Layout({ children, user, onLogout }) {
  const nav =
    user?.role === "admin"
      ? [
          ...BASE_NAV,
          { to: "/members", label: "Members", icon: ShieldCheck },
          { to: "/prompts", label: "Prompts", icon: ScrollText },
        ]
      : BASE_NAV;
  return (
    <div className="mx-auto flex min-h-screen max-w-[1400px] gap-6 px-4 py-5 md:px-6">
      {/* Sidebar */}
      <aside className="sticky top-5 hidden h-[calc(100vh-2.5rem)] w-60 shrink-0 flex-col justify-between md:flex">
        <div>
          <Wordmark />
          <nav className="mt-8 flex flex-col gap-1">
            {nav.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition ${
                    isActive
                      ? "bg-surface text-ink shadow-soft"
                      : "text-muted hover:bg-surface/60 hover:text-ink"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon size={18} className={isActive ? "text-accent" : ""} />
                    {label}
                    {isActive && (
                      <motion.span
                        layoutId="navdot"
                        className="ml-auto h-1.5 w-1.5 rounded-full bg-accent"
                      />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex flex-col gap-1 border-t pt-3">
          {user && (
            <div className="flex items-center gap-2.5 px-2 pb-2">
              <UserAvatar user={user} />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{user.name || "You"}</div>
                <div className="truncate text-[11px] text-muted">{user.email}</div>
              </div>
            </div>
          )}
          <ThemeToggle />
          <button onClick={onLogout} className="btn-ghost h-10 justify-start px-3 text-sm">
            <span className="grid h-6 w-6 place-items-center rounded-md border">
              <LogOut size={14} />
            </span>
            Sign out
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="fixed inset-x-0 top-0 z-20 flex items-center justify-between border-b bg-bg/80 px-4 py-3 backdrop-blur md:hidden">
        <Wordmark />
        <div className="flex gap-1">
          {nav.map(({ to, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `grid h-10 w-10 place-items-center rounded-lg ${
                  isActive ? "bg-surface text-accent" : "text-muted"
                }`
              }
            >
              <Icon size={18} />
            </NavLink>
          ))}
        </div>
      </div>

      {/* Content */}
      <main className="min-w-0 flex-1 pt-16 md:pt-0">{children}</main>
    </div>
  );
}
