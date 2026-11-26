import {
  Bot,
  FolderKanban,
  KeyRound,
  LayoutGrid,
  LogOut,
  Plus,
  Trash2,
} from "lucide-react";
import { useState } from "react";

export default function Sidebar({
  user,
  activePage,
  onNavigate,
  onNewTask,
  onLogout,
  workflowsCount,
  credentialsCount,
  history,
  currentRunId,
  onSelectRun,
  onDeleteRun,
}) {
  const [deletingRunId, setDeletingRunId] = useState(null);
  const [deleteError, setDeleteError] = useState("");

  const handleDeleteRun = async (runId) => {
    setDeletingRunId(runId);
    setDeleteError("");
    try {
      await onDeleteRun(runId);
    } catch (error) {
      setDeleteError(error.response?.data?.detail || "Could not delete this run.");
    } finally {
      setDeletingRunId(null);
    }
  };

  const navItems = [
    { id: "workspace", label: "Workspace", icon: LayoutGrid },
    {
      id: "workflows",
      label: "Saved Workflows",
      icon: FolderKanban,
      count: workflowsCount,
    },
    {
      id: "vault",
      label: "Credential Vault",
      icon: KeyRound,
      count: credentialsCount,
    },
  ];

  return (
    <aside className="w-60 h-screen shrink-0 bg-white/[0.02] backdrop-blur-2xl border-r border-white/[0.07] flex flex-col justify-between p-4">
      <div className="flex flex-1 min-h-0 flex-col space-y-5 overflow-hidden">
        {/* Brand Header */}
        <div className="flex items-center gap-2.5 px-1">
          <div className="w-8 h-8 rounded-lg bg-violet-500/15 border border-violet-500/30 flex items-center justify-center text-violet-400">
            <Bot className="w-4 h-4" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight text-zinc-100">
              AURA
            </div>
            <div className="text-[10px] text-zinc-500">Browser Automation</div>
          </div>
        </div>

        {/* New Task CTA */}
        <button
          onClick={onNewTask}
          className="w-full py-2 px-3 rounded-xl bg-violet-600/90 hover:bg-violet-500 text-white text-xs font-medium flex items-center justify-center gap-1.5 transition cursor-pointer shadow-sm"
        >
          <Plus className="w-3.5 h-3.5" /> New Task
        </button>

        {/* Primary Navigation */}
        <nav className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activePage === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onNavigate(item.id)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-medium transition cursor-pointer ${
                  isActive
                    ? "bg-violet-500/15 text-violet-300 border border-violet-500/25"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04]"
                }`}
              >
                <span className="flex items-center gap-2.5">
                  <Icon className="w-3.5 h-3.5" />
                  {item.label}
                </span>
                {typeof item.count === "number" && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-white/[0.05] text-zinc-400">
                    {item.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Recent Runs Feed */}
        <div className="flex flex-1 min-h-0 flex-col pt-3 border-t border-white/[0.06]">
          <div className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Recent Runs
          </div>
          {deleteError && <p className="px-2 pb-2 text-[10px] text-rose-300">{deleteError}</p>}
          <div className="flex-1 min-h-0 space-y-1 overflow-y-auto pr-1">
            {history.length === 0 ? (
              <p className="px-2 text-[11px] text-zinc-600">No runs yet</p>
            ) : (
              history.map((run) => (
                <div
                  key={run.run_id}
                  className={`group w-full rounded-lg transition flex items-center gap-1 ${
                    currentRunId === run.run_id
                      ? "bg-white/[0.07] text-zinc-100"
                      : "text-zinc-400 hover:bg-white/[0.03] hover:text-zinc-200"
                  }`}
                >
                  <button
                    onClick={() => onSelectRun(run)}
                    className="min-w-0 flex-1 text-left px-2.5 py-2 text-xs cursor-pointer flex items-start gap-2"
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                        run.status === "completed"
                          ? "bg-emerald-400"
                          : run.status === "awaiting_approval"
                          ? "bg-amber-400"
                          : run.status === "running"
                          ? "bg-sky-400"
                          : "bg-rose-400"
                      }`}
                    />
                    <span className="truncate">{run.task}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteRun(run.run_id)}
                    disabled={deletingRunId === run.run_id || ["running", "awaiting_approval"].includes(run.status)}
                    title={["running", "awaiting_approval"].includes(run.status) ? "Active runs cannot be deleted" : "Delete run"}
                    aria-label={`Delete run: ${run.task}`}
                    className="mr-1 p-1.5 rounded-md text-zinc-500 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-rose-300 hover:bg-rose-500/10 transition disabled:cursor-not-allowed disabled:opacity-30 cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Bottom User Profile */}
      <div className="pt-3 border-t border-white/[0.07] flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-medium text-zinc-200 truncate">
            {user.email}
          </div>
          <div className="text-[10px] text-zinc-500">
            Firebase Auth
          </div>
        </div>
        <button
          onClick={onLogout}
          title="Logout"
          className="p-2 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-white/[0.06] transition cursor-pointer"
        >
          <LogOut className="w-3.5 h-3.5" />
        </button>
      </div>
    </aside>
  );
}
