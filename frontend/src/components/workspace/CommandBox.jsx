import { Mic, MicOff, Play, RefreshCw, Sparkles, Square } from "lucide-react";
import { useVoiceInput } from "../../hooks/useVoiceInput";

const DEMO_PROMPTS = [
  "Open https://books.toscrape.com and extract the titles and prices of the first 5 books",
  "Open https://the-internet.herokuapp.com/login and log in with username tomsmith and password SuperSecretPassword!",
  "Open https://quotes.toscrape.com and extract the first 3 quotes and their authors",
];

export default function CommandBox({
  task,
  setTask,
  maxSteps,
  setMaxSteps,
  timeoutSec,
  setTimeoutSec,
  running,
  stopping,
  canStop,
  isIdle,
  onRunTask,
  onStop,
}) {
  const { isRecording, isPolishing, voiceError, toggleRecording } =
    useVoiceInput({
      onTranscriptChange: (text) => setTask(text),
    });

  return (
    <div
      className={`w-full transition-all ${
        isIdle ? "max-w-3xl mx-auto space-y-5" : ""
      }`}
    >
      {isIdle && (
        <div className="text-center space-y-2 mb-6">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-violet-500/10 border border-violet-500/20 text-violet-300 text-xs">
            <Sparkles className="w-3.5 h-3.5" /> Autonomous Web Agent
          </div>
          <h2 className="text-2xl font-semibold text-zinc-100 tracking-tight">
            What should the browser agent automate?
          </h2>
          <p className="text-xs text-zinc-400">
            Type a task or click the microphone to dictate in plain English.
          </p>
        </div>
      )}

      <form
        onSubmit={onRunTask}
        className="bg-white/[0.03] backdrop-blur-xl border border-white/[0.09] focus-within:border-violet-500/40 rounded-2xl p-4 shadow-xl transition"
      >
        <textarea
          rows={isIdle ? 3 : 2}
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onRunTask();
            }
          }}
          placeholder="Describe your web task (e.g., 'Open https://books.toscrape.com and extract the titles and prices of the first 5 books')..."
          className="w-full bg-transparent text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none resize-none"
        />

        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 mt-2 border-t border-white/[0.06]">
          <div className="flex items-center gap-2.5 text-[11px] text-zinc-400">
            <label className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/[0.03] border border-white/[0.07]">
              <span>Max Steps:</span>
              <input
                type="number"
                min={1}
                max={50}
                value={maxSteps}
                onChange={(e) => setMaxSteps(e.target.value)}
                className="w-10 bg-transparent text-zinc-200 focus:outline-none text-center"
              />
            </label>
            <label className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-white/[0.03] border border-white/[0.07]">
              <span>Timeout:</span>
              <input
                type="number"
                min={10}
                max={900}
                value={timeoutSec}
                onChange={(e) => setTimeoutSec(e.target.value)}
                className="w-12 bg-transparent text-zinc-200 focus:outline-none text-center"
              />
              <span>s</span>
            </label>
            {isPolishing && (
              <span className="text-violet-400 animate-pulse">
                Refining voice transcript...
              </span>
            )}
            {voiceError && <span className="text-rose-400">{voiceError}</span>}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggleRecording}
              title={
                isRecording
                  ? "Stop voice recording"
                  : "Dictate prompt by voice"
              }
              className={`p-2.5 rounded-xl border transition cursor-pointer ${
                isRecording
                  ? "bg-rose-500/20 border-rose-500/50 text-rose-300 animate-pulse"
                  : "bg-white/[0.04] hover:bg-white/[0.08] border-white/[0.08] text-zinc-300"
              }`}
            >
              {isRecording ? (
                <MicOff className="w-4 h-4" />
              ) : (
                <Mic className="w-4 h-4" />
              )}
            </button>

            {running ? (
              <button
                type="button"
                onClick={onStop}
                disabled={!canStop || stopping}
                className="px-4 py-2 rounded-xl bg-rose-600/90 hover:bg-rose-500 text-white text-xs font-medium flex items-center gap-1.5 transition cursor-pointer disabled:opacity-50"
              >
                {stopping ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5 fill-current" />}
                {stopping ? "Stopping..." : "Stop Run"}
              </button>
            ) : (
              <button
                type="submit"
                disabled={!task.trim()}
                className="px-4 py-2 rounded-xl bg-violet-600/90 hover:bg-violet-500 text-white text-xs font-medium flex items-center gap-1.5 transition cursor-pointer disabled:opacity-40"
              >
                <>
                  <Play className="w-3.5 h-3.5" /> Execute Run
                </>
              </button>
            )}
          </div>
        </div>
      </form>

      {isIdle && (
        <div className="flex flex-wrap justify-center gap-2">
          {DEMO_PROMPTS.map((sample, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setTask(sample)}
              className="text-left text-[11px] px-3 py-1.5 rounded-full bg-white/[0.03] hover:bg-violet-500/10 border border-white/[0.07] hover:border-violet-500/30 text-zinc-400 hover:text-zinc-200 transition cursor-pointer truncate max-w-xs"
            >
              {sample}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
