import { useState, useMemo } from "react";
import { useAllAlbums } from "../api/hooks";
import AudioPlayer from "../components/AudioPlayer";

export default function WebPlayer() {
  const { data: albums, isLoading } = useAllAlbums();
  const [query, setQuery] = useState("");
  const [selectedAlbum, setSelectedAlbum] = useState<any | null>(null);
  const [trackIndex, setTrackIndex] = useState(0);
  const [shouldAutoPlay, setShouldAutoPlay] = useState(false);

  // Filter albums by search query
  const filtered = useMemo(() => {
    if (!albums) return [];
    const q = query.toLowerCase();
    return albums.filter((a: any) =>
      `${a.albumartist} ${a.album}`.toLowerCase().includes(q)
    );
  }, [albums, query]);

  // Extract track number from track, title, or filename
  const getTrackNumber = (t: any): number => {
    // 1. If track field exists
    if (t.track != null) {
      const n = Number(t.track);
      if (!Number.isNaN(n)) return n;
    }

    // 2. Extract from title: "03 If I Die Young"
    if (typeof t.title === "string") {
      const m = /^(\d+)[\s._-]/.exec(t.title.trim());
      if (m) return Number(m[1]);
    }

    // 3. Extract from filename: "03 If I Die Young.mp3"
    if (typeof t.path === "string") {
      const base = t.path.split("/").pop() ?? "";
      const m = /^(\d+)[\s._-]/.exec(base.trim());
      if (m) return Number(m[1]);
    }

    return 0;
  };

  // Sort tracks using derived track numbers
  const tracks = useMemo(() => {
    if (!selectedAlbum?.tracks) return [];

    return [...selectedAlbum.tracks]
      .map(t => ({
        ...t,
        _trackNumber: getTrackNumber(t)
      }))
      .sort((a, b) => a._trackNumber - b._trackNumber);
  }, [selectedAlbum]);

  // Current track object for AudioPlayer
  const currentTrack =
    tracks.length > 0
      ? {
          title: tracks[trackIndex]?.title ?? "",
          path: tracks[trackIndex]?.path ?? ""
        }
      : null;

  // Auto-play next track
  const handleEnded = () => {
    if (trackIndex < tracks.length - 1) {
      setTrackIndex(trackIndex + 1);
      setShouldAutoPlay(true);
    }
  };

  // Format codec + bit depth + sample rate + bitrate
  const formatCodec = (
    codec: string,
    bitDepth: number,
    sampleRate: number,
    bitrate: number
  ) => {
    if (codec?.includes("flac"))
      return `${bitDepth}/${(sampleRate / 1000).toFixed(1)}`;
    if (codec?.includes("mpeg")) return `${bitrate}kbps`;
    if (codec?.includes("aac")) return "AAC";
    return (codec || "").toUpperCase();
  };

  return (
    <div className="grid gap-4 grid-cols-1 md:grid-cols-[280px,1fr]">
      {/* LEFT SIDEBAR */}
      <div className="space-y-4">
        <div className="bg-card rounded-xl p-3 border border-zinc-800">
          <input
            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-accent"
            placeholder="Search artist or album…"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
        </div>

        <div className="bg-card rounded-xl p-3 border border-zinc-800 max-h-[70vh] overflow-auto scrollbar-thin">
          {isLoading || !filtered ? (
            <div className="text-xs text-gray-400">Loading…</div>
          ) : (
            <ul className="space-y-1 text-sm">
              {filtered.map((a: any, i: number) => (
                <li key={i}>
                  <button
                    className={`w-full text-left px-2 py-1 rounded-md ${
                      selectedAlbum === a
                        ? "bg-accent text-black"
                        : "hover:bg-zinc-800 text-gray-200"
                    }`}
                    onClick={() => {
                      setSelectedAlbum(a);
                      setTrackIndex(0);
                      setShouldAutoPlay(false); // album click = paused
                    }}
                  >
                    {a.albumartist} — {a.album}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* RIGHT SIDE */}
      <div className="space-y-4">
        <div className="bg-card rounded-xl p-4 border border-zinc-800">
          {selectedAlbum ? (
            <>
              <div className="flex gap-4">
                {/* COVER */}
                <div className="w-40 h-40 bg-zinc-900 rounded-lg overflow-hidden">
                  <img
                    src={selectedAlbum.cover || "/fallback-covers/default.png"}
                    alt={selectedAlbum.album}
                    className="w-full h-full object-cover"
                  />
                </div>

                {/* TRACKLIST */}
                <div className="flex-1">
                  <div className="text-sm text-gray-400 mb-1">
                    {selectedAlbum.albumartist}
                  </div>
                  <div className="text-xl font-semibold text-gray-100 mb-3">
                    {selectedAlbum.album}
                  </div>

                  <ul className="text-sm text-gray-200 max-h-64 overflow-auto scrollbar-thin">
                    {tracks.map((t: any, i: number) => (
                      <li key={i}>
                        <button
                          className={`w-full text-left px-2 py-1 rounded-md ${
                            i === trackIndex
                              ? "bg-accent text-black"
                              : "hover:bg-zinc-800"
                          }`}
                          onClick={() => {
                            setTrackIndex(i);
                            setShouldAutoPlay(true); // track click = play
                          }}
                        >
                          {t._trackNumber ? `${t._trackNumber}. ` : ""}
                          {t.title}

                          <span className="text-xs text-gray-400 ml-2">
                            {formatCodec(
                              t.codec,
                              t.bit_depth,
                              t.sample_rate,
                              t.bitrate
                            )}
                            {" • "}
                            {t.duration_human}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              {/* AUDIO PLAYER */}
              <AudioPlayer
                track={currentTrack}
                autoPlay={shouldAutoPlay}
                onEnded={handleEnded}
              />
            </>
          ) : (
            <div className="text-sm text-gray-400">
              Select an album from the left to start playing.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
