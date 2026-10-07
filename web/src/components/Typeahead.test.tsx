import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import Typeahead from "./Typeahead";

interface Hit {
  name: string;
  unit: string;
  category: string;
  score: number;
  match: "prefix" | "fuzzy";
}

function Harness({
  search,
  onSelect,
}: {
  search: (q: string, signal: AbortSignal) => Promise<Hit[]>;
  onSelect: (hit: Hit) => void;
}) {
  const [value, setValue] = useState("");

  return (
    <Typeahead
      label="Test"
      value={value}
      onChange={setValue}
      onSelect={onSelect}
      search={search}
    />
  );
}

describe("Typeahead", () => {
  it("searches once, DEBOUNCE_MS after the last keystroke", async () => {
    const search = vi.fn((_q: string, _signal: AbortSignal) => Promise.resolve([]));
    const onSelect = vi.fn();

    render(<Harness search={search} onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    const user = userEvent.setup();

    await user.type(input, "chick");
    expect(search).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(search).toHaveBeenCalledOnce();
    }, { timeout: 500 });

    expect(search).toHaveBeenCalledWith("chick", expect.any(Object));
  });

  it("aborts the stale request and ignores its late response", async () => {
    const search = vi.fn((_q: string, _signal: AbortSignal) => {
      return new Promise<Hit[]>(() => {
        // Never resolves - tests that cancellation works
      });
    });
    const onSelect = vi.fn();

    render(<Harness search={search} onSelect={onSelect} />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    const user = userEvent.setup();

    await user.type(input, "ch");
    await waitFor(() => {
      expect(search).toHaveBeenCalledTimes(1);
    }, { timeout: 500 });

    const firstSignal = (search.mock.calls[0] as any)[1];

    await user.type(input, "i");
    await waitFor(() => {
      expect(search).toHaveBeenCalledTimes(2);
    }, { timeout: 500 });

    const secondSignal = (search.mock.calls[1] as any)[1];

    expect(firstSignal.aborted).toBe(true);
    expect(secondSignal.aborted).toBe(false);
  });

  it("exposes combobox and listbox roles", async () => {
    const hits: Hit[] = [
      { name: "chicken breast", unit: "lb", category: "Meat", score: 1, match: "prefix" },
    ];
    const search = vi.fn((_q: string, _signal: AbortSignal) =>
      Promise.resolve(hits)
    );
    const onSelect = vi.fn();

    render(<Harness search={search} onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    const user = userEvent.setup();

    expect(input).toHaveAttribute("aria-autocomplete", "list");

    await user.type(input, "chick");

    await waitFor(() => {
      const options = screen.queryAllByRole("option");
      expect(options.length).toBeGreaterThan(0);
    }, { timeout: 500 });

    expect(input).toHaveAttribute("aria-expanded", "true");

    const option = screen.getByRole("option");
    expect(option).toBeInTheDocument();
  });

  it("supports ArrowUp, ArrowDown, Enter and Escape", async () => {
    const hits: Hit[] = [
      { name: "chicken breast", unit: "lb", category: "Meat", score: 1, match: "prefix" },
      { name: "chicken thighs", unit: "lb", category: "Meat", score: 0.9, match: "prefix" },
    ];
    const search = vi.fn((_q: string, _signal: AbortSignal) =>
      Promise.resolve(hits)
    );
    const onSelect = vi.fn();

    render(<Harness search={search} onSelect={onSelect} />);
    const input = screen.getByRole("combobox") as HTMLInputElement;
    const user = userEvent.setup();

    await user.type(input, "chick");

    await waitFor(() => {
      const options = screen.queryAllByRole("option");
      expect(options.length).toBeGreaterThan(0);
    }, { timeout: 500 });

    await user.keyboard("{ArrowDown}");
    let firstOption = screen.getAllByRole("option")[0];
    expect(firstOption).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", firstOption.id);

    await user.keyboard("{ArrowDown}");
    let secondOption = screen.getAllByRole("option")[1];
    expect(secondOption).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", secondOption.id);

    await user.keyboard("{ArrowUp}");
    firstOption = screen.getAllByRole("option")[0];
    expect(firstOption).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith(hits[0]);
    expect(input.value).toBe("chicken breast");

    await user.type(input, " extra");
    await waitFor(() => {
      expect(search).toHaveBeenCalledWith("chicken breast extra", expect.any(Object));
    }, { timeout: 500 });

    await user.keyboard("{Escape}");
    expect(input).toHaveAttribute("aria-expanded", "false");
  });

  it("highlights the matched text", async () => {
    const hits: Hit[] = [
      { name: "chicken breast", unit: "lb", category: "Meat", score: 1, match: "prefix" },
    ];
    const search = vi.fn((_q: string, _signal: AbortSignal) =>
      Promise.resolve(hits)
    );
    const onSelect = vi.fn();

    render(<Harness search={search} onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    const user = userEvent.setup();

    await user.type(input, "chi");

    await waitFor(() => {
      const mark = screen.getByText("chi");
      expect(mark.tagName).toBe("MARK");
    }, { timeout: 500 });
  });

  it("does not search for an empty query", async () => {
    const search = vi.fn();
    const onSelect = vi.fn();

    render(<Harness search={search} onSelect={onSelect} />);
    const input = screen.getByRole("combobox");
    const user = userEvent.setup();

    await user.clear(input);

    await new Promise(resolve => setTimeout(resolve, 250));

    expect(search).not.toHaveBeenCalled();
  });
});
