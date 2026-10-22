import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export function useResource<T>(path: string | null) {
  return useQuery({
    queryKey: [path],
    queryFn: () => api<T>(path as string),
    enabled: Boolean(path),
  });
}
