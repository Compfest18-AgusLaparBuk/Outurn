"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toasty } from "@cloudflare/kumo/components/toast";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Toasty>{children}</Toasty>
    </QueryClientProvider>
  );
}
