import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";

export default function ApprovalBanner({ run, running, onDecision }) {
  if (run?.status !== "awaiting_approval") return null;

  return (
    <div className="p-4 rounded-2xl bg-violet-950/30 backdrop-blur-xl border border-violet-500/35 flex flex-wrap items-center justify-between gap-4">
      <div className="flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
        <div>
          <div className="text-xs font-semibold text-zinc-100">
            HUMAN APPROVAL REQUIRED
          </div>
          <p className="text-xs text-zinc-300 mt-0.5">{run.final_summary}</p>
          {run.pending_approval?.proposed_action && (
            <code className="inline-block mt-1.5 text-[11px] px-2.5 py-1 rounded bg-black/50 text-violet-300 font-mono">
              {run.pending_approval.proposed_action.action} →{" "}
              {JSON.stringify(run.pending_approval.proposed_action.params)}
            </code>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => onDecision(true)}
          disabled={running}
          className="px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium flex items-center gap-1.5 cursor-pointer"
        >
          <CheckCircle2 className="w-3.5 h-3.5" /> Approve Step
        </button>
        <button
          onClick={() => onDecision(false)}
          disabled={running}
          className="px-3.5 py-2 rounded-xl bg-white/[0.06] hover:bg-rose-500/20 border border-white/10 text-zinc-200 text-xs font-medium flex items-center gap-1.5 cursor-pointer"
        >
          <XCircle className="w-3.5 h-3.5" /> Reject
        </button>
      </div>
    </div>
  );
}