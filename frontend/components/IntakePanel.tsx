"use client";
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { User, Users, Activity, HeartPulse, Flag, Baby } from "lucide-react";
import { useStore } from "@/lib/store";

const LABELS: Record<string, string> = {
  fatigue: "усталость", gi: "ЖКТ", cardio: "сердце/давление", neuro: "неврология",
  respiratory: "дыхание", endocrine: "эндокринология", musculoskeletal: "опорно-двигательный",
  womens_health: "женское здоровье", mens_health: "мужское здоровье", vision: "зрение", skin: "кожа", other: "другое",
  diabetes: "диабет", hypertension: "гипертония", ihd: "ИБС/инфаркт", stroke: "инсульт",
  oncology: "онкология", glaucoma: "глаукома", hepatitis_b: "гепатит B", hepatitis_c: "гепатит C",
  chest_pain: "боль в груди", neuro_deficit: "неврологический дефицит", severe_dyspnea: "одышка в покое",
  bleeding: "кровотечение", syncope: "обморок", high_fever: "высокая температура",
  pregnancy_acute: "острое при беременности", suicidal_ideation: "суицидальные мысли",
};

function Tile({ icon, title, values, highlight, danger }: {
  icon: React.ReactNode; title: string; values: string[]; highlight: boolean; danger?: boolean;
}) {
  const empty = values.length === 0;
  return (
    <motion.div animate={highlight ? { scale: [1, 1.03, 1], backgroundColor: ["#FFFFFF", "#E7F0EB", "#FFFFFF"] } : {}}
      transition={{ duration: 0.9 }}
      className={`rounded-2xl border p-4 shadow-soft ${danger && !empty ? "border-red-200 bg-red-50" : "border-emerald-soft bg-white"}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={danger && !empty ? "text-red-600" : "text-emerald"}>{icon}</span>
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</span>
      </div>
      {empty ? <span className="text-sm text-gray-300">пока пусто</span> : (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v, i) => (
            <span key={i} className={`text-[13px] px-2.5 py-1 rounded-full ${
              danger ? "bg-red-100 text-red-700" : "bg-emerald-mist text-emerald"}`}>{v}</span>
          ))}
        </div>
      )}
    </motion.div>
  );
}

export default function IntakePanel() {
  const { intake } = useStore();
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const prev = useRef<string>("");
  useEffect(() => {
    if (!intake) return;
    const cur = JSON.stringify([intake.age, intake.gender, intake.symptoms, intake.family_history,
      intake.chronic_conditions, intake.red_flags, intake.is_pregnant, intake.child_age_months]);
    if (prev.current && prev.current !== cur) {
      const keys = new Set<string>();
      const p = JSON.parse(prev.current); const c = JSON.parse(cur);
      ["age", "gender", "symptoms", "family", "chronic", "flags", "pregnant", "child"].forEach((k, i) => {
        if (JSON.stringify(p[i]) !== JSON.stringify(c[i])) keys.add(k);
      });
      setChanged(keys);
      const t = setTimeout(() => setChanged(new Set()), 1200);
      return () => clearTimeout(t);
    }
    prev.current = cur;
  }, [intake]);

  const age = intake?.age ? [`${intake.age} лет`] : intake?.child_age_months != null
    ? [`ребёнок ${intake.child_age_months} мес`] : [];
  const gender = intake?.gender ? [intake.gender === "male" ? "мужской" : "женский"] : [];
  if (intake?.is_pregnant) gender.push("беременность");
  const map = (arr: string[]) => arr.map((x) => LABELS[x] ?? x);

  return (
    <div className="h-full grid grid-cols-2 gap-3 content-start">
      <Tile icon={<User className="w-4 h-4" />} title="Возраст" values={age} highlight={changed.has("age")} />
      <Tile icon={<Users className="w-4 h-4" />} title="Пол" values={gender} highlight={changed.has("gender") || changed.has("pregnant")} />
      <Tile icon={<Activity className="w-4 h-4" />} title="Симптомы" values={map(intake?.symptoms ?? [])} highlight={changed.has("symptoms")} />
      <Tile icon={<HeartPulse className="w-4 h-4" />} title="Анамнез и семья"
        values={map([...(intake?.family_history ?? []), ...(intake?.chronic_conditions ?? [])])}
        highlight={changed.has("family") || changed.has("chronic")} />
      <div className="col-span-2">
        <Tile icon={<Flag className="w-4 h-4" />} title="Красные флаги"
          values={(intake?.red_flags?.length ?? 0) > 0 ? map(intake!.red_flags) : []}
          highlight={changed.has("flags")} danger />
      </div>
      <div className="col-span-2 rounded-2xl border border-dashed border-emerald-soft bg-emerald-mist/50 p-3 flex items-center gap-2">
        <Baby className="w-4 h-4 text-emerald/50" />
        <span className="text-xs text-emerald/70">Живая анкета: поля заполняются из ваших сообщений и фиксируются на сервере — движок решает только по ним.</span>
      </div>
    </div>
  );
}
