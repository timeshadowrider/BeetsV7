import { useState } from "react";
import { runPipeline } from "../api/hooks";

export default function PipelineControl() {
  const [status, setStatus] = useState<string>("");

  const onRun = async () => {
    setStatus("Starting pipeline…");
    try {
      await runPipeline();
      setStatus("Pipeline started.");
    } catch (err: any) {
      setStatus(`Error: ${err?.message ?? "unknown"}`);
    }
  };

  return (
    <div className="max-w-lg space-y-4">
      <div className="bg-card rounded-xl p-4 border border-zinc-800 shadow-md">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">
          Pipeline Control
        </h3>
        <button
          onClick={onRun}
          className="px-4 py-2 rounded-lg bg-accent text-black text-sm font-semibold"
        >
          Run Pipeline
        </button>
        {status && (
          <div className="mt-3 text-xs text-gray-300">
            {status}
          </div>
        )}
      </div>
    </div>
  );
}
