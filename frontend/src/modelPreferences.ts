import type { Model } from "./types";

export const MODEL_WORKING_SET_STORAGE_KEY = "riffroom:model-working-set:v1";

type PreferenceStorage = Pick<Storage, "getItem" | "setItem">;

export type ModelVisibilityResult = {
  visibleModelIds: string[];
  error?: string;
};

const compatibleIds = (models: Model[]) =>
  new Set(
    models
      .filter((model) => model.compatibility.compatible)
      .map((model) => model.id),
  );

export function defaultVisibleModelIds(models: Model[]) {
  const curated = models
    .filter((model) => model.curated && model.compatibility.compatible)
    .map((model) => model.id);
  if (curated.length) return curated;
  const fallback = models.find((model) => model.compatibility.compatible);
  return fallback ? [fallback.id] : [];
}

export function validateVisibleModelIds(
  value: unknown,
  models: Model[],
): string[] {
  if (!Array.isArray(value)) return defaultVisibleModelIds(models);
  const compatible = compatibleIds(models);
  const visible = Array.from(
    new Set(
      value.filter(
        (modelId): modelId is string =>
          typeof modelId === "string" && compatible.has(modelId),
      ),
    ),
  );
  return visible.length ? visible : defaultVisibleModelIds(models);
}

function browserStorage(): PreferenceStorage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function saveVisibleModelIds(
  visibleModelIds: string[],
  storage: PreferenceStorage | undefined = browserStorage(),
) {
  try {
    storage?.setItem(
      MODEL_WORKING_SET_STORAGE_KEY,
      JSON.stringify(visibleModelIds),
    );
  } catch {
    // Browser privacy settings and full/corrupt storage must not block use.
  }
}

export function loadVisibleModelIds(
  models: Model[],
  storage: PreferenceStorage | undefined = browserStorage(),
) {
  const fallback = defaultVisibleModelIds(models);
  if (!storage) return fallback;
  let raw: string | null;
  try {
    raw = storage.getItem(MODEL_WORKING_SET_STORAGE_KEY);
  } catch {
    return fallback;
  }
  if (raw === null) return fallback;
  try {
    const visibleModelIds = validateVisibleModelIds(JSON.parse(raw), models);
    saveVisibleModelIds(visibleModelIds, storage);
    return visibleModelIds;
  } catch {
    saveVisibleModelIds(fallback, storage);
    return fallback;
  }
}

export function setModelVisibility(
  currentVisibleModelIds: string[],
  modelId: string,
  visible: boolean,
  models: Model[],
): ModelVisibilityResult {
  const current = validateVisibleModelIds(currentVisibleModelIds, models);
  const compatible = compatibleIds(models);
  if (!compatible.has(modelId)) return { visibleModelIds: current };
  if (visible) {
    return {
      visibleModelIds: current.includes(modelId)
        ? current
        : [...current, modelId],
    };
  }
  if (!current.includes(modelId)) return { visibleModelIds: current };
  if (current.length === 1) {
    return {
      visibleModelIds: current,
      error: "Keep at least one compatible model shown in separation menus.",
    };
  }
  return {
    visibleModelIds: current.filter((visibleId) => visibleId !== modelId),
  };
}

export function ensureModelVisible(
  currentVisibleModelIds: string[],
  modelId: string,
  models: Model[],
) {
  return setModelVisibility(currentVisibleModelIds, modelId, true, models)
    .visibleModelIds;
}
