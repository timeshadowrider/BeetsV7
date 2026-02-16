type Album = {
  albumartist: string;
  album: string;
  cover?: string;
};

function fallbackCoverKey(a: Album) {
  return encodeURIComponent(`${a.albumartist}-${a.album}`.toLowerCase());
}

export default function AlbumCard({
  album,
  onClick
}: {
  album: Album;
  onClick?: () => void;
}) {
  // ---------------------------------------------------------
  // FIXED: Use album.cover directly (no extra /music prefix)
  // ---------------------------------------------------------
  const cover = album.cover
    ? album.cover
    : `/fallback-covers/${fallbackCoverKey(album)}.png`;

  return (
    <button
      onClick={onClick}
      className="bg-card rounded-xl overflow-hidden shadow-md border border-zinc-800 hover:border-accent transition flex flex-col"
    >
      <div className="aspect-square bg-zinc-900">
        <img
          src={cover}
          alt={album.album}
          className="w-full h-full object-cover"
          loading="lazy"
        />
      </div>
      <div className="p-2 text-left">
        <div className="text-sm font-semibold text-gray-100 truncate">
          {album.album}
        </div>
        <div className="text-xs text-gray-400 truncate">
          {album.albumartist}
        </div>
      </div>
    </button>
  );
}
