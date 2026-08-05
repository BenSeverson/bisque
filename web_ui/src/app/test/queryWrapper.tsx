import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * A React Query client tuned for tests: no retries, so a mocked rejection fails
 * the assertion immediately rather than three seconds later.
 *
 * `gcTime: Infinity` rather than 0 — an entry seeded with `setQueryData` has no
 * observer, so a zero gcTime collects it before the assertion can read it back.
 * Isolation comes from building a fresh client per test, not from eviction.
 */
export function makeTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

/**
 * Wrapper for `renderHook`/`render`. Returns the client too, so a test can
 * inspect the cache directly — which is how the optimistic-update and rollback
 * behaviour in useSaveSettings is observed.
 */
export function withQueryClient(client = makeTestQueryClient()) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}
