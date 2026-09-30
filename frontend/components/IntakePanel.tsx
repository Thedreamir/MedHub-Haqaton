"use client";
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { User, Users, Activity, HeartPulse, Flag, ClipboardCheck, ShieldAlert } from "lucide-react";
import { useStore } from "@/lib/store";
import type { Intake } from "@/lib/types";

const SYMPTOMS: [string, string][] = [
  ["fatigue", "усталость"], ["gi", "ЖКТ"], ["cardio", "сердце/давление"], ["neuro", "неврология"],
  ["respiratory", "дыхание"], ["endocrine", "эндокринология"], ["musculoskeletal", "опорно-двигательный"],
  ["womens_health", "женское здоровье"], ["mens_health", "мужское здоровье"], ["vision", "зрение"],
  ["skin", "кожа"], ["other", "другое"],
];
const FAMILY: [string, string][] = [
  ["diabetes", "диабет"], ["hypertension", "гипертония"], ["ihd", "ИБС/инфаркт"],
  ["stroke", "инсульт"], ["oncology", "онкология"], ["glaucoma", "глаукома"],
];
const CHRONIC: [string, string][] = [
  ["hypertension", "гипертония"], ["ihd", "ИБС"], ["diabetes", "диабет"], ["glaucoma", "глаукома"],
  ["hepatitis_b", "гепатит B"], ["hepatitis_c", "гепатит C"], ["other", "другое"],
];
const REDFLAG_LABELS: Record<string, string> = {
  chest_pain: "боль в груди", neuro_deficit: "неврологический дефицит", severe_dyspnea: "одышка в покое",
  bleeding: "кровотечение", syncope: "обморок", high_fever: "высокая температура",
  pregnancy_acute: "острое при беременности", suicidal_ideation: "суицидальные мысли",
};

const EMPTY: Intake = {
  age: null, gender: null, symptoms: [], family_history: [], chronic_conditions: [],
  red_flags: [], is_pregnant: null, child_age_months: null, smoking: null, state_version: 0,
};

type ListKey = "symptoms" | "family_history" | "chronic_conditions";

function Chip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className={`text-[13px] px-2.5 py-1 rounded-full border transition ${
        active ? "bg-emerald text-white border-emerald" : "bg-white text-emerald border-emerald-soft hover:bg-emerald-mist"}`}>
      {label}
    </button>
  );
}

function Tile({ icon, title, highlight, danger, wide, children }: {
  icon: React.ReactNode; title: string; highlight: boolean; danger?: boolean; wide?: boolean; children: React.ReactNode;
}) {
  return (
    <motion.div animate={highlight ? { scale: [1, 1.03, 1], backgroundColor: ["#FFFFFF", "#E7F0EB", "#FFFFFF"] } : {}}
      transition={{ duration: 0.9 }}
      className={`${wide ? "col-span-2" : ""} rounded-2xl border p-4 shadow-soft ${danger ? "border-red-200 bg-red-50" : "border-emerald-soft bg-white"}`}>
      <div className="flex items-center gap-2 mb-2.5">
        <span className={danger ? "text-red-600" : "text-emerald"}>{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</span>
      </div>
      {children}
    </motion.div>
  );
}

export default function IntakePanel() {
  const { intake, busy, submitManual } = useStore();
  const [draft, setDraft] = useState<Intake>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const prev = useRef<string>("");

  // Chat/LLM updates flow in from the store; refresh the local draft unless
  // the user is mid-edit (dirty), so manual typing is never clobbered.
  useEffect(() => {
    if (!intake) return;
    const cur = JSON.stringify([intake.age, intake.gender, intake.symptoms, intake.family_history,
      intake.chronic_conditions, intake.red_flags, intake.is_pregnant, intake.child_age_months, intake.smoking]);
    if (prev.current && prev.current !== cur) {
      const keys = new Set<string>();
      const p = JSON.parse(prev.current); const c = JSON.parse(cur);
      ["age", "gender", "symptoms", "family", "chronic", "flags", "pregnant", "child", "smoking"].forEach((k, i) => {
        if (JSON.stringify(p[i]) !== JSON.stringify(c[i])) keys.add(k);
      });
      setChanged(keys);
      const t = setTimeout(() => setChanged(new Set()), 1200);
      prev.current = cur;
      if (!dirty) setDraft({ ...intake });
      return () => clearTimeout(t);
    }
    prev.current = cur;
    if (!dirty) setDraft({ ...intake });
  }, [intake, dirty]);

  const edit = <K extends keyof Intake>(key: K, value: Intake[K]) => {
    setDirty(true);
    setDraft((d) => ({ ...d, [key]: value }));
  };
  const toggle = (key: ListKey, v: string) => {
    setDirty(true);
    setDraft((d) => ({ ...d, [key]: d[key].includes(v) ? d[key].filter((x) => x !== v) : [...d[key], v] }));
  };
  const num = (raw: string, min: number, max: number): number | null => {
    if (raw.trim() === "") return null;
    const n = Math.round(Number(raw));
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : null;
  };
  const submit = async () => {
    if (await submitManual(draft)) setDirty(false);
  };

  const numCls = "w-full rounded-lg border border-emerald-soft px-2.5 py-1.5 text-sm text-ink bg-white focus:outline-none focus:ring-1 focus:ring-emerald";

  return (
    <div className="h-full overflow-y-auto chat-scroll">
      <div className="grid grid-cols-2 gap-3 content-start pb-1">
        <Tile icon={<User className="w-4 h-4" />} title="Возраст" highlight={changed.has("age") || changed.has("child")}>
          <div className="space-y-2">
            <label className="block text-[11px] text-gray-400">лет
              <input type="number" min={1} max={120} className={numCls} placeholder="например, 42"
                value={draft.age ?? ""} onChange={(e) => edit("age", num(e.target.value, 1, 120))} />
            </label>
            <label className="block text-[11px] text-gray-400">или ребёнок, месяцев
              <input type="number" min={0} max={204} className={numCls} placeholder="0–204"
                value={draft.child_age_months ?? ""} onChange={(e) => edit("child_age_months", num(e.target.value, 0, 204))} />
            </label>
          </div>
        </Tile>

        <Tile icon={<Users className="w-4 h-4" />} title="Пол" highlight={changed.has("gender") || changed.has("pregnant")}>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={draft.gender === "male"} label="мужской" onClick={() => { edit("gender", "male"); edit("is_pregnant", null); }} />
            <Chip active={draft.gender === "female"} label="женский" onClick={() => edit("gender", "female")} />
          </div>
          {draft.gender === "female" && (
            <div className="mt-2.5">
              <div className="text-[11px] text-gray-400 mb-1">беременность</div>
              <div className="flex flex-wrap gap-1.5">
                <Chip active={draft.is_pregnant === true} label="да" onClick={() => edit("is_pregnant", true)} />
                <Chip active={draft.is_pregnant === false} label="нет" onClick={() => edit("is_pregnant", false)} />
                <Chip active={draft.is_pregnant === null} label="не знаю" onClick={() => edit("is_pregnant", null)} />
              </div>
            </div>
          )}
        </Tile>

        <Tile wide icon={<Activity className="w-4 h-4" />} title="Симптомы — что беспокоит" highlight={changed.has("symptoms")}>
          <div className="flex flex-wrap gap-1.5">
            {SYMPTOMS.map(([v, l]) => (
              <Chip key={v} active={draft.symptoms.includes(v)} label={l} onClick={() => toggle("symptoms", v)} />
            ))}
          </div>
        </Tile>

        <Tile wide icon={<HeartPulse className="w-4 h-4" />} title="Анамнез и семья" highlight={changed.has("family") || changed.has("chronic") || changed.has("smoking")}>
          <div className="text-[11px] text-gray-400 mb-1">здоровье семьи — 1-я линия (родители, братья, сёстры)</div>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {FAMILY.map(([v, l]) => (
              <Chip key={v} active={draft.family_history.includes(v)} label={l} onClick={() => toggle("family_history", v)} />
            ))}
          </div>
          <div className="text-[11px] text-gray-400 mb-1">хронические состояния</div>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {CHRONIC.map(([v, l]) => (
              <Chip key={v} active={draft.chronic_conditions.includes(v)} label={l} onClick={() => toggle("chronic_conditions", v)} />
            ))}
          </div>
          <div className="text-[11px] text-gray-400 mb-1">образ жизни</div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={draft.smoking === true} label="курю / вейплю"
              onClick={() => edit("smoking", draft.smoking === true ? null : true)} />
            <Chip active={draft.smoking === false} label="не курю"
              onClick={() => edit("smoking", draft.smoking === false ? null : false)} />
          </div>
        </Tile>

        <Tile wide danger icon={<Flag className="w-4 h-4" />} title="Красные флаги" highlight={changed.has("flags")}>
          {(intake?.red_flags?.length ?? 0) > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {intake!.red_flags.map((v) => (
                <span key={v} className="text-[13px] px-2.5 py-1 rounded-full bg-red-100 text-red-700">
                  {REDFLAG_LABELS[v] ?? v}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-sm text-gray-300">не выявлены</span>
          )}
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-red-400">
            <ShieldAlert className="w-3.5 h-3.5" />
            Заполняется только из чата автоматически — тревожный признак нельзя снять вручную.
          </div>
        </Tile>

        <div className="col-span-2 rounded-2xl border border-emerald-soft bg-white p-4 shadow-soft flex items-center gap-3">
          <button onClick={submit} disabled={busy}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald text-white text-sm font-semibold hover:opacity-90 transition disabled:opacity-50">
            <ClipboardCheck className="w-4 h-4" />
            {busy ? "Считаю…" : "Рассчитать чекап"}
          </button>
          <span className="text-[11px] text-gray-400 leading-snug">
            Ручной ввод и чат пишут в одну анкету — движок по приказу ДСМ-174 считает только по ней.
          </span>
        </div>
      </div>
    </div>
  );
}
