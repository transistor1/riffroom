import { describe, expect, it, vi } from "vitest";
import type { Model } from "./types";
import {
  MODEL_WORKING_SET_STORAGE_KEY,
  defaultVisibleModelIds,
  ensureModelVisible,
  loadVisibleModelIds,
  setModelVisibility,
} from "./modelPreferences";

const model = (id: string, { curated = true, compatible = true } = {}) =>
  ({
    id,
    curated,
    compatibility: { compatible },
  }) as Model;

const models = [
  model("curated-one"),
  model("curated-two"),
  model("community-one", { curated: false }),
  model("unavailable", { compatible: false }),
];

function memoryStorage(initial?: unknown) {
  const values = new Map<string, string>();
  if (initial !== undefined) {
    values.set(MODEL_WORKING_SET_STORAGE_KEY, JSON.stringify(initial));
  }
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
    value: () => values.get(MODEL_WORKING_SET_STORAGE_KEY),
  };
}

describe("model working-set preferences", () => {
  it("shows compatible curated models by default", () => {
    expect(defaultVisibleModelIds(models)).toEqual([
      "curated-one",
      "curated-two",
    ]);
  });

  it("validates persisted IDs and removes stale or incompatible entries", () => {
    const storage = memoryStorage([
      "community-one",
      "removed-model",
      "unavailable",
      "community-one",
    ]);
    expect(loadVisibleModelIds(models, storage)).toEqual(["community-one"]);
    expect(storage.value()).toBe('["community-one"]');
  });

  it("falls back safely for corrupt, empty, or unavailable storage", () => {
    const corrupt = memoryStorage();
    corrupt.getItem.mockReturnValue("not-json");
    expect(loadVisibleModelIds(models, corrupt)).toEqual([
      "curated-one",
      "curated-two",
    ]);
    expect(loadVisibleModelIds(models, memoryStorage([]))).toEqual([
      "curated-one",
      "curated-two",
    ]);
    expect(
      loadVisibleModelIds(models, {
        getItem: () => {
          throw new Error("storage disabled");
        },
        setItem: vi.fn(),
      }),
    ).toEqual(["curated-one", "curated-two"]);
  });

  it("hides and shows compatible models", () => {
    const hidden = setModelVisibility(
      ["curated-one", "curated-two"],
      "curated-two",
      false,
      models,
    );
    expect(hidden).toEqual({ visibleModelIds: ["curated-one"] });
    expect(
      setModelVisibility(hidden.visibleModelIds, "curated-two", true, models),
    ).toEqual({ visibleModelIds: ["curated-one", "curated-two"] });
  });

  it("adds a hidden community model when it is explicitly used", () => {
    expect(
      ensureModelVisible(["curated-one"], "community-one", models),
    ).toEqual(["curated-one", "community-one"]);
  });

  it("refuses to hide the last compatible visible model", () => {
    expect(
      setModelVisibility(["community-one"], "community-one", false, models),
    ).toEqual({
      visibleModelIds: ["community-one"],
      error: "Keep at least one compatible model shown in separation menus.",
    });
  });
});
