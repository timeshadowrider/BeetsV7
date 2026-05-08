import { useEffect, useRef, useState } from "react";

type Track = {
  title: string;
  path: string;
};

export default function AudioPlayer({
  track,
  autoPlay,
  onEnded
}: {
  track: Track | null;
  autoPlay: boolean;
  onEnded?: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // Load track + respect autoPlay flag
  useEffect(() => {
    if (!audioRef.current || !track) return;

    const audio = audioRef.current;
    audio.src = track.path;
    audio.load();

    if (autoPlay) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }, [track, autoPlay]);

  const formatTime = (sec: number) => {
    if (!sec || isNaN(sec)) return "0:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60)
      .toString()
      .padStart(2, "0");
    return `${m}:${s}`;
  };

  return (
    <div className="bg-card border border-zinc-800 rounded-xl p-3 mt-4">
      <div className="text-xs text-gray-400 mb-1">Now Playing:</div>
      <div className="text-sm text-gray-100 mb-2 truncate">
        {track ? track.title : "Nothing selected"}
      </div>

      <audio
        ref={audioRef}
        controls
        className="w-full"
        onEnded={onEnded}
        onTimeUpdate={() => {
          if (audioRef.current) setCurrentTime(audioRef.current.currentTime);
        }}
        onLoadedMetadata={() => {
          if (audioRef.current) setDuration(audioRef.current.duration);
        }}
      />

      <div className="text-xs text-gray-400 mt-1">
        {formatTime(currentTime)} / {formatTime(duration)}
      </div>
    </div>
  );
}
