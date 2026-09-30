"use client";
import { useEffect } from "react";
import { Leaf } from "lucide-react";
import ChatPanel from "@/components/ChatPanel";
import IntakePanel from "@/components/IntakePanel";
import ResultView from "@/components/ResultView";
import { useStore } from "@/lib/store";

export default function Home() {
  const hydrate = useStore((s) => s.hydrate);
  useEffect(() => { hydrate(); }, [hydrate]);

  return (
    <main className="min-h-screen bg-cream">
      <header className="max-w-7xl mx-auto px-6 pt-6 pb-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-emerald flex items-center justify-center">
            <Leaf className="w-5 h-5 text-gold" />
          </div>
          <div>
            <div className="font-bold text-emerald leading-tight">Check-up Intelligence</div>
            <div className="text-[11px] text-gray-400">PRIME Green Clinic · конструктор персонального чекапа</div>
          </div>
        </div>
        <span className="text-[10px] px-2.5 py-1 rounded-full bg-gold-soft text-gold font-medium">ДЕМО · синтетические пациенты</span>
      </header>

      <div className="max-w-7xl mx-auto px-6 pb-10">
        <div className="grid lg:grid-cols-2 gap-4 lg:h-[560px]">
          <ChatPanel />
          <IntakePanel />
        </div>
        <ResultView />
      </div>
    </main>
  );
}
