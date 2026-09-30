"use client";
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { SendHorizonal, Sparkles, RotateCcw, WifiOff } from "lucide-react";
import { useStore } from "@/lib/store";

const GOLDEN = [
  { label: "Демо: мужчина 42, усталость", text: "Мне 42 года, мужчина. Постоянно уставший, после еды тяжесть. У отца диабет." },
  { label: "Демо: женщина 35, плановый", text: "Мне 35 лет, женщина. Хочу плановый чекап, ничего не беспокоит." },
  { label: "Демо: красный флаг 55", text: "Мне 55 лет, мужчина. Острая боль за грудиной, отдаёт в левую руку, холодный пот." },
];

export default function ChatPanel() {
  const { messages, send, loadGolden, reset, offline, busy, llmStatus } = useStore();
  const [text, setText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  return (
    <div className="flex flex-col h-full bg-white rounded-2xl shadow-soft border border-emerald-soft overflow-hidden">
      <div className="px-5 py-4 border-b border-emerald-soft flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-emerald" />
          <span className="font-semibold text-emerald">Чат с конструктором</span>
          {llmStatus === "cached_golden" && <span className="text-[10px] px-2 py-0.5 rounded-full bg-gold-soft text-gold">кэш</span>}
          {llmStatus === "degraded_keyword" && <span className="text-[10px] px-2 py-0.5 rounded-full bg-gold-soft text-gold">локальный разбор</span>}
        </div>
        <button onClick={reset} className="text-gray-400 hover:text-emerald transition" title="Начать заново">
          <RotateCcw className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto chat-scroll px-5 py-4 space-y-3">
        {messages.map((m, i) => (
          <motion.div key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-[15px] leading-relaxed ${
              m.role === "user" ? "ml-auto bg-emerald text-white rounded-br-md" : "bg-emerald-mist text-ink rounded-bl-md"}`}>
            {m.text}
          </motion.div>
        ))}
        {busy && <div className="bg-emerald-mist text-emerald/60 px-4 py-2.5 rounded-2xl rounded-bl-md max-w-[60%] text-sm animate-pulse">Анализирую…</div>}
        <div ref={bottomRef} />
      </div>

      {offline && (
        <div className="mx-4 mb-2 flex items-center gap-2 text-xs text-gold bg-gold-soft rounded-xl px-3 py-2">
          <WifiOff className="w-3.5 h-3.5" /> Офлайн-режим: золотые кейсы работают из кэша
        </div>
      )}

      <div className="px-4 pb-2 flex flex-wrap gap-2">
        {GOLDEN.map((g, i) => (
          <button key={i} onClick={() => loadGolden(i, g.text)}
            className="text-[11px] px-3 py-1.5 rounded-full border border-emerald-soft text-emerald hover:bg-emerald-mist transition">
            {g.label}
          </button>
        ))}
      </div>

      <form className="p-4 pt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text); setText(""); }}>
        <input value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Например: 42 года, мужчина, устаю, у отца диабет…"
          className="flex-1 px-4 py-3 rounded-xl border border-emerald-soft focus:outline-none focus:ring-2 focus:ring-emerald/30 text-[15px]" />
        <button type="submit" disabled={busy}
          className="px-4 py-3 rounded-xl bg-emerald text-white hover:bg-emerald-mid transition disabled:opacity-50">
          <SendHorizonal className="w-5 h-5" />
        </button>
      </form>
    </div>
  );
}
