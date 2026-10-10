"use client";

/**
 * The browser-side data layer (design portal-shell, decision 11): one TanStack Query client per page load, wired
 * to the fetch wrapper so a sign-out clears every cached list.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError, setClientHooks } from "@/lib/api/client";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return count < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => {
    const qc = makeQueryClient();
    setClientHooks({ clearCache: () => qc.clear() });
    return qc;
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
