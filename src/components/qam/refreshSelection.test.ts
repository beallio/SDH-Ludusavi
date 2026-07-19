import { describe, it, expect } from "vitest";
import {
  resolveAppliedSelection,
  resolveRefreshedSelection,
} from "./refreshSelection";

describe("resolveRefreshedSelection", () => {
  const games = [{ name: "A" }, { name: "B" }, { name: "C" }];

  it("returns preferred game when present", () => {
    const result = resolveRefreshedSelection({
      games,
      preferredGame: "B",
      currentSelectedGame: "A",
    });
    expect(result).toEqual({ source: "preferred", game: "B" });
  });

  it("returns current selection when preferred is absent but current is present", () => {
    const result = resolveRefreshedSelection({
      games,
      currentSelectedGame: "C",
    });
    expect(result).toEqual({ source: "preferred", game: "C" });
  });

  it("returns first game when target is absent", () => {
    const result = resolveRefreshedSelection({
      games,
      preferredGame: "D",
      currentSelectedGame: "E",
    });
    expect(result).toEqual({ source: "first", game: "A" });
  });

  it("returns none when list is empty", () => {
    const result = resolveRefreshedSelection({
      games: [],
      currentSelectedGame: "A",
    });
    expect(result).toEqual({ source: "none", game: "" });
  });
});

describe("resolveAppliedSelection", () => {
  const games = [{ name: "A" }, { name: "B" }];

  it("keeps a valid live selection ahead of the persisted preference", () => {
    expect(
      resolveAppliedSelection({
        games,
        preferredGame: "B",
        liveSelection: "A",
      }),
    ).toEqual({ source: "preferred", game: "A" });
  });

  it("uses the persisted preference when the live selection is empty", () => {
    expect(
      resolveAppliedSelection({
        games,
        preferredGame: "B",
        liveSelection: "",
      }),
    ).toEqual({ source: "preferred", game: "B" });
  });

  it("uses a valid persisted preference when the live selection is stale", () => {
    expect(
      resolveAppliedSelection({
        games,
        preferredGame: "B",
        liveSelection: "Z",
      }),
    ).toEqual({ source: "preferred", game: "B" });
  });

  it("falls back to the first game without a preference or live selection", () => {
    expect(
      resolveAppliedSelection({
        games,
        liveSelection: "",
      }),
    ).toEqual({ source: "first", game: "A" });
  });
});
