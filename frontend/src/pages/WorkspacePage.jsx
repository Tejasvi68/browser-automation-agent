import { useEffect, useState } from "react";
import CommandBox from "../components/workspace/CommandBox";
import ApprovalBanner from "../components/workspace/ApprovalBanner";
import BrowserViewport from "../components/workspace/BrowserViewport";
import StepTimeline from "../components/workspace/StepTimeline";
import RunResultCard from "../components/workspace/RunResultCard";

export default function WorkspacePage({
  task,
  setTask,
  maxSteps,
  setMaxSteps,
  timeoutSec,
  setTimeoutSec,
  running,
  stopping,
  currentRun,
  runError,
  onRunTask,
  onStop,
  onApproval,
  onExport,
  onSaveWorkflow,
}) {
  const [selectedStepIdx, setSelectedStepIdx] = useState(0);
  const steps = currentRun?.steps_history || [];

  useEffect(() => {
    setSelectedStepIdx(0);
  }, [currentRun?.run_id]);

  const isIdle = !currentRun && !running;

  return (
    <div
      className={`flex-1 p-6 max-w-[1440px] w-full mx-auto flex flex-col ${
        isIdle ? "justify-center" : "gap-5"
      }`}
    >
      <CommandBox
        task={task}
        setTask={setTask}
        maxSteps={maxSteps}
        setMaxSteps={setMaxSteps}
        timeoutSec={timeoutSec}
        setTimeoutSec={setTimeoutSec}
        running={running}
        stopping={stopping}
        canStop={Boolean(currentRun?.run_id)}
        isIdle={isIdle}
        onRunTask={onRunTask}
        onStop={onStop}
      />

      {runError && (
        <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/25 text-xs text-rose-300">
          {runError}
        </div>
      )}

      <ApprovalBanner
        run={currentRun}
        running={running}
        onDecision={onApproval}
      />

      {currentRun && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-stretch">
            <div className="lg:col-span-8 flex">
              <BrowserViewport
                steps={steps}
                activeStepIndex={selectedStepIdx}
                onSelectStep={setSelectedStepIdx}
                isRunning={running}
              />
            </div>
            <div className="lg:col-span-4 flex">
              <StepTimeline
                steps={steps}
                selectedIdx={selectedStepIdx}
                onSelect={setSelectedStepIdx}
                activeStepIndex={selectedStepIdx}
                onSelectStep={setSelectedStepIdx}
              />
            </div>
          </div>

          <RunResultCard
            run={currentRun}
            onExport={onExport}
            onSaveWorkflow={onSaveWorkflow}
          />
        </>
      )}
    </div>
  );
}
