import { motion } from "framer-motion";
import { Activity, Coins, Flame, Scale } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api.js";
import { useTheme } from "../lib/theme.jsx";

const fade = {
  hidden: { opacity: 0, y: 14 },
  show: (i) => ({ opacity: 1, y: 0, transition: { delay: i * 0.06, duration: 0.5, ease: [0.22, 1, 0.36, 1] } }),
};

function useChartColors() {
  const { theme } = useTheme();
  const dark = theme === "dark";
  return {
    accent: dark ? "#34D399" : "#147D5A",
    amber: dark ? "#E0A050" : "#C67C38",
    grid: dark ? "#23302B" : "#E4E0D4",
    axis: dark ? "#8A9A92" : "#6B7A72",
    surface: dark ? "#141C19" : "#FFFDF7",
    ink: dark ? "#EDEBE3" : "#14201B",
    sleep: dark ? "#A78BFA" : "#7C5CBF",
    heart: dark ? "#F87171" : "#C0392B",
    spo2: dark ? "#38BDF8" : "#0E7AA6",
  };
}

function Stat({ i, icon: Icon, label, value, unit, accent }) {
  return (
    <motion.div custom={i} variants={fade} initial="hidden" animate="show" className="card p-5">
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        <span
          className="grid h-8 w-8 place-items-center rounded-lg"
          style={{ background: `${accent}1f`, color: accent }}
        >
          <Icon size={16} />
        </span>
      </div>
      <div className="mt-4 flex items-baseline gap-1.5">
        <span className="font-display text-4xl tracking-tight">{value}</span>
        {unit && <span className="text-sm text-muted">{unit}</span>}
      </div>
    </motion.div>
  );
}

function ChartCard({ i, title, subtitle, children }) {
  return (
    <motion.div custom={i} variants={fade} initial="hidden" animate="show" className="card p-5">
      <div className="mb-4">
        <h3 className="font-display text-lg tracking-tight">{title}</h3>
        {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
      </div>
      {children}
    </motion.div>
  );
}

function ChartTip({ active, payload, label, unit, c }) {
  if (!active || !payload?.length) return null;
  const multi = payload.length > 1;
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs shadow-soft"
      style={{ background: c.surface, color: c.ink, borderColor: c.grid }}
    >
      <div className="text-muted">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="font-semibold">
          {multi && <span className="font-normal text-muted">{p.name}: </span>}
          {p.value}
          {unit ? ` ${unit}` : ""}
        </div>
      ))}
    </div>
  );
}

const num = (v, d = 0) => (v == null || Number.isNaN(v) ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
const shortDay = (s) => (s ? s.slice(5) : "");

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const c = useChartColors();

  useEffect(() => {
    api.dashboard().then(setData).catch((e) => setError(e.message));
  }, []);

  const macros = data?.nutrition_today?.summary || {};
  const weightSeries = useMemo(() => {
    const rows = data?.weights?.history?.data || [];
    return [...rows].sort((a, b) => (a.day > b.day ? 1 : -1)).map((r) => ({ day: shortDay(r.day), value: r.value }));
  }, [data]);
  const latestWeight = weightSeries.at(-1)?.value;
  const sleepSeries = useMemo(
    () => (data?.sleep || []).map((r) => ({ day: shortDay(r.day), value: r.value })),
    [data],
  );
  const heartRateSeries = useMemo(
    () => (data?.heart_rate || []).map((r) => ({ day: shortDay(r.day), value: r.value })),
    [data],
  );
  const spo2Series = useMemo(
    () => (data?.spo2 || []).map((r) => ({ day: shortDay(r.day), value: r.value })),
    [data],
  );
  const costSeries = data
    ? [
        { name: "Today", cost: +(data.usage.today.cost || 0).toFixed(3) },
        { name: "7 days", cost: +(data.usage.week.cost || 0).toFixed(3) },
        { name: "30 days", cost: +(data.usage.month.cost || 0).toFixed(3) },
      ]
    : [];
  const targets = data?.macro_targets;
  const macroBars = [
    { name: "Protein", g: macros.protein, target: targets?.protein },
    { name: "Carbs", g: macros.carbs, target: targets?.carbs },
    { name: "Fat", g: macros.fat, target: targets?.fat },
    { name: "Fiber", g: macros.fiber, target: targets?.fiber },
  ]
    .filter((m) => m.g != null)
    .map((m) => ({ ...m, g: Math.round(m.g) }));
  // A fresh day with nothing logged yet still has target-only entries (g: 0),
  // which would otherwise render as an empty-looking chart of bare target bars.
  const hasConsumedMacros = macroBars.some((m) => m.g > 0);

  const name = data?.profile?.name;
  const wUnit = data?.weights?.unit || data?.profile?.weight_unit || "lbs";

  return (
    <div className="pb-10">
      <motion.header custom={0} variants={fade} initial="hidden" animate="show" className="mb-6">
        <p className="text-sm text-muted">
          {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
        </p>
        <h1 className="font-display text-3xl tracking-tight md:text-4xl">
          {name ? `Hello, ${name}.` : "Your day at a glance."}
        </h1>
      </motion.header>

      {error && <div className="card mb-6 p-4 text-sm text-amber">Couldn't load data: {error}</div>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat i={1} icon={Flame} label="Calories today" value={num(macros.energy)} unit="kcal" accent={c.amber} />
        <Stat i={2} icon={Activity} label="Protein today" value={num(macros.protein, 1)} unit="g" accent={c.accent} />
        <Stat i={3} icon={Scale} label="Latest weight" value={latestWeight != null ? num(latestWeight, 1) : "—"} unit={wUnit} accent={c.accent} />
        <Stat i={4} icon={Coins} label="Cost · 30d" value={data ? `$${num(data.usage.month.cost, 2)}` : "—"} accent={c.amber} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartCard i={5} title="Weight trend" subtitle={`Logged to Cronometer · ${wUnit}`}>
            {weightSeries.length ? (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={weightSeries} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={c.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                  <Tooltip content={<ChartTip unit={wUnit} c={c} />} />
                  <Line type="monotone" dataKey="value" stroke={c.accent} strokeWidth={2.5} dot={{ r: 3, fill: c.accent }} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <Empty>No weight history yet — log your weight in chat.</Empty>
            )}
          </ChartCard>
        </div>

        <ChartCard
          i={6}
          title="Macros today"
          subtitle={targets ? "grams consumed vs. your daily target" : "grams consumed"}
        >
          {hasConsumedMacros ? (
            <>
              {targets && (
                <div className="mb-3 flex items-center gap-4 text-xs text-muted">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: c.accent }} />
                    Consumed
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: c.axis }} />
                    Target
                  </span>
                </div>
              )}
              <ResponsiveContainer width="100%" height={targets ? 208 : 240}>
                <BarChart data={macroBars} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={c.grid} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip unit="g" c={c} />} cursor={{ fill: `${c.accent}12` }} />
                  <Bar dataKey="g" name="Consumed" fill={c.accent} radius={[6, 6, 0, 0]} maxBarSize={28} />
                  {targets && (
                    <Bar
                      dataKey="target"
                      name="Target"
                      fill={c.axis}
                      fillOpacity={0.3}
                      radius={[6, 6, 0, 0]}
                      maxBarSize={28}
                    />
                  )}
                </BarChart>
              </ResponsiveContainer>
            </>
          ) : (
            <Empty>Nothing logged today yet.</Empty>
          )}
        </ChartCard>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <ChartCard i={8} title="Sleep trend" subtitle="Hours asleep · last 30 days">
          {sleepSeries.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={sleepSeries} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTip unit="hrs" c={c} />} cursor={{ fill: `${c.sleep}12` }} />
                <Bar dataKey="value" fill={c.sleep} radius={[4, 4, 0, 0]} maxBarSize={16} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty height={200}>No sleep data from Google Health yet.</Empty>
          )}
        </ChartCard>

        <ChartCard i={9} title="Heart rate trend" subtitle="Resting BPM · last 30 days">
          {heartRateSeries.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={heartRateSeries} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                <Tooltip content={<ChartTip unit="bpm" c={c} />} />
                <Line type="monotone" dataKey="value" stroke={c.heart} strokeWidth={2} dot={{ r: 2, fill: c.heart }} activeDot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <Empty height={200}>No heart rate data from Google Health yet.</Empty>
          )}
        </ChartCard>

        <ChartCard i={10} title="SpO2 trend" subtitle="Blood oxygen % · last 30 days">
          {spo2Series.length ? (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={spo2Series} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tick={{ fill: c.axis, fontSize: 11 }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                <Tooltip content={<ChartTip unit="%" c={c} />} />
                <Line type="monotone" dataKey="value" stroke={c.spo2} strokeWidth={2} dot={{ r: 2, fill: c.spo2 }} activeDot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <Empty height={200}>No SpO2 data from Google Health yet.</Empty>
          )}
        </ChartCard>
      </div>

      <div className="mt-4">
        <ChartCard i={11} title="Assistant cost" subtitle="LLM spend across periods">
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={costSeries} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid stroke={c.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: c.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTip unit="$" c={c} />} cursor={{ fill: `${c.amber}12` }} />
              <Bar dataKey="cost" fill={c.amber} radius={[6, 6, 0, 0]} maxBarSize={54} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}

function Empty({ height = 240, children }) {
  return (
    <div className="grid place-items-center text-center text-sm text-muted" style={{ height }}>
      {children}
    </div>
  );
}
