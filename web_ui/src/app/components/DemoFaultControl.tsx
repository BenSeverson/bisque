/**
 * Demo-only lever for tripping a simulated safety fault.
 *
 * A kiln that never fails leaves everything downstream of a fault unreachable:
 * the dashboard error banner, the history detail's cause line, and Settings'
 * Last Error and emergency-stop guidance (all #235). In the mock that was the
 * permanent state — every history record was hardcoded `errorCode: 0` and the
 * simulator had no path into `status: "error"` — so the published demo, which
 * is the only place most people will ever see this UI, showed the happy path
 * exclusively (#239).
 *
 * Render this ONLY under `__DEMO__`. It posts to `/api/v1/mock/fault`, which
 * exists in the mock server alone; a real controller answers 404.
 */
import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, ChevronDown } from "lucide-react";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { api } from "../services/api";
import { queryKeys } from "../hooks/queries";
import { FIRING_ERROR_CODES, describeFiringError } from "../utils/firingError";
import { toErrorMessage } from "../utils/error";

/**
 * The faults worth reaching by hand. Between them they cover both shapes the
 * copy takes — a cause with an actionable remedy (E1, E3, E5) and one where
 * there is nothing honest to add from a phone (E2).
 */
const FAULTS = [
  FIRING_ERROR_CODES.TC_FAULT,
  FIRING_ERROR_CODES.OVER_TEMP,
  FIRING_ERROR_CODES.NOT_RISING,
  FIRING_ERROR_CODES.EMERGENCY_STOP,
];

export function DemoFaultControl() {
  const queryClient = useQueryClient();

  const trip = useCallback(
    async (code: number) => {
      try {
        await api.simulateFault(code);
        // The fault lands in the simulator, not in React Query's cache: the
        // trip flips /system's emergencyStop and lastErrorCode, and closes out
        // an in-progress firing into a new history record. Neither query
        // refetches on its own, so Settings would keep rendering "None" until
        // something else invalidated them.
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.systemInfo }),
          queryClient.invalidateQueries({ queryKey: queryKeys.history }),
        ]);
        toast.success(`Simulated fault: ${describeFiringError(code)}`);
      } catch (e) {
        toast.error(`Could not simulate a fault: ${toErrorMessage(e)}`);
      }
    },
    [queryClient],
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className="gap-2">
          <AlertTriangle className="h-4 w-4" />
          Simulate Fault
          <ChevronDown className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {FAULTS.map((code) => (
          <DropdownMenuItem key={code} onSelect={() => void trip(code)}>
            {describeFiringError(code)} (E{code})
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
