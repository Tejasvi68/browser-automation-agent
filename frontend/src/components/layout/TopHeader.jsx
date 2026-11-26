export default function TopHeader({ activePage, currentRun }) {
  return (
    <header className="h-12 shrink-0 border-b border-white/[0.06] px-6 flex items-center justify-between bg-white/[0.01] backdrop-blur-md">
      <div className="flex items-center gap-2 text-xs text-zinc-400">
        <span className="capitalize text-zinc-200 font-medium">
          {activePage}
        </span>
        {currentRun && activePage === "workspace" && (
          <>
            <span>/</span>
            <span className="font-mono text-zinc-300">
              Run #{currentRun.run_id}
            </span>
            <span
              className={`ml-2 px-2 py-0.5 rounded-full text-[10px] font-medium border ${
                currentRun.status === "completed"
                  ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                  : currentRun.status === "awaiting_approval"
                  ? "bg-amber-500/10 text-amber-400 border-amber-500/25"
                  : ["running", "pending"].includes(currentRun.status)
                  ? "bg-sky-500/10 text-sky-400 border-sky-500/20"
                  : "bg-rose-500/10 text-rose-400 border-rose-500/20"
              }`}
            >
              {currentRun.status.replace("_", " ").toUpperCase()}
            </span>
          </>
        )}
      </div>
    </header>
  );
}
