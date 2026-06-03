import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./app/App.tsx";
import "./styles/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: true,
    },
  },
});

async function bootstrap() {
  // In the static demo build, install the in-browser mock backend BEFORE the
  // app mounts and makes its first request/WebSocket connection. The dynamic
  // import keeps the simulator out of the firmware bundle (__DEMO__ folds to
  // false there, so this branch and its import are dropped).
  if (__DEMO__) {
    const { installDemo } = await import("./app/mock/installDemo");
    installDemo();
  }

  createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

void bootstrap();
