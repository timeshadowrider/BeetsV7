import { useState } from "react";
import { api } from "../api/client";

export default function VolumioBuilder() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<string>("");

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setStatus("Uploading and building playlist…");
    const form = new FormData();
    form.append("file", file);
    form.append("name", "Spotify Import");
    try {
      const { data } = await api.post(
        "/volumio/playlist/from_spotify_csv",
        form,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      setStatus(`Imported ${data.tracks ?? "?"} tracks.`);
    } catch (err: any) {
      setStatus(`Error: ${err?.message ?? "unknown"}`);
    }
  };

  return (
    <div className="max-w-xl space-y-4">
      <div className="bg-card rounded-xl p-4 border border-zinc-800 shadow-md">
        <h3 className="text-sm font-semibold text-gray-200 mb-3">
          Volumio Playlist Builder (Spotify CSV)
        </h3>
        <form className="space-y-3" onSubmit={onSubmit}>
          <input
            type="file"
            accept=".csv"
            onChange={e => setFile(e.target.files?.[0] ?? null)}
            className="text-sm text-gray-200"
          />
          <button
            type="submit"
            disabled={!file}
            className="px-4 py-2 rounded-lg bg-accent text-black text-sm font-semibold disabled:opacity-50"
          >
            Upload & Build
          </button>
        </form>
        {status && (
          <div className="mt-3 text-xs text-gray-300">
            {status}
          </div>
        )}
      </div>
    </div>
  );
}
