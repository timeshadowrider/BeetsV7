export default function StatsCard({
  title,
  items
}: {
  title: string;
  items: { label: string; value: number | string }[];
}) {
  return (
    <div className="bg-card rounded-xl p-4 shadow-md border border-zinc-800">
      <h3 className="text-sm font-semibold text-gray-200 mb-3">{title}</h3>
      <ul className="space-y-1 text-sm text-gray-300">
        {items.map(i => (
          <li key={i.label} className="flex justify-between">
            <span className="text-gray-400">{i.label}</span>
            <span className="font-medium">{i.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
