"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";

/**
 * One query client per browser session.
 *
 * Retries are off for 4xx: a 402 over quota or a 404 will answer the same way five times
 * and the user is left watching a spinner instead of reading the reason.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (count, error) => {
              if (error instanceof ApiError && error.status < 500) return false;
              return count < 2;
            },
            staleTime: 10_000,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
