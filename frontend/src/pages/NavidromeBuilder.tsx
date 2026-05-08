import { useState, useRef, useEffect } from "react";
import { api } from "../api/client";

type BuildResult = {
  status: string;
  playlist: string;
  matched: number;
  unmatched_count: number;
  total: number;
  unmatched: string[];
  output_path?: string;
  message?: string;
};

export default function NavidromeBuilder() {
  const [file, setFile] = useState<File | null>(null);
  const [playlistName, setPlaylistName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-scroll log panel
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  // Live-poll the navidrome log file while building, just like VolumioBuilder
  useEffect(() => {
    if (loading) {
      pollRef.current = setInterval(async () => {
        try {
          const { data } = await api.get("/ui/navidrome/logs", {
            responseType: "text",
          });
          const lines: string[] = (data as string)
            .split("\n")
            .filter((l) => l.includes("[NAVIDROME]"))
            .slice(-100);
          if (lines.length > 0) setLogs(lines);
        } catch {
          return; // swallow harmless empty responses        
        }
      }, 2500);
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

  function handleFileChange(f: File | null) {
    setFile(f);
    setResult(null);
    setError(null);
    setLogs([]);
    if (f && !playlistName) {
      setPlaylistName(
        f.name
          .replace(/\.csv$/i, "")
          .replace(/[_-]/g, " ")
          .trim(),
      );
    }
  }

  async function handleBuild() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setLogs([`Starting upload: ${file.name}`, "Matching tracks against Beets library..."]);

    const formData = new FormData();
    formData.append("file", file);
    if (playlistName.trim()) formData.append("playlist_name", playlistName.trim());

    try {
      const { data } = await api.post(
        "/ui/navidrome/playlist/upload",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setResult(data);
      if (data.status === "ok") {
        setLogs((prev) => [
          ...prev,
          `Matched ${data.matched}/${data.total} tracks.`,
          `M3U written to: ${data.output_path}`,
          ...(data.unmatched_count > 0
            ? [`${data.unmatched_count} tracks not found in library.`]
            : []),
          "=== Done ===",
        ]);
      } else {
        setLogs((prev) => [
          ...prev,
          `No matches found. ${data.message ?? ""}`,
        ]);
      }
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail || err?.message || "Unknown error";
      setError(`Error: ${msg}`);
      setLogs((prev) => [...prev, `ERROR: ${msg}`]);
    } finally {
      setLoading(false);
    }
  }

  async function handleDownload() {
    if (!result?.playlist) return;
    try {
      const { data } = await api.get(
        `/ui/navidrome/playlist/download/${encodeURIComponent(result.playlist)}`,
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(
        new Blob([data], { type: "audio/x-mpegurl" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `${result.playlist}.m3u`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Download failed.");
    }
  }

  function logColor(line: string) {
    if (line.includes("ERROR")) return "text-red-400";
    if (line.includes("WARNING") || line.includes("NO MATCH"))
      return "text-yellow-400";
    if (
      line.includes("MATCH") ||
      line.includes("written") ||
      line.includes("Done") ||
      line.includes("Matched")
    )
      return "text-green-400";
    return "text-gray-400";
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-lg font-semibold text-gray-100">
        Navidrome Playlist Builder (Spotify CSV)
      </h2>

      <div className="bg-card rounded-xl p-5 border border-zinc-800 space-y-4">
        <p className="text-sm text-gray-400">
          Export a playlist from Spotify using{" "}
          <a
            href="https://exportify.net"
            target="_blank"
            rel="noreferrer"
            className="text-accent underline"
          >
            Exportify
          </a>
          , then upload the CSV here. Tracks will be matched against your Beets
          library and saved as an M3U in your Navidrome playlist folder.
          Navidrome will auto-import it within 5 minutes.
        </p>

        {/* Playlist name */}
        <div className="space-y-1">
          <label className="text-xs text-gray-500 uppercase tracking-wide">
            Playlist name
          </label>
          <input
            type="text"
            value={playlistName}
            onChange={(e) => setPlaylistName(e.target.value)}
            placeholder="My Playlist"
            className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5
                       text-sm text-gray-200 placeholder-gray-600 focus:outline-none
                       focus:border-accent transition"
          />
        </div>

        {/* File picker */}
        <div className="flex items-center gap-3">
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
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
          onClick={handleBuild}
          disabled={!file || loading}
          className="px-5 py-2 bg-accent text-black font-semibold text-sm rounded-lg
                     hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition"
        >
          {loading ? "Building..." : "Upload & Build M3U"}
        </button>

        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>

      {/* Live log panel */}
      {logs.length > 0 && (
        <div className="bg-black/80 rounded-xl border border-zinc-800 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-mono uppercase tracking-wide">
              Build Log
            </span>
            {loading && (
              <span className="text-xs text-accent animate-pulse">
                Running...
              </span>
            )}
          </div>
          <div
            ref={logRef}
            className="font-mono text-xs space-y-0.5 max-h-64 overflow-y-auto"
          >
            {logs.map((line, i) => (
              <div key={i} className={logColor(line)}>
                {line}
              </div>
            ))}
            {loading && (
              <div className="text-gray-600 animate-pulse">...</div>
            )}
          </div>
        </div>
      )}

      {/* Results summary */}
      {result && (
        <div className="bg-card rounded-xl p-5 border border-zinc-800 space-y-3">
          {result.status === "ok" ? (
            <>
              <div className="flex items-center justify-between">
                <p className="text-green-400 font-semibold text-sm">
                  &quot;{result.playlist}&quot; saved
                </p>
                <button
                  onClick={handleDownload}
                  className="text-xs px-3 py-1 bg-zinc-700 hover:bg-zinc-600
                             text-gray-200 rounded transition"
                >
                  Download .m3u
                </button>
              </div>

              {result.output_path && (
                <p className="text-xs text-gray-500 font-mono truncate">
                  {result.output_path}
                </p>
              )}

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
                  <span
                    className={
                      result.unmatched_count > 0
                        ? "text-yellow-400"
                        : "text-gray-300"
                    }
                  >
                    {result.unmatched_count}
                  </span>
                </div>
              </div>

              <p className="text-xs text-gray-500">
                Navidrome scans every 5 minutes — your playlist will appear
                shortly.
              </p>
            </>
          ) : (
            <p className="text-yellow-400 text-sm">
              {result.message ?? "No tracks matched."}
            </p>
          )}

          {result.unmatched && result.unmatched.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-1">
                Unmatched tracks
                {result.unmatched_count > 20 ? " (first 20)" : ""}:
              </p>
              <ul className="text-xs text-gray-500 space-y-0.5 max-h-40 overflow-y-auto">
                {result.unmatched.map((t, i) => (
                  <li key={i} className="truncate">
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
