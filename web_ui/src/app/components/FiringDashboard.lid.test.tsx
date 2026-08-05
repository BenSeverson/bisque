import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { withQueryClient } from "../test/queryWrapper";
import { useKilnStore } from "../stores/kilnStore";
import { FiringDashboard } from "./FiringDashboard";

/**
 * The lid indicator's whole job is to distinguish three states the firmware
 * deliberately reports differently: no switch fitted (key omitted → null),
 * fitted and shut (false), fitted and open (true). Collapsing the first two is
 * the bug this guards — it would put a permanent "Lid closed" on every kiln
 * that has no switch at all, which is most of them.
 */
describe("FiringDashboard lid indicator", () => {
  const setLid = (lidOpen: boolean | null) => {
    useKilnStore.setState((s) => ({ firingProgress: { ...s.firingProgress, lidOpen } }));
  };

  it("shows nothing when the kiln reports no lid switch", () => {
    setLid(null);
    render(<FiringDashboard />, { wrapper: withQueryClient().wrapper });
    expect(screen.queryByText(/^Lid /)).not.toBeInTheDocument();
  });

  it("reports an open lid", () => {
    setLid(true);
    render(<FiringDashboard />, { wrapper: withQueryClient().wrapper });
    expect(screen.getByText(/Lid open/)).toBeInTheDocument();
  });

  it("reports a closed lid", () => {
    setLid(false);
    render(<FiringDashboard />, { wrapper: withQueryClient().wrapper });
    expect(screen.getByText(/Lid closed/)).toBeInTheDocument();
  });
});
