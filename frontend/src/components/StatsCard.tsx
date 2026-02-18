export default function StatsCard({
  title,
  items,
  isLoading = false
}: {
  title: string;
  items: { label: string; value: number | string }[];
  isLoading?: boolean;
}) {
  return (
    <div className="bg-card rounded-xl p-4 shadow-md border border-zinc-800">
      <h3 className="text-sm font-semibold text-gray-200 mb-3">{title}</h3>

      {isLoading ? (
        // Animated skeleton rows while fetching
        <div className="space-y-2">
          {[1, 2, 3].map(n => (
            <div key={n} className="h-4 bg-zinc-700 rounded animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-xs text-gray-500">No data available</p>
      ) : (
        <ul className="space-y-1 text-sm text-gray-300">
          {items.map(i => (
            <li key={i.label} className="flex justify-between">
              <span className="text-gray-400">{i.label}</span>
              <span className="font-medium">{i.value}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
