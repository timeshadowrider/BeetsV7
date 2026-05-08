import { useState, useRef, useEffect } from "react";
import { api } from "../api/client";

type BuildResult = {
  status: string;
  playlist: string;
  matched: number;
  unmatched_count: number;
  total: number;
  volumio_errors: number;
  unmatched: string[];
  message?: string;
};

export default function VolumioBuilder() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  useEffect(() => {
    if (loading) {
      pollRef.current = setInterval(async () => {
        try {
          const { data } = await api.get("/ui/logs/volumio", {
            responseType: "text"
          });
          const lines: string[] = data
            .split("\n")
            .filter((l: string) => l.includes("[VOLUMIO]"))
            .slice(-100);
          if (lines.length > 0) setLogs(lines);
        } catch {
          // endpoint may not exist yet
        }
      }, 1000);
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [loading]);

  function addLog(msg: string) {
    const ts = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, `[${ts}] ${msg}`]);
  }

  async function handleUpload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setLogs([]);
    addLog(`Starting upload: ${file.name}`);
    addLog("Parsing CSV and searching Beets library...");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const { data } = await api.post(
        "/ui/volumio/playlist/upload",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      setResult(data);
      if (data.status === "ok") {
        addLog(`Done! Matched ${data.matched}/${data.total} tracks.`);
        addLog(`Playlist "${data.playlist}" pushed to Volumio.`);
        if (data.unmatched_count > 0) addLog(`${data.unmatched_count} tracks not found in library.`);
        if (data.volumio_errors > 0) addLog(`WARNING: ${data.volumio_errors} Volumio API errors.`);
      } else {
        addLog(`No matches found. ${data.message ?? ""}`);
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "Unknown error";
      setError(`Error: ${msg}`);
      addLog(`ERROR: ${msg}`);
    } finally {
      setLoading(false);
    }
  }

  function logColor(line: string) {
    if (line.includes("ERROR")) return "text-red-400";
    if (line.includes("WARNING") || line.includes("NO MATCH")) return "text-yellow-400";
    if (line.includes("MATCH") || line.includes("Done") || line.includes("pushed")) return "text-green-400";
    return "text-gray-400";
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-lg font-semibold text-gray-100">
        Volumio Playlist Builder (Spotify CSV)
      </h2>

      <div className="bg-card rounded-xl p-5 border border-zinc-800 space-y-4">
        <p className="text-sm text-gray-400">
          Export a playlist from Spotify using{" "}
          <a href="https://exportify.net" target="_blank" rel="noreferrer" className="text-accent underline">
            Exportify
          </a>
          , then upload the CSV here. Tracks will be matched against your Beets
          library and pushed to Volumio as a playlist.
        </p>

        <div className="flex items-center gap-3">
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
              setError(null);
              setLogs([]);
            }}
          />
          <button
            onClick={() => inputRef.current?.click()}
            className="px-3 py-1.5 bg-zinc-700 text-gray-200 text-sm rounded hover:bg-zinc-600 transition"
          >
            Choose File
          </button>
          <span className="text-sm text-gray-400 truncate">
            {file ? file.name : "No file chosen"}
          </span>
        </div>

        <button
          onClick={handleUpload}
          disabled={!file || loading}
          className="px-5 py-2 bg-accent text-black font-semibold text-sm rounded-lg
                     hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {loading ? "Building..." : "Upload & Build"}
        </button>

        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>

      {/* Live log panel */}
      {logs.length > 0 && (
        <div className="bg-black/80 rounded-xl border border-zinc-800 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-mono uppercase tracking-wide">Build Log</span>
            {loading && <span className="text-xs text-accent animate-pulse">Running...</span>}
          </div>
          <div
            ref={logRef}
            className="font-mono text-xs space-y-0.5 max-h-64 overflow-y-auto"
          >
            {logs.map((line, i) => (
              <div key={i} className={logColor(line)}>{line}</div>
            ))}
            {loading && <div className="text-gray-600 animate-pulse">...</div>}
          </div>
        </div>
      )}

      {/* Results summary */}
      {result && (
        <div className="bg-card rounded-xl p-5 border border-zinc-800 space-y-3">
          {result.status === "ok" ? (
            <>
              <p className="text-green-400 font-semibold text-sm">
                Playlist &quot;{result.playlist}&quot; sent to Volumio
              </p>
              <div className="text-sm text-gray-300 space-y-1">
                <div className="flex justify-between">
                  <span className="text-gray-400">Total tracks in CSV</span>
                  <span>{result.total}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Matched in library</span>
                  <span className="text-green-400">{result.matched}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Not found</span>
                  <span className={result.unmatched_count > 0 ? "text-yellow-400" : "text-gray-300"}>
                    {result.unmatched_count}
                  </span>
                </div>
                {result.volumio_errors > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-400">Volumio API errors</span>
                    <span className="text-red-400">{result.volumio_errors}</span>
                  </div>
                )}
              </div>
            </>
          ) : (
            <p className="text-yellow-400 text-sm">{result.message ?? "No tracks matched."}</p>
          )}

          {result.unmatched && result.unmatched.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1">
                Unmatched tracks{result.unmatched_count > 20 ? " (first 20)" : ""}:
              </p>
              <ul className="text-xs text-gray-500 space-y-0.5 max-h-40 overflow-y-auto">
                {result.unmatched.map((t, i) => (
                  <li key={i} className="truncate">{t}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
