import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchBox from "./SearchBox";

const results = [
  { geo_level: "place", geo_id: "0455000", name: "Phoenix", state_abbr: "AZ", display: "Phoenix, AZ", match_score: 1 },
  { geo_level: "county", geo_id: "04013", name: "Maricopa County", state_abbr: "AZ", display: "Maricopa County, AZ", match_score: 0.9 },
];

describe("SearchBox", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows typeahead results from /api/search", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(results), { status: 200 }));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <SearchBox />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.type(screen.getByLabelText("Search markets"), "phoe");
    await waitFor(() => expect(screen.getByText("Phoenix, AZ")).toBeInTheDocument());
    expect(screen.getByText("Maricopa County, AZ")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/search?q=phoe"), expect.anything());
  });
});
