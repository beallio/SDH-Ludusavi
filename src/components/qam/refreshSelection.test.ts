import { describe, it, expect } from "vitest";
import { resolveRefreshedSelection } from "./refreshSelection";

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
