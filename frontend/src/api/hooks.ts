import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

export function useLibraryStats() {
  return useQuery({
    queryKey: ["stats", "library"],
    queryFn: async () => {
      const { data } = await api.get("/ui/stats/library");
      return data;
    }
  });
}

export function useInboxStats() {
  return useQuery({
    queryKey: ["stats", "inbox"],
    queryFn: async () => {
      const { data } = await api.get("/ui/stats/inbox");
      return data;
    }
  });
}

export function useRecentAlbums() {
  return useQuery({
    queryKey: ["albums", "recent"],
    queryFn: async () => {
      const { data } = await api.get("/ui/albums/recent");
      return data as any[];
    }
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
      const { data } = await api.get("/status"); // adjust if you expose pipeline_status.json
      return data;
    },
    enabled: false
  });
}

export async function runPipeline() {
  await api.post("/pipeline/run");
}
