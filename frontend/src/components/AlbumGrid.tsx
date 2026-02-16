import AlbumCard from "./AlbumCard";

type Album = {
  albumartist: string;
  album: string;
  cover?: string;
};

export default function AlbumGrid({
  albums,
  onSelect
}: {
  albums: Album[];
  onSelect?: (a: Album) => void;
}) {
  return (
    <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
      {albums.map((a, i) => (
        <AlbumCard
          key={i}
          album={a}
          onClick={onSelect ? () => onSelect(a) : undefined}
        />
      ))}
    </div>
  );
}
