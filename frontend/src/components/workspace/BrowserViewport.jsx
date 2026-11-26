import React, { useState, useEffect, useRef } from "react";
import { ChevronLeft, ChevronRight, Play, Pause, Globe } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

function resolveScreenshotUrl(step) {
  if (!step || typeof step !== "object") return null;
  if (step.screenshot_base64) {
    return `data:image/png;base64,${step.screenshot_base64}`;
  }
  if (typeof step.screenshot_url === "string" && step.screenshot_url) {
    return step.screenshot_url.startsWith("http")
      ? step.screenshot_url
      : `${API_BASE}${step.screenshot_url.startsWith("/") ? "" : "/"}${step.screenshot_url}`;
  }
  if (typeof step.screenshot_path === "string" && step.screenshot_path) {
    const normalized = step.screenshot_path.replace(/\\/g, "/");
    const idx = normalized.indexOf("artifacts/");
    const relPath = idx !== -1 ? `/${normalized.slice(idx)}` : `/${normalized.replace(/^\.?\//, "")}`;
    return `${API_BASE}${relPath}`;
  }
  return null;
}

export default function BrowserViewport({ steps = [], activeStepIndex = 0, onSelectStep, isRunning = false }) {
  const safeSteps = Array.isArray(steps) ? steps : [];
  const numericIndex = Number.isFinite(Number(activeStepIndex)) ? Number(activeStepIndex) : 0;
  const safeIndex = Math.max(0, Math.min(numericIndex, Math.max(0, safeSteps.length - 1)));

  const [isPlaying, setIsPlaying] = useState(false);
  const indexRef = useRef(safeIndex);
  indexRef.current = safeIndex;

  const selectStepSafely = (idx) => {
    if (typeof onSelectStep === "function") {
      onSelectStep(idx);
    }
  };

  // Auto-play replay slideshow when a multi-step run finishes
  useEffect(() => {
    if (safeSteps.length === 0) return;
    if (isRunning) {
      setIsPlaying(false);
      selectStepSafely(safeSteps.length - 1);
    } else {
      selectStepSafely(0);
      if (safeSteps.length > 1) setIsPlaying(true);
    }
  }, [isRunning, safeSteps.length]);

  useEffect(() => {
    if (!isPlaying || safeSteps.length <= 1) return;
    const timer = setInterval(() => {
      const next = indexRef.current + 1;
      if (next >= safeSteps.length) {
        setIsPlaying(false);
      } else {
        selectStepSafely(next);
      }
    }, 1400);
    return () => clearInterval(timer);
  }, [isPlaying, safeSteps.length]);

  const currentStep = safeSteps[safeIndex] || null;
  const screenshotSrc = resolveScreenshotUrl(currentStep);

  return (
    <div className="flex flex-col flex-1 w-full min-w-0 min-h-[460px] rounded-2xl bg-[#111116]/90 border border-white/10 overflow-hidden">
      {/* Top Browser Chrome Bar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#18181F] border-b border-white/10">
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="w-2.5 h-2.5 rounded-full bg-rose-500/80" />
          <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
        </div>
        <div className="flex items-center gap-2 px-3 py-1 rounded-lg bg-black/40 border border-white/5 text-xs text-zinc-400 max-w-md truncate mx-3">
          <Globe className="w-3.5 h-3.5 text-violet-400 shrink-0" />
          <span className="truncate">{currentStep?.url || "about:blank"}</span>
        </div>
        <span className="text-xs text-zinc-400 font-medium shrink-0">
          {safeSteps.length > 0 ? `Step ${safeIndex + 1} of ${safeSteps.length}` : "Idle"}
        </span>
      </div>

      {/* Screenshot Viewport */}
      <div className="relative flex-1 flex items-center justify-center bg-[#09090D] overflow-hidden min-h-[360px]">
        {screenshotSrc ? (
          <img
            src={screenshotSrc}
            alt={`Step ${safeIndex + 1}`}
            className="w-full h-full object-contain transition-opacity duration-300"
          />
        ) : (
          <p className="text-sm text-zinc-500">
            {isRunning ? "Executing browser steps in headless Chromium..." : "No browser frame captured yet."}
          </p>
        )}
      </div>

      {/* Bottom Replay Scrubber & Play/Pause Controls */}
      {safeSteps.length > 0 && (
        <div className="flex items-center gap-3 px-4 py-2.5 bg-[#18181F] border-t border-white/10">
          <button
            type="button"
            onClick={() => {
              if (safeIndex >= safeSteps.length - 1) selectStepSafely(0);
              setIsPlaying((p) => !p);
            }}
            className="p-1.5 rounded-lg bg-violet-600/20 text-violet-300 hover:bg-violet-600/30 transition shrink-0"
            title={isPlaying ? "Pause Replay" : "Auto-Play Replay"}
          >
            {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
          </button>
          <button
            type="button"
            disabled={safeIndex === 0}
            onClick={() => {
              setIsPlaying(false);
              selectStepSafely(Math.max(0, safeIndex - 1));
            }}
            className="p-1 rounded hover:bg-white/10 disabled:opacity-30 text-zinc-300 shrink-0"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <input
            type="range"
            min={0}
            max={Math.max(0, safeSteps.length - 1)}
            value={safeIndex}
            onChange={(e) => {
              setIsPlaying(false);
              selectStepSafely(Number(e.target.value));
            }}
            className="flex-1 accent-violet-500 cursor-pointer"
          />
          <button
            type="button"
            disabled={safeIndex >= safeSteps.length - 1}
            onClick={() => {
              setIsPlaying(false);
              selectStepSafely(Math.min(safeSteps.length - 1, safeIndex + 1));
            }}
            className="p-1 rounded hover:bg-white/10 disabled:opacity-30 text-zinc-300 shrink-0"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <span className="text-xs font-mono text-violet-300 min-w-[72px] text-right shrink-0">
            {currentStep?.action || ""}
          </span>
        </div>
      )}
    </div>
  );
}