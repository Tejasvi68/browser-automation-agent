export default function StepTimeline({ steps, selectedStepIdx, onSelectStep }) {
  return (
    <div className="lg:col-span-4 bg-white/[0.025] backdrop-blur-xl border border-white/[0.08] rounded-2xl p-4 flex flex-col justify-between max-h-[550px]">
      <div className="text-xs font-semibold text-zinc-200 pb-3 border-b border-white/[0.07] flex items-center justify-between">
        <span>Step Execution Timeline</span>
        <span className="text-[11px] text-zinc-500">{steps.length} steps</span>
      </div>

      <div className="flex-1 overflow-y-auto py-3 space-y-2.5 pr-1">
        {steps.map((s, idx) => {
          const isSelected = idx === selectedStepIdx;
          return (
            <button
              key={s.step}
              onClick={() => onSelectStep(idx)}
              className={`w-full text-left p-3 rounded-xl border transition cursor-pointer ${
                isSelected
                  ? "bg-violet-500/12 border-violet-500/40"
                  : "bg-white/[0.02] hover:bg-white/[0.05] border-white/[0.06]"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-zinc-100 flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-violet-500/20 text-violet-300 text-[10px] flex items-center justify-center font-semibold">
                    {s.step}
                  </span>
                  {s.action}
                </span>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full ${
                    s.success
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-rose-500/10 text-rose-400"
                  }`}
                >
                  {s.success ? "Completed" : "Recovered"}
                </span>
              </div>
              <p className="text-[11px] text-zinc-400 mt-1.5 line-clamp-2">
                {s.thought}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}