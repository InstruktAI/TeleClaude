// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PlainTextContent } from "../PlainTextContent";

describe("PlainTextContent", () => {
  it("preserves raw line breaks via pre-wrap styling", () => {
    const props = {
      text: "first line\n\nsecond paragraph",
      status: { type: "complete" },
    } as any;

    render(
      <PlainTextContent {...props} />,
    );

    const content = screen.getByText(/first line/);
    expect(content.className).toContain("whitespace-pre-wrap");
    expect(content.textContent).toContain("first line");
    expect(content.textContent).toContain("second paragraph");
  });
});
