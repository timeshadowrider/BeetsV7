import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export function useLibraryStats() {
  return useQuery({
    queryKey: ["stats", "library"],
    queryFn: async () => {
      const { data } = await api.get("/ui/stats/library");
      return data;
    },
    refetchInterval: 30_000,   // re-fetch every 30s
    staleTime: 10_000
  });
}

export function useInboxStats() {
  return useQuery({
    queryKey: ["stats", "inbox"],
    queryFn: async () => {
      const { data } = await api.get("/ui/stats/inbox");
      return data;
    },
    refetchInterval: 30_000,
    staleTime: 10_000
  });
}

export function useRecentAlbums() {
  return useQuery({
    queryKey: ["albums", "recent"],
    queryFn: async () => {
      const { data } = await api.get("/ui/albums/recent");
      return data as any[];
    },
    refetchInterval: 60_000,
    staleTime: 30_000
  });
}

export function useAllAlbums() {
  return useQuery({
    queryKey: ["albums", "all"],
    queryFn: async () => {
      const { data } = await api.get("/ui/albums/all");
      return data as any[];
    }
  });
}

export function usePipelineLog() {
  return useQuery({
    queryKey: ["logs", "pipeline"],
    queryFn: async () => {
      const { data } = await api.get("/ui/logs/pipeline", {
        responseType: "text"
      });
      return data as string;
    },
    refetchInterval: 2000
  });
}

export function useBeetsLog() {
  return useQuery({
    queryKey: ["logs", "beets"],
    queryFn: async () => {
      const { data } = await api.get("/ui/logs/beets", {
        responseType: "text"
      });
      return data as string;
    },
    refetchInterval: 2000
  });
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["pipeline", "status"],
    queryFn: async () => {
      const { data } = await api.get("/status");
      return data;
    },
    enabled: false
  });
}

export async function runPipeline() {
  await api.post("/pipeline/run");
}
