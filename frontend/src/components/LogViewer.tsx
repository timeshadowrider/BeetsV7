export default function LogViewer({ text }: { text: string }) {
  return (
    <pre className="bg-black/80 text-green-400 text-xs p-3 rounded-xl border border-zinc-800 overflow-auto max-h-[70vh] whitespace-pre-wrap scrollbar-thin">
      {text || "No log data."}
    </pre>
  );
}
