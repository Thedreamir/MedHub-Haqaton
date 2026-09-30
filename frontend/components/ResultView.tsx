"use client";
import { motion } from "framer-motion";
import { ShieldAlert, BadgeCheck, Wallet, Route, Map, BellRing, Phone, Mail, Stethoscope, Info } from "lucide-react";
import { useStore, downloadIcs } from "@/lib/store";
import type { TestItem } from "@/lib/types";

const fmt = (n: number) => n.toLocaleString("ru-KZ").replace(/,/g, " ") + " ₸";

function TestRow({ t }: { t: TestItem }) {
  return (
    <li className="flex items-start gap-2 py-1.5">
      <BadgeCheck className={`w-4 h-4 mt-0.5 shrink-0 ${t.payment === "paid_prime" ? "text-gold" : "text-emerald"}`} />
      <div className="text-sm leading-snug">
        <span className="font-medium">{t.name}</span>
        {t.payment !== "paid_prime" && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-emerald-mist text-emerald align-middle">0 ₸ ОСМС</span>}
        {t.needs_doctor_validation && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-gold-soft text-gold align-middle">подтверждает врач</span>}
        <div className="text-gray-500 text-[13px]">{t.why}</div>
      </div>
    </li>
  );
}

export default function ResultView() {
  const { result, intake } = useStore();
  if (!result) return null;

  if (result.is_emergency) {
    return (
      <motion.section initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
        className="mt-6 rounded-2xl border-2 border-red-300 bg-red-50 p-8 text-center shadow-lift">
        <ShieldAlert className="w-12 h-12 text-red-600 mx-auto mb-4" />
        <h2 className="text-2xl font-bold text-red-700 mb-2">Стоп. Это не случай планового чекапа</h2>
        <p className="text-red-700 max-w-xl mx-auto">{result.emergency_banner}</p>
        <p className="mt-4 text-sm text-red-500">Подбор коммерческого чекапа заблокирован движком — безопасность прежде продаж.</p>
      </motion.section>
    );
  }

  const pkg = result.prime_package;
  return (
    <motion.section initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mt-6 space-y-4">
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-2xl bg-white border border-emerald-soft shadow-soft p-6">
          <div className="flex items-center gap-2 mb-1">
            <Stethoscope className="w-5 h-5 text-emerald" />
            <h3 className="font-bold text-emerald text-lg">Положено по ОСМС — 0 ₸</h3>
          </div>
          <p className="text-xs text-gray-400 mb-3">Скрининги по приказу ДСМ-174/2020 (ред. № 75/2026) для вашего возраста и пола</p>
          {result.osms_free_tests.length === 0
            ? <p className="text-sm text-gray-400">По возрастной сетке в этом году скрининги не назначены — даты следующих смотрите в карте здоровья ниже.</p>
            : <ul className="divide-y divide-emerald-mist">{result.osms_free_tests.map((t, i) => <TestRow key={i} t={t} />)}</ul>}
        </div>

        {pkg && (
          <div className="rounded-2xl bg-emerald text-white shadow-lift p-6">
            <div className="flex items-center gap-2 mb-1">
              <Wallet className="w-5 h-5 text-gold" />
              <h3 className="font-bold text-lg">Усиление PRIME</h3>
            </div>
            <div className="text-2xl font-bold mt-1">{pkg.name}</div>
            <div className="text-3xl font-bold text-gold mt-2">{pkg.price_kzt ? fmt(pkg.price_kzt) : "цена уточняется клиникой"}</div>
            {pkg.composition_note && <p className="text-xs text-emerald-soft/80 mt-2 flex gap-1"><Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />{pkg.composition_note}</p>}
            {result.prime_addon_tests.length > 0 && (
              <div className="mt-4 bg-white/10 rounded-xl p-3">
                <div className="text-xs uppercase tracking-wide text-emerald-soft/70 mb-1">Персональные акценты по жалобам и анамнезу</div>
                <ul>{result.prime_addon_tests.map((t, i) => (
                  <li key={i} className="text-sm py-1">
                    {t.name}
                    {t.needs_doctor_validation && <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-gold/20 text-gold">подтверждает врач</span>}
                    <span className="block text-xs text-emerald-soft/70">{t.why}</span>
                  </li>))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="rounded-2xl bg-white border border-emerald-soft shadow-soft p-6">
        <div className="flex items-center gap-2 mb-4">
          <Route className="w-5 h-5 text-emerald" />
          <h3 className="font-bold text-emerald text-lg">Маршрут одного дня</h3>
        </div>
        <div className="grid md:grid-cols-3 gap-3">
          {result.itinerary_timeline.map((s) => (
            <div key={s.order} className="rounded-xl bg-emerald-mist p-4">
              <div className="text-[11px] uppercase tracking-wide text-emerald/60">{s.block}{s.time_window ? ` · ${s.time_window}` : ""}</div>
              <div className="font-semibold text-emerald mt-1">{s.title}</div>
              <div className="text-[13px] text-gray-600 mt-1 leading-snug">{s.details}</div>
            </div>
          ))}
        </div>
        <a href={`tel:${result.booking_contact_phone.replace(/\s/g, "")}`}
          className="mt-5 inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gold text-ink font-semibold hover:brightness-105 transition">
          <Phone className="w-4 h-4" /> Записаться: {result.booking_contact_phone}
        </a>
        <a href={`mailto:${result.booking_contact_email}`} className="ml-3 inline-flex items-center gap-1.5 text-sm text-emerald underline underline-offset-4">
          <Mail className="w-4 h-4" />{result.booking_contact_email}
        </a>
        <p className="text-[11px] text-gray-400 mt-2">Заявка уходит в контакт-центр клиники — без онлайн-оплаты и без обязательств.</p>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-2xl bg-white border border-emerald-soft shadow-soft p-6">
          <div className="flex items-center gap-2 mb-3">
            <Map className="w-5 h-5 text-emerald" />
            <h3 className="font-bold text-emerald text-lg">Карта здоровья — мой план</h3>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-gold-soft text-gold">демо-данные</span>
          </div>
          <ul className="space-y-2">
            {result.health_map.map((h, i) => (
              <li key={i} className="flex gap-3 items-start">
                <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${h.status === "done" ? "bg-emerald" : h.status === "due" ? "bg-gold" : "bg-gray-300"}`} />
                <div className="text-sm">
                  <span className="font-medium">{h.item}</span>
                  <span className="text-gray-500"> — {h.when}</span>
                  <div className="text-xs text-gray-400">{h.why}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-2xl bg-white border border-emerald-soft shadow-soft p-6 flex flex-col">
          <div className="flex items-center gap-2 mb-3">
            <BellRing className="w-5 h-5 text-emerald" />
            <h3 className="font-bold text-emerald text-lg">Напоминание о повторе</h3>
          </div>
          <p className="text-sm text-gray-600">{result.reminder?.message_preview}</p>
          <p className="text-xs text-gray-400 mt-1">{result.reminder?.due_in}</p>
          {intake && (
            <button onClick={() => downloadIcs(intake)}
              className="mt-4 self-start px-5 py-2.5 rounded-xl border border-emerald text-emerald font-medium hover:bg-emerald-mist transition text-sm">
              Добавить в календарь (.ics)
            </button>
          )}
          <p className="text-[11px] text-gray-400 mt-3">Roadmap: живой Telegram-бот с напоминаниями о подготовке и повторном скрининге.</p>
        </div>
      </div>

      <div className="rounded-xl bg-emerald-mist px-4 py-3 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-emerald/80">
        <span>⚕ {result.not_diagnosis}</span>
        <span>{result.disclaimer}</span>
        <span>Все пациенты в демо — синтетические.</span>
      </div>
    </motion.section>
  );
}
