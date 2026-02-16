import StatsCard from "../components/StatsCard";
import AlbumGrid from "../components/AlbumGrid";
import { useLibraryStats, useInboxStats, useRecentAlbums } from "../api/hooks";

export default function Dashboard() {
  const { data: lib, isLoading: libLoading } = useLibraryStats();
  const { data: inbox, isLoading: inboxLoading } = useInboxStats();
  const { data: recent, isLoading: recentLoading } = useRecentAlbums();

  return (
    <div className="space-y-6">
      <div className="grid gap-4 grid-cols-1 md:grid-cols-2">
        <StatsCard
          title="Library Stats"
          items={
            libLoading || !lib
              ? []
              : [
                  { label: "Artists", value: lib.artists ?? "?" },
                  { label: "Albums", value: lib.albums ?? "?" },
                  { label: "Tracks", value: lib.tracks ?? "?" }
                ]
          }
        />
        <StatsCard
          title="Inbox Stats"
          items={
            inboxLoading || !inbox
              ? []
              : [
                  { label: "Artists", value: inbox.artists ?? "?" },
                  { label: "Tracks", value: inbox.tracks ?? "?" }
                ]
          }
        />
      </div>

      <div className="bg-card rounded-xl p-4 border border-zinc-800 shadow-md">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">
          Recently Added Albums
        </h3>
        {recentLoading || !recent ? (
          <div className="text-xs text-gray-400">Loading…</div>
        ) : (
          <ul className="text-sm text-gray-300 space-y-1">
            {recent.map((a: any, i: number) => (
              <li key={i} className="flex justify-between">
                <span className="truncate">
                  {a.albumartist} — {a.album}
                </span>
                {a.added && (
                  <span className="text-xs text-gray-500 ml-2">
                    {a.added}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="bg-card rounded-xl p-4 border border-zinc-800 shadow-md">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">
          Newest Albums Grid
        </h3>
        {recentLoading || !recent ? (
          <div className="text-xs text-gray-400">Loading…</div>
        ) : (
          <AlbumGrid albums={recent} />
        )}
      </div>
    </div>
  );
}
