import { useEffect, useRef, useState } from "react";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { auth } from "./firebase";
import api from "./api/client";
import Sidebar from "./components/layout/Sidebar";
import TopHeader from "./components/layout/TopHeader";
import AuthPage from "./pages/AuthPage";
import WorkspacePage from "./pages/WorkspacePage";
import WorkflowsPage from "./pages/WorkflowsPage";
import VaultPage from "./pages/VaultPage";

export default function App() {
  const [user, setUser] = useState(null);
  const [activePage, setActivePage] = useState("workspace");

  const [task, setTask] = useState("");
  const [maxSteps, setMaxSteps] = useState(12);
  const [timeoutSec, setTimeoutSec] = useState(180);
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const stopRequestedRunId = useRef(null);
  const [currentRun, setCurrentRun] = useState(null);
  const [runError, setRunError] = useState("");

  const [history, setHistory] = useState([]);
  const [workflows, setWorkflows] = useState([]);
  const [credentials, setCredentials] = useState([]);

  useEffect(() => {
    if (!auth) return;
    const unsub = onAuthStateChanged(auth, (fbUser) => {
      if (fbUser) {
        setUser({ uid: fbUser.uid, email: fbUser.email });
      } else {
        setUser(null);
      }
    });
    return () => unsub();
  }, []);

  useEffect(() => {
    if (user) refreshAll();
  }, [user]);

  const refreshAll = async () => {
    try {
      const [runsRes, wfRes, credRes] = await Promise.all([
        api.get("/runs"),
        api.get("/workflows"),
        api.get("/vault/credentials"),
      ]);
      setHistory(runsRes.data);
      setWorkflows(wfRes.data);
      setCredentials(credRes.data);
    } catch {
      // Backend starting up
    }
  };

  const handleLogout = async () => {
    if (auth?.currentUser) await signOut(auth);
    setUser(null);
  };

  const handleNewTask = () => {
    setActivePage("workspace");
    setCurrentRun(null);
    setTask("");
    setRunError("");
  };

  const handleRunTask = async (e) => {
    e?.preventDefault();
    if (!task.trim() || running) return;
    setRunning(true);
    setStopping(false);
    setRunError("");
    try {
      const res = await api.post("/run", {
        task,
        max_steps: Number(maxSteps),
        timeout_seconds: Number(timeoutSec),
      });
      const initialRun = res.data;
      setCurrentRun(initialRun);

      // Poll live every 1s while status is "running" so screenshots & steps stream in real time
      if (initialRun.status === "running" && initialRun.run_id) {
        await new Promise((resolve) => {
          const pollTimer = setInterval(async () => {
            try {
              const statusRes = await api.get(`/runs/${initialRun.run_id}`);
              const updated = statusRes.data;
              setCurrentRun(updated);
              if (updated.status !== "running") {
                clearInterval(pollTimer);
                resolve();
              }
            } catch {
              clearInterval(pollTimer);
              resolve();
            }
          }, 1000);
        });
      }

      await refreshAll();
    } catch (err) {
      setRunError(err.response?.data?.detail || err.message);
    } finally {
      setRunning(false);
    }
  };

  const handleStopTask = async () => {
    const runId = currentRun?.run_id;
    if (!runId || stopping) return;
    stopRequestedRunId.current = runId;
    setStopping(true);
    setRunError("");
    try {
      const res = await api.post(`/runs/${runId}/stop`);
      setCurrentRun(res.data);
      await refreshAll();
    } catch (err) {
      setRunError(err.response?.data?.detail || err.message);
    } finally {
      stopRequestedRunId.current = null;
      setStopping(false);
      setRunning(false);
    }
  };

  const handleApproval = async (approved) => {
    if (!currentRun || running) return;
    setRunning(true);
    setRunError("");
    const runId = currentRun.run_id;
    setCurrentRun((run) => run ? {
      ...run,
      status: approved ? "running" : run.status,
      final_summary: approved ? "Approval received. Automation is continuing." : run.final_summary,
    } : run);

    let keepPolling = approved;
    const pollRun = async () => {
      while (keepPolling) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        try {
          const statusRes = await api.get(`/runs/${runId}`);
          const updated = statusRes.data;
          setCurrentRun((run) => run?.run_id === runId ? { ...run, ...updated } : run);
          if (updated.status !== "running") keepPolling = false;
        } catch {
          keepPolling = false;
        }
      }
    };

    let pollRequest;
    try {
      const approvalRequest = api.post(`/runs/${runId}/approve`, { approved });
      pollRequest = pollRun();
      const res = await approvalRequest;
      keepPolling = false;
      await pollRequest;
      setCurrentRun(res.data);
      await refreshAll();
    } catch (err) {
      keepPolling = false;
      await pollRequest;
      if (stopRequestedRunId.current !== runId) {
        setRunError(err.response?.data?.detail || err.message);
      }
    } finally {
      setRunning(false);
    }
  };

  const handleExport = async (runId, format) => {
    const res = await api.get(`/runs/${runId}/export?format=${format}`, {
      responseType: "blob",
    });
    const url = window.URL.createObjectURL(new Blob([res.data]));
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `run_${runId}.${format}`);
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const handleDeleteRun = async (runId) => {
    await api.delete(`/runs/${runId}`);
    setHistory((runs) => runs.filter((run) => run.run_id !== runId));
    if (currentRun?.run_id === runId) {
      setCurrentRun(null);
      setTask("");
      setRunError("");
    }
  };

  const handleSaveWorkflow = async (payload) => {
    try {
      await api.post("/workflows", payload);
      await refreshAll();
      return "Saved!";
    } catch (err) {
      return err.response?.data?.detail || "Error saving";
    }
  };

  const handleReplayWorkflow = async (workflowId) => {
    setActivePage("workspace");
    setRunning(true);
    setRunError("");
    try {
      const res = await api.post(`/workflows/${workflowId}/replay`);
      setCurrentRun(res.data);
      setTask(res.data.task || "");
      await refreshAll();
    } catch (err) {
      setRunError(err.response?.data?.detail || err.message);
    } finally {
      setRunning(false);
    }
  };

  const handleAddCredential = async (form) => {
    await api.post("/vault/credentials", form);
    await refreshAll();
  };

  const handleLoadCredential = async (id) => (await api.get(`/vault/credentials/${id}`)).data;

  const handleUpdateCredential = async (id, form) => {
    await api.put(`/vault/credentials/${id}`, form);
    await refreshAll();
  };

  const handleDeleteCredential = async (id) => {
    await api.delete(`/vault/credentials/${id}`);
    await refreshAll();
  };

  if (!user) {
    return <AuthPage />;
  }

  return (
    <div className="h-screen bg-[#08080c] text-zinc-100 flex overflow-hidden selection:bg-violet-500/30">
      <Sidebar
        user={user}
        activePage={activePage}
        onNavigate={setActivePage}
        onNewTask={handleNewTask}
        onLogout={handleLogout}
        workflowsCount={workflows.length}
        credentialsCount={credentials.length}
        history={history}
        currentRunId={currentRun?.run_id}
        onDeleteRun={handleDeleteRun}
        onSelectRun={(run) => {
          setCurrentRun(run);
          setTask(run.task);
          setActivePage("workspace");
        }}
      />

      <main className="flex-1 flex flex-col overflow-y-auto relative">
        <TopHeader activePage={activePage} currentRun={currentRun} />

        {activePage === "workspace" && (
          <WorkspacePage
            task={task}
            setTask={setTask}
            maxSteps={maxSteps}
            setMaxSteps={setMaxSteps}
            timeoutSec={timeoutSec}
            setTimeoutSec={setTimeoutSec}
            running={running}
            stopping={stopping}
            currentRun={currentRun}
            runError={runError}
            onRunTask={handleRunTask}
            onStop={handleStopTask}
            onApproval={handleApproval}
            onExport={handleExport}
            onSaveWorkflow={handleSaveWorkflow}
          />
        )}

        {activePage === "workflows" && (
          <WorkflowsPage
            workflows={workflows}
            onReplay={handleReplayWorkflow}
          />
        )}

        {activePage === "vault" && (
          <VaultPage
            credentials={credentials}
            onAddCredential={handleAddCredential}
            onLoadCredential={handleLoadCredential}
            onUpdateCredential={handleUpdateCredential}
            onDeleteCredential={handleDeleteCredential}
          />
        )}
      </main>
    </div>
  );
}                                                                                                      
