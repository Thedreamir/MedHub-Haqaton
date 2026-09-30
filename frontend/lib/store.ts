"use client";
import { create } from "zustand";
import golden from "./golden.json";
import type { ChatResponse, CheckupResult, Intake } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const CACHE_KEY = "checkup-last-response";

export interface Msg { role: "user" | "assistant"; text: string; }

interface State {
  sessionId: string;
  messages: Msg[];
  intake: Intake | null;
  result: CheckupResult | null;
  llmStatus: string | null;
  offline: boolean;
  busy: boolean;
  send: (text: string) => Promise<void>;
  submitManual: (draft: Intake) => Promise<boolean>;
  loadGolden: (i: number, label: string) => void;
  reset: () => void;
  hydrate: () => void;
}

const newSession = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now();

export const useStore = create<State>((set, get) => ({
  sessionId: newSession(),
  messages: [{ role: "assistant", text: "Здравствуйте! Расскажите о себе простыми словами: возраст, пол, что беспокоит, здоровье семьи. Анкета справа заполнится сама — или заполните её вручную и нажмите «Рассчитать чекап»." }],
  intake: null, result: null, llmStatus: null, offline: false, busy: false,

  send: async (text) => {
    if (get().busy || !text.trim()) return;
    set((s) => ({ busy: true, messages: [...s.messages, { role: "user", text }] }));
    try {
      const r = await fetch(`${API}/api/intake/message`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: get().sessionId, text }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const data: ChatResponse = await r.json();
      if (typeof localStorage !== "undefined") localStorage.setItem(CACHE_KEY, JSON.stringify(data));
      set((s) => ({
        busy: false, offline: false, intake: data.intake, result: data.result,
        llmStatus: data.llm_status,
        messages: [...s.messages, { role: "assistant", text: data.assistant_message }],
      }));
    } catch {
      set((s) => ({
        busy: false, offline: true,
        messages: [...s.messages, { role: "assistant", text: "Сеть недоступна — работаю офлайн. Ниже можно открыть золотой демо-кейс, он загрузится мгновенно из кэша." }],
      }));
    }
  },

  submitManual: async (draft) => {
    if (get().busy) return false;
    set({ busy: true });
    try {
      // Safety: red flags are never editable by hand - always re-attach the
      // latest server/chat red-flag state so a manual submit can't drop one.
      const intake = { ...draft, red_flags: get().intake?.red_flags ?? draft.red_flags };
      const r = await fetch(`${API}/api/intake/manual`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: get().sessionId, intake }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const data: ChatResponse = await r.json();
      if (typeof localStorage !== "undefined") localStorage.setItem(CACHE_KEY, JSON.stringify(data));
      set((s) => ({
        busy: false, offline: false, intake: data.intake, result: data.result,
        llmStatus: data.llm_status,
        messages: [...s.messages, { role: "assistant", text: data.assistant_message }],
      }));
      return true;
    } catch {
      set((s) => ({
        busy: false, offline: true,
        messages: [...s.messages, { role: "assistant", text: "Сеть недоступна — анкету не отправить. Попробуйте ещё раз или откройте золотой демо-кейс из кэша." }],
      }));
      return false;
    }
  },

  loadGolden: (i, label) => {
    const data = (golden as unknown as ChatResponse[])[i];
    if (!data) return;
    set((s) => ({
      offline: false, intake: data.intake, result: data.result, llmStatus: "cached_golden",
      messages: [...s.messages, { role: "user", text: label }, { role: "assistant", text: data.assistant_message }],
    }));
  },

  reset: () => {
    const sid = get().sessionId;
    fetch(`${API}/api/intake/reset/${sid}`, { method: "POST" }).catch(() => {});
    if (typeof localStorage !== "undefined") localStorage.removeItem(CACHE_KEY);
    set({
      sessionId: newSession(), intake: null, result: null, llmStatus: null, offline: false,
      messages: [{ role: "assistant", text: "Начнём заново: возраст, пол, что беспокоит?" }],
    });
  },

  hydrate: () => {
    try {
      const raw = typeof localStorage !== "undefined" ? localStorage.getItem(CACHE_KEY) : null;
      if (!raw) return;
      const data: ChatResponse = JSON.parse(raw);
      set({ intake: data.intake, result: data.result, llmStatus: "cached_golden" });
    } catch { /* no cache */ }
  },
}));

export function buildIcsClientSide(): string {
  const d = new Date(Date.now() + 86400000);
  const dt = d.toISOString().slice(0, 10).replace(/-/g, "");
  return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Checkup Constructor//RU", "BEGIN:VEVENT",
    `UID:${newSession()}@checkup-demo`, `DTSTART;VALUE=DATE:${dt}`,
    "SUMMARY:Чекап PRIME — анализы строго натощак (вода можно), начало в 8:00",
    "DESCRIPTION:Демо-напоминание. Подготовку подтверждает клиника при записи: +7 747 094 26 21",
    "END:VEVENT", "END:VCALENDAR", ""].join("\r\n");
}

export async function downloadIcs(intake: Intake) {
  let body = "";
  try {
    const r = await fetch(`${API}/api/reminder/ics`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(intake),
    });
    if (!r.ok) throw new Error();
    body = await r.text();
  } catch { body = buildIcsClientSide(); }
  const blob = new Blob([body], { type: "text/calendar" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "checkup-reminder.ics";
  a.click();
  URL.revokeObjectURL(a.href);
}
