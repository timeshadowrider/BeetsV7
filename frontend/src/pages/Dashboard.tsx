import StatsCard from "../components/StatsCard";
import AlbumGrid from "../components/AlbumGrid";
import { useLibraryStats, useInboxStats, useRecentAlbums } from "../api/hooks";

// Format ISO timestamp ? "Feb 17, 2026"
function formatDate(raw?: string): string {
  if (!raw) return "";
  const d = new Date(raw);
  if (isNaN(d.getTime())) return raw; // fall back to raw if unparseable
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

// Strip the corrupted separator character (? and variants) Beets sometimes
// inserts between albumartist and album in the joined string.
function cleanText(s?: string): string {
  if (!s) return "";
  return s.replace(/[?\uFFFD]/g, "").trim();
}

export default function Dashboard() {
  const { data: lib, isLoading: libLoading } = useLibraryStats();
  const { data: inbox, isLoading: inboxLoading } = useInboxStats();
  const { data: recent, isLoading: recentLoading } = useRecentAlbums();

  return (
    <div className="space-y-6">
      {/* -- Stats row --------------------------------------------- */}
      <div className="grid gap-4 grid-cols-1 md:grid-cols-2">
        <StatsCard
          title="Library Stats"
          isLoading={libLoading}
          items={
            !lib
              ? []
              : [
                  { label: "Artists", value: lib.artists ?? "—" },
                  { label: "Albums",  value: lib.albums  ?? "—" },
                  { label: "Tracks",  value: lib.tracks  ?? "—" },
                  ...(lib.formats != null
                    ? [{ label: "Formats", value: lib.formats }]
                    : []),
                  ...(lib.genres != null
                    ? [{ label: "Genres",  value: lib.genres  }]
                    : []),
                  ...(lib.labels != null
                    ? [{ label: "Labels",  value: lib.labels  }]
                    : [])
                ]
          }
        />

        <StatsCard
          title="Inbox Stats"
          isLoading={inboxLoading}
          items={
            !inbox
              ? []
              : [
                  { label: "Artists", value: inbox.artists ?? "—" },
                  { label: "Tracks",  value: inbox.tracks  ?? "—" }
                ]
          }
        />
      </div>

      {/* -- Recently Added + Album Grid (side by side) ------------- */}
      <div className="flex gap-4 items-start">

        {/* Left: compact text list */}
        <div className="w-72 flex-shrink-0 bg-card rounded-xl p-4 border border-zinc-800 shadow-md">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">
            Recently Added
          </h3>
          {recentLoading ? (
            <div className="space-y-2">
              {[...Array(8)].map((_, n) => (
                <div key={n} className="h-3 bg-zinc-700 rounded animate-pulse" />
              ))}
            </div>
          ) : !recent || recent.length === 0 ? (
            <p className="text-xs text-gray-500">No albums found</p>
          ) : (
            <ul className="space-y-2 text-xs text-gray-300">
              {recent.map((a) => (
                <li
                  key={`${cleanText(a.albumartist)}::${cleanText(a.album)}`}
                  className="flex flex-col"
                >
                  <span className="font-medium text-gray-200 truncate">
                    {cleanText(a.albumartist)}
                  </span>
                  <span className="text-gray-400 truncate">{cleanText(a.album)}</span>
                  {a.added && (
                    <span className="text-gray-600 text-[10px]">
                      {formatDate(a.added)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Right: album art grid */}
        <div className="flex-1 bg-card rounded-xl p-4 border border-zinc-800 shadow-md min-w-0">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">
            Newest Albums
          </h3>
          {recentLoading ? (
            <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
              {[...Array(12)].map((_, n) => (
                <div
                  key={n}
                  className="aspect-square bg-zinc-700 rounded-xl animate-pulse"
                />
              ))}
            </div>
          ) : !recent || recent.length === 0 ? (
            <p className="text-xs text-gray-500">No albums found</p>
          ) : (
            <AlbumGrid albums={recent} />
          )}
        </div>
      </div>
    </div>
  );
}
