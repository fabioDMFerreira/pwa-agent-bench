import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ColumnPicker } from "../ColumnPicker.js";
import { DEFAULT_VISIBLE, LOCKED_ON } from "../columnDefs.js";

describe("<ColumnPicker/>", () => {
  it("renders nothing when disabled by the feature flag", () => {
    const { container } = render(
      <ColumnPicker
        visible={DEFAULT_VISIBLE}
        onToggle={vi.fn()}
        onReset={vi.fn()}
        enabled={false}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a Columns button and toggles the popover", async () => {
    const user = userEvent.setup();
    render(
      <ColumnPicker
        visible={DEFAULT_VISIBLE}
        onToggle={vi.fn()}
        onReset={vi.fn()}
      />,
    );
    const btn = screen.getByTestId("columns-btn");
    expect(screen.queryByTestId("columns-popover")).toBeNull();
    await user.click(btn);
    expect(screen.getByTestId("columns-popover")).toBeInTheDocument();
    await user.click(btn);
    expect(screen.queryByTestId("columns-popover")).toBeNull();
  });

  it("locked-on rows have disabled checkboxes and a lock icon", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <ColumnPicker
        visible={DEFAULT_VISIBLE}
        onToggle={onToggle}
        onReset={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId("columns-btn"));
    for (const id of LOCKED_ON) {
      const cb = screen.getByTestId(`col-checkbox-${id}`) as HTMLInputElement;
      expect(cb.disabled).toBe(true);
      expect(cb.checked).toBe(true);
      expect(screen.getByTestId(`col-lock-${id}`)).toBeInTheDocument();
    }
    // Attempting to click a disabled checkbox is a no-op.
    const cb = screen.getByTestId(`col-checkbox-${LOCKED_ON[0]}`);
    fireEvent.click(cb);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("clicking a non-locked checkbox invokes onToggle with the id", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <ColumnPicker
        visible={DEFAULT_VISIBLE}
        onToggle={onToggle}
        onReset={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId("columns-btn"));
    await user.click(screen.getByTestId("col-checkbox-status"));
    expect(onToggle).toHaveBeenCalledWith("status");
  });

  it("reset button invokes onReset and closes the popover", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    render(
      <ColumnPicker
        visible={DEFAULT_VISIBLE}
        onToggle={vi.fn()}
        onReset={onReset}
      />,
    );
    await user.click(screen.getByTestId("columns-btn"));
    await user.click(screen.getByTestId("reset-btn"));
    expect(onReset).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("columns-popover")).toBeNull();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(
      <ColumnPicker
        visible={DEFAULT_VISIBLE}
        onToggle={vi.fn()}
        onReset={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId("columns-btn"));
    expect(screen.getByTestId("columns-popover")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("columns-popover")).toBeNull();
  });
});
