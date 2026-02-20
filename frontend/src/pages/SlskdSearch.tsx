import { useState, useRef, useEffect } from "react";
import { api } from "../api/client";

// ── Types ─────────────────────────────────────────────────────────────────────
type TrackStatus = "idle" | "searching" | "found" | "queued" | "missing";
type SearchMode  = "tracks" | "albums";
type FilterTab   = "all" | "found" | "queued" | "missing";

type TrackMatch = {
  filename: string;
  size: number;
  username: string;
  quality: number;
};

type TrackResult = {
  idx: number;
  title: string;
  artist: string;
  album: string;
  status: TrackStatus;
  matches: TrackMatch[];
};

// ── CSV helpers ───────────────────────────────────────────────────────────────
function parseCSVLine(line: string): string[] {
  const result: string[] = [];
  let inQuote = false, cur = "";
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') { inQuote = !inQuote; continue; }
    if (ch === "," && !inQuote) { result.push(cur); cur = ""; continue; }
    cur += ch;
  }
  result.push(cur);
  return result;
}

function parseCSV(text: string): Record<string, string>[] {
  const lines = text.split("\n");
  if (!lines.length) return [];
  const headers = parseCSVLine(lines[0]);
  const rows: Record<string, string>[] = [];
  for (let i = 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const vals = parseCSVLine(lines[i]);
    const row: Record<string, string> = {};
    headers.forEach((h, idx) => (row[h.trim()] = (vals[idx] || "").trim()));
    rows.push(row);
  }
  return rows;
}

function detectColumns(rows: Record<string, string>[]) {
  if (!rows.length) return { title: "", artist: "", album: "" };
  const cols = Object.keys(rows[0]);
  return {
    title:  cols.find(c => /track.name/i.test(c)) || cols.find(c => /title/i.test(c)) || "",
    artist: cols.find(c => /artist/i.test(c)) || "",
    album:  cols.find(c => /album/i.test(c))  || "",
  };
}

// ── SLSKD helpers ─────────────────────────────────────────────────────────────
function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

function getQuality(filename: string): number {
  if (/\.flac$/i.test(filename)) return 3;
  if (/\.m4a$/i.test(filename))  return 2;
  if (/\.mp3$/i.test(filename))  return 1;
  return 0;
}

function normalizeStr(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9\s]/g, " ").trim();
}

/**
 * Extract the first meaningful keyword from a title/album string,
 * skipping common filler words. Used to match against SLSKD file paths.
 * e.g. "Animal (Expanded Edition)" → "animal"
 *      "Electric Love"             → "electric"
 *      "The Middle"                → "middle"
 */
function firstKeyWord(s: string): string {
  const stop = new Set(["the", "and", "feat", "with", "from", "live", "remix",
                        "version", "mix", "edit", "remaster", "deluxe", "bonus"]);
  const words = normalizeStr(s).split(/\s+/).filter(w => w.length > 2 && !stop.has(w));
  return words[0] ?? "";
}

/**
 * Parse the /responses array from SLSKD.
 * Each response has: { username, files: [{filename, size, ...}] }
 * We match the first keyword of title (track mode) or album (album mode)
 * against the full file path (which includes folder names = artist/album).
 */
function parseResponses(
  responses: any[],
  title: string,
  mode: SearchMode,
  album: string,
): TrackMatch[] {
  const matchTerm = mode === "albums" ? album : title;
  const keyword   = firstKeyWord(matchTerm);
  if (!keyword) return [];

  const matches: TrackMatch[] = [];

  for (const resp of responses) {
    const username = resp.username ?? "";
    for (const file of (resp.files ?? [])) {
      const fname = file.filename ?? "";
      const isAudio = /\.(flac|mp3|m4a|ogg|aac|wav)$/i.test(fname);
      if (!isAudio) continue;
      // Normalise backslashes and check for keyword anywhere in full path
      const fullPath = normalizeStr(fname.replace(/\\/g, "/"));
      if (fullPath.includes(keyword)) {
        matches.push({
          filename: fname,
          size:     file.size ?? 0,
          username,
          quality:  getQuality(fname),
        });
      }
    }
  }

  // Prefer FLAC → M4A → MP3, then largest file
  return matches.sort((a, b) =>
    a.quality !== b.quality ? b.quality - a.quality : b.size - a.size
  );
}

/**
 * Run a SLSKD search:
 * 1. POST /slskd/searches  → get search id
 * 2. Poll GET /slskd/searches/{id} until isComplete
 * 3. Fetch GET /slskd/searches/{id}/responses for actual file results
 */
async function slskdSearch(query: string): Promise<any[]> {
  // 1. Initiate
  const { data: search } = await api.post("/ui/slskd/searches", {
    searchText: query,
    fileLimit: 500,
    resultLimit: 50,
  });
  const id: string = search.id;

  // 2. Poll state until complete — SLSKD searches take ~15-30s and end with
  //    state "Completed" or "Completed, TimedOut". Poll for up to 40s.
  for (let i = 0; i < 40; i++) {
    await sleep(1000);
    const { data: state } = await api.get(`/ui/slskd/searches/${id}`);
    const done = state.isComplete ||
                 (state.state ?? "").includes("Completed") ||
                 (state.state ?? "").includes("TimedOut");
    if (done) break;
  }

  // 3. Fetch actual file results — only populated after search completes
  try {
    const { data: responses } = await api.get(`/ui/slskd/searches/${id}/responses`);
    return Array.isArray(responses) ? responses : [];
  } catch {
    return [];
  }
}

async function countActiveTransfers(): Promise<number> {
  try {
    const { data } = await api.get("/ui/slskd/transfers");
    const activeStates = ["requested", "initializing", "inprogress", "queued"];
    let count = 0;
    for (const user of (data as any[])) {
      for (const dir of (user.directories ?? [])) {
        for (const file of (dir.files ?? [])) {
          const s = (file.state ?? "").toLowerCase();
          if (activeStates.some(a => s.includes(a)) && !s.includes("completed")) count++;
        }
      }
    }
    return count;
  } catch {
    return -1;
  }
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function SlskdSearch() {
  const [csvRows,     setCsvRows]     = useState<Record<string, string>[]>([]);
  const [fileName,    setFileName]    = useState("");
  const [results,     setResults]     = useState<TrackResult[]>([]);
  const [searching,   setSearching]   = useState(false);
  const [mode,        setMode]        = useState<SearchMode>("tracks");
  const [filter,      setFilter]      = useState<FilterTab>("all");
  const [logs,        setLogs]        = useState<{ msg: string; type: string }[]>([]);
  const [progress,    setProgress]    = useState(0);
  const [slskdActive, setSlskdActive] = useState<number | null>(null);

  const logRef   = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    const poll = async () => setSlskdActive(await countActiveTransfers());
    poll();
    const id = setInterval(poll, 15000);
    return () => clearInterval(id);
  }, []);

  function addLog(msg: string, type = "info") {
    const ts = new Date().toLocaleTimeString("en-US", {
      hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    setLogs(prev => [...prev, { msg: `[${ts}] ${msg}`, type }]);
  }

  function loadFile(file: File) {
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = (e.target?.result as string).replace(/^\uFEFF/, "");
      const rows = parseCSV(text);
      setCsvRows(rows);
      setResults([]);
      setLogs([]);
      setProgress(0);
      addLog(`Loaded ${rows.length} tracks from ${file.name}`);
    };
    reader.readAsText(file, "utf-8");
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) loadFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file?.name.endsWith(".csv")) loadFile(file);
  }

  async function runSearch() {
    if (!csvRows.length) return;
    const cols = detectColumns(csvRows);
    if (!cols.title) { addLog("Cannot detect Track Name column", "error"); return; }

    setSearching(true);
    setFilter("all");
    setLogs([]);
    setProgress(0);

    const initial: TrackResult[] = csvRows.map((r, i) => ({
      idx:     i,
      title:   r[cols.title]  ?? "",
      artist:  r[cols.artist] ?? "",
      album:   r[cols.album]  ?? "",
      status:  "searching",
      matches: [],
    }));
    setResults(initial);
    addLog(`Starting ${mode} search for ${initial.length} tracks...`);

    for (let i = 0; i < initial.length; i++) {
      const track = { ...initial[i] };

      // Primary artist — split "Luis Fonsi;Daddy Yankee" → "Luis Fonsi"
      const primaryArtist = track.artist.split(";")[0].trim();

      // Album: first 3 meaningful words (avoids long noisy queries)
      const albumShort = track.album
        .replace(/[^a-zA-Z0-9\s]/g, " ")
        .trim()
        .split(/\s+/)
        .filter(w => w.length > 1)
        .slice(0, 3)
        .join(" ");

      const query = mode === "albums"
        ? `${primaryArtist} ${albumShort}`.trim()
        : `${primaryArtist} ${track.title}`.trim();

      addLog(`Searching: "${query}"`);

      try {
        const responses = await slskdSearch(query);
        const matches   = parseResponses(responses, track.title, mode, track.album);
        track.status    = matches.length ? "found" : "missing";
        track.matches   = matches;
        addLog(
          matches.length
            ? `✓ Found: ${track.artist} – ${track.title} (${matches.length} results)`
            : `✗ Missing: ${track.artist} – ${track.title}`,
          matches.length ? "found" : "miss"
        );
      } catch (err: any) {
        track.status = "missing";
        addLog(`Error: ${err.message}`, "error");
      }

      setProgress(Math.round(((i + 1) / initial.length) * 100));
      setResults(prev => prev.map((r, idx) => idx === i ? track : r));
      await sleep(300);
    }

    setSearching(false);
    addLog("Search complete.", "info");
  }

  async function queueDownload(idx: number) {
    const track = results[idx];
    if (!track?.matches.length) return;
    const best = track.matches[0];
    addLog(`Queueing: ${best.filename} from ${best.username}`, "queue");

    try {
      const { data } = await api.post(
        `/ui/slskd/downloads/${best.username}`,
        [{ filename: best.filename, size: best.size }]
      );
      if (data.ok) {
        setResults(prev => prev.map((t, i) => i === idx ? { ...t, status: "queued" } : t));
        addLog(`✓ Queued: ${track.title}`, "queue");
      } else {
        addLog(`Queue failed: status ${data.status}`, "error");
      }
    } catch (err: any) {
      addLog(`Queue error: ${err.message}`, "error");
    }
  }

  function clearAll() {
    setCsvRows([]); setResults([]); setFileName("");
    setLogs([]); setProgress(0); setFilter("all");
    if (inputRef.current) inputRef.current.value = "";
  }

  const stats = {
    total:   results.length,
    found:   results.filter(r => r.status === "found").length,
    queued:  results.filter(r => r.status === "queued").length,
    missing: results.filter(r => r.status === "missing").length,
  };

  const filtered = filter === "all" ? results : results.filter(r => r.status === filter);

  const slskdLabel =
    slskdActive === null ? "checking..."     :
    slskdActive  <  0   ? "offline"          :
    slskdActive === 0   ? "online · idle"    :
                          `online · ${slskdActive} active`;

  const slskdColor =
    slskdActive === null ? "bg-zinc-600" :
    slskdActive  <  0   ? "bg-red-500"  :
    slskdActive === 0   ? "bg-accent"   : "bg-yellow-400";

  function logColor(type: string) {
    if (type === "found") return "text-green-400";
    if (type === "miss")  return "text-yellow-400";
    if (type === "error") return "text-red-400";
    if (type === "queue") return "text-accent";
    return "text-gray-400";
  }

  function statusBadge(status: TrackStatus) {
    switch (status) {
      case "found":     return <span className="text-green-400  text-xs font-mono">● Found</span>;
      case "queued":    return <span className="text-yellow-400 text-xs font-mono">◆ Queued</span>;
      case "missing":   return <span className="text-red-400    text-xs font-mono">○ Missing</span>;
      case "searching": return <span className="text-gray-500   text-xs font-mono animate-pulse">◌ Searching</span>;
      default:          return <span className="text-gray-600   text-xs font-mono">— Idle</span>;
    }
  }

  return (
    <div className="space-y-5 max-w-5xl">

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-100">SLSKD Search</h2>
        <div className="flex items-center gap-2 bg-card border border-zinc-800 rounded-lg px-3 py-1.5">
          <span className={`w-2 h-2 rounded-full ${slskdColor}`} />
          <span className="text-xs text-gray-400 font-mono">slskd · {slskdLabel}</span>
        </div>
      </div>

      {/* Upload + controls */}
      <div className="bg-card rounded-xl p-5 border border-zinc-800 space-y-4">
        <p className="text-sm text-gray-400">
          Upload a Spotify CSV (via{" "}
          <a href="https://exportify.net" target="_blank" rel="noreferrer"
             className="text-accent underline">Exportify</a>
          ) to search SLSKD for matching tracks or albums and queue downloads.
        </p>

        <div
          onDragOver={e => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className="border border-dashed border-zinc-700 hover:border-accent rounded-xl p-6
                     text-center cursor-pointer transition group"
        >
          <input ref={inputRef} type="file" accept=".csv"
            className="hidden" onChange={handleFileChange} />
          <div className="text-2xl text-zinc-600 group-hover:text-accent transition mb-2">⬆</div>
          <p className="text-sm text-gray-400">
            {fileName
              ? <span className="text-accent font-medium">📄 {fileName}</span>
              : <><strong className="text-gray-200">Drop CSV here</strong> or click to browse</>
            }
          </p>
          {csvRows.length > 0 &&
            <p className="text-xs text-gray-500 mt-1">{csvRows.length} tracks loaded</p>
          }
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={runSearch}
            disabled={!csvRows.length || searching}
            className="px-5 py-2 bg-accent text-black font-semibold text-sm rounded-lg
                       hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            {searching ? "Searching..." : "Search SLSKD"}
          </button>

          <button
            onClick={clearAll}
            disabled={!csvRows.length && !results.length}
            className="px-4 py-2 bg-zinc-700 text-gray-200 text-sm rounded-lg
                       hover:bg-zinc-600 disabled:opacity-40 transition"
          >
            Clear
          </button>

          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-gray-500">Search by:</span>
            <div className="flex border border-zinc-700 rounded-lg overflow-hidden">
              {(["tracks", "albums"] as SearchMode[]).map(m => (
                <button key={m} onClick={() => setMode(m)}
                  className={`px-3 py-1 text-xs capitalize transition ${
                    mode === m
                      ? "bg-accent text-black font-semibold"
                      : "bg-transparent text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {searching && (
        <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
          <div className="h-full bg-accent transition-all duration-300" style={{ width: `${progress}%` }} />
        </div>
      )}

      {results.length > 0 && (
        <div className="grid grid-cols-4 gap-px bg-zinc-800 border border-zinc-800 rounded-xl overflow-hidden">
          {[
            { label: "Total",   value: stats.total,   color: "text-gray-100"   },
            { label: "Found",   value: stats.found,   color: "text-green-400"  },
            { label: "Queued",  value: stats.queued,  color: "text-yellow-400" },
            { label: "Missing", value: stats.missing, color: "text-red-400"    },
          ].map(s => (
            <div key={s.label} className="bg-card px-4 py-3">
              <div className="text-xs text-gray-500 mb-1">{s.label}</div>
              <div className={`text-xl font-bold ${s.color}`}>{s.value}</div>
            </div>
          ))}
        </div>
      )}

      {results.length > 0 && (
        <div className="bg-card rounded-xl border border-zinc-800 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
            <span className="text-xs text-gray-500 font-mono uppercase tracking-wide">Results</span>
            <div className="flex gap-1">
              {(["all", "found", "queued", "missing"] as FilterTab[]).map(f => (
                <button key={f} onClick={() => setFilter(f)}
                  className={`px-2.5 py-1 rounded text-xs capitalize transition ${
                    filter === f
                      ? "bg-accent text-black font-semibold"
                      : "bg-zinc-800 text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-[2rem_1fr_160px_90px_80px] gap-3 px-4 py-2
                          border-b border-zinc-800 text-xs text-gray-500 font-mono uppercase tracking-wide">
            <span>#</span><span>Track</span><span>Album</span><span>Status</span><span>Action</span>
          </div>

          <div className="divide-y divide-zinc-800/60 max-h-[60vh] overflow-y-auto scrollbar-thin">
            {filtered.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-gray-500">No results in this filter</div>
            ) : filtered.map(track => (
              <div key={track.idx}
                className="grid grid-cols-[2rem_1fr_160px_90px_80px] gap-3 px-4 py-3
                           items-center hover:bg-zinc-800/40 transition"
              >
                <span className="text-xs text-gray-600 font-mono text-right">{track.idx + 1}</span>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-100 truncate">{track.title}</div>
                  <div className="text-xs text-gray-500 truncate font-mono">{track.artist}</div>
                </div>
                <div className="text-xs text-gray-500 truncate">{track.album}</div>
                <div>{statusBadge(track.status)}</div>
                <div>
                  {track.status === "found" && track.matches.length > 0 ? (
                    <button onClick={() => queueDownload(track.idx)}
                      className="px-2 py-1 text-xs bg-zinc-700 text-gray-200 rounded
                                 hover:bg-accent hover:text-black transition font-mono">
                      ⬇ Queue
                    </button>
                  ) : track.status === "queued" ? (
                    <span className="text-xs text-yellow-400 font-mono">Queued</span>
                  ) : (
                    <span className="text-xs text-gray-600">—</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {logs.length > 0 && (
        <div className="bg-black/80 rounded-xl border border-zinc-800 p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-mono uppercase tracking-wide">Search Log</span>
            <div className="flex items-center gap-3">
              {searching && <span className="text-xs text-accent animate-pulse">Running...</span>}
              <button onClick={() => setLogs([])}
                className="text-xs text-gray-600 hover:text-gray-400 transition">Clear</button>
            </div>
          </div>
          <div ref={logRef}
            className="font-mono text-xs space-y-0.5 max-h-48 overflow-y-auto scrollbar-thin">
            {logs.map((entry, i) => (
              <div key={i} className={logColor(entry.type)}>{entry.msg}</div>
            ))}
            {searching && <div className="text-gray-600 animate-pulse">...</div>}
          </div>
        </div>
      )}
    </div>
  );
}
