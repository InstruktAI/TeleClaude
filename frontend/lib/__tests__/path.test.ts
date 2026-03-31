import { afterEach, describe, expect, it } from "vitest";
import { replaceHomeWithTilde } from "@/lib/utils/path";

const ORIGINAL_HOME = process.env.HOME;
const ORIGINAL_USERPROFILE = process.env.USERPROFILE;

describe("replaceHomeWithTilde", () => {
  afterEach(() => {
    process.env.HOME = ORIGINAL_HOME;
    process.env.USERPROFILE = ORIGINAL_USERPROFILE;
  });

  it("replaces a macOS home prefix with a tilde", () => {
    process.env.HOME = "/Users/Morriz";

    expect(
      replaceHomeWithTilde("/Users/Morriz/Workspace/InstruktAI/TeleClaude"),
    ).toBe("~/Workspace/InstruktAI/TeleClaude");
  });

  it("ignores a root HOME value and still recognizes the real macOS home prefix", () => {
    process.env.HOME = "/";

    expect(
      replaceHomeWithTilde("/Users/Morriz/Workspace/InstruktAI/TeleClaude"),
    ).toBe("~/Workspace/InstruktAI/TeleClaude");
  });

  it("leaves already-tilde-prefixed paths unchanged", () => {
    expect(replaceHomeWithTilde("~/Workspace/InstruktAI/TeleClaude")).toBe(
      "~/Workspace/InstruktAI/TeleClaude",
    );
  });
});
