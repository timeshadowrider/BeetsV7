import { useState } from "react";
import { useBeetsLog, usePipelineLog } from "../api/hooks";
import LogViewer from "../components/LogViewer";

export default function Logs() {
  const [tab, setTab] = useState<"beets" | "pipeline">("beets");
  const beets = useBeetsLog();
  const pipeline = usePipelineLog();

  const text = tab === "beets" ? beets.data ?? "" : pipeline.data ?? "";

  return (
    <div className="space-y-4">
      <div className="bg-card rounded-xl p-3 border border-zinc-800 flex gap-2">
        <button
          onClick={() => setTab("beets")}
          className={`px-3 py-1 rounded-full text-xs ${
            tab === "beets"
              ? "bg-accent text-black"
              : "bg-zinc-800 text-gray-300"
          }`}
        >
          Beets Imports
        </button>
        <button
          onClick={() => setTab("pipeline")}
          className={`px-3 py-1 rounded-full text-xs ${
            tab === "pipeline"
              ? "bg-accent text-black"
              : "bg-zinc-800 text-gray-300"
          }`}
        >
          Pipeline Logs
        </button>
      </div>
      <LogViewer text={text} />
    </div>
  );
}
