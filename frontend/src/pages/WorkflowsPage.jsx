import { Clock, Play } from "lucide-react";

export default function WorkflowsPage({ workflows, onReplay }) {
  return (
    <div className="p-6 max-w-5xl w-full mx-auto grid grid-cols-1 md:grid-cols-2 gap-4">
      {workflows.length === 0 ? (
        <p className="text-xs text-zinc-500">
          No saved workflows yet. Complete a task in Workspace and save it.
        </p>
      ) : (
        workflows.map((wf) => (
          <div
            key={wf.id}
            className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.08] p-5 rounded-2xl flex flex-col justify-between gap-4"
          >
            <div>
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-zinc-100">
                  {wf.name}
                </h3>
                {wf.schedule_cron && (
                  <span className="text-[11px] px-2.5 py-0.5 rounded-full bg-violet-500/15 text-violet-300 border border-violet-500/25 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> {wf.schedule_cron}
                  </span>
                )}
              </div>
              <p className="text-xs text-zinc-400 mt-2">{wf.task_prompt}</p>
            </div>
            <button
              onClick={() => onReplay(wf.id)}
              className="self-start px-3.5 py-2 rounded-xl bg-violet-600/90 hover:bg-violet-500 text-white text-xs font-medium flex items-center gap-1.5 cursor-pointer"
            >
              <Play className="w-3.5 h-3.5" /> Replay Workflow
            </button>
          </div>
        ))
      )}
    </div>
  );
}