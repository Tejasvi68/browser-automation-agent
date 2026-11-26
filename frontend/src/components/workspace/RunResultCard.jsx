import { useState } from "react";
import { Download, Save, Sparkles } from "lucide-react";

function formatSummaryLine(line, index) {
  const numbered = line.match(/^\s*(\d+)\.\s+(.*)$/);
  const content = numbered ? numbered[2] : line;
  const parts = content.split(/(\*\*.*?\*\*)/g).filter(Boolean);
  const formatted = parts.map((part, partIndex) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={partIndex} className="font-semibold text-white">{part.slice(2, -2)}</strong>
    ) : part
  );

  if (numbered) {
    return (
      <div key={index} className="flex gap-3 rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-violet-500/15 text-xs font-semibold text-violet-300">
          {numbered[1]}
        </span>
        <p className="min-w-0 flex-1">{formatted}</p>
      </div>
    );
  }

  return line.trim() ? <p key={index}>{formatted}</p> : <div key={index} className="h-1" />;
}

export default function RunResultCard({ run, onExport, onSaveWorkflow }) {
  const [wfName, setWfName] = useState("");
  const [wfCron, setWfCron] = useState("");
  const [wfMsg, setWfMsg] = useState("");

  const handleSave = async (e) => {
    e.preventDefault();
    if (!wfName.trim()) return;
    const msg = await onSaveWorkflow({
      run_id: run.run_id,
      name: wfName,
      schedule_cron: wfCron.trim() || null,
    });
    setWfMsg(msg);
    setWfName("");
    setWfCron("");
  };

  return (
    <div className="bg-white/[0.025] backdrop-blur-xl border border-white/[0.08] rounded-2xl p-5 md:p-6 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3 max-w-4xl min-w-0">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-violet-300">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Result Summary</span>
          </div>
          <div className="space-y-2 text-sm md:text-[15px] leading-7 text-zinc-300 break-words">
            {(run.final_summary || "The run completed without a summary.")
              .split("\n")
              .map(formatSummaryLine)}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onExport(run.run_id, "json")}
            className="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 text-xs text-zinc-200 flex items-center gap-1.5 cursor-pointer"
          >
            <Download className="w-3.5 h-3.5 text-violet-400" /> JSON
          </button>
          <button
            onClick={() => onExport(run.run_id, "csv")}
            className="px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 text-xs text-zinc-200 flex items-center gap-1.5 cursor-pointer"
          >
            <Download className="w-3.5 h-3.5 text-violet-400" /> CSV
          </button>
        </div>
      </div>

      {run.status === "completed" && (
        <form
          onSubmit={handleSave}
          className="pt-4 border-t border-white/[0.07] flex flex-wrap items-center gap-3"
        >
          <input
            type="text"
            required
            value={wfName}
            onChange={(e) => setWfName(e.target.value)}
            placeholder="Save as reusable workflow name..."
            className="px-3 py-1.5 bg-black/40 border border-white/10 rounded-xl text-xs text-zinc-100 flex-1 min-w-[200px] focus:outline-none focus:border-violet-500/50"
          />
          <input
            type="text"
            value={wfCron}
            onChange={(e) => setWfCron(e.target.value)}
            placeholder="Optional Cron (e.g. 0 9 * * *)"
            className="px-3 py-1.5 bg-black/40 border border-white/10 rounded-xl text-xs text-zinc-100 w-48 focus:outline-none focus:border-violet-500/50"
          />
          <button
            type="submit"
            className="px-3.5 py-1.5 rounded-xl bg-violet-600/80 hover:bg-violet-500 text-white text-xs font-medium flex items-center gap-1.5 cursor-pointer"
          >
            <Save className="w-3.5 h-3.5" /> Save Workflow
          </button>
          {wfMsg && <span className="text-xs text-emerald-400">{wfMsg}</span>}
        </form>
      )}
    </div>
  );
}
