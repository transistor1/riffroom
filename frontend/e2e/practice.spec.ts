import { test, expect } from "@playwright/test";
import path from "node:path";

const modelWorkingSetKey = "riffroom:model-working-set:v1";

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.evaluate(
    (key) => localStorage.removeItem(key),
    modelWorkingSetKey,
  );
  await page.reload();
});

test.afterEach(async ({ page }) => {
  await page.evaluate(
    (key) => localStorage.removeItem(key),
    modelWorkingSetKey,
  );
});

test("portable allowlist models appear once without unvalidated MLX", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Model manager" }).click();
  const manager = page.getByRole("dialog", { name: "Model manager" });
  await manager.getByRole("button", { name: "Community" }).click();
  for (const modelName of [
    "MDX-Net Model: UVR-MDX-NET Inst HQ 5",
    "MDX23C Model: MDX23C DrumSep by aufr33-jarredou",
    "Roformer Model: Mel-Roformer-Karaoke-Aufr33-Viperx",
  ]) {
    await manager.getByLabel("Search models").fill(modelName);
    const card = manager.locator(".manager-model").filter({
      has: manager.getByRole("heading", { name: modelName }),
    });

    await expect(card).toHaveCount(1);
    await expect(card.getByText("mlx-audio-separator")).toHaveCount(0);
    await expect(
      card
        .locator("dl > div")
        .filter({ hasText: "Provider / runtime" })
        .locator("code"),
    ).toHaveText(/^(audio-separator|No runtime available)$/);
  }
});

test("portable-only model offers install only when no variant is usable", async ({
  page,
}) => {
  let available = false;
  let installing = false;
  let installAttempts = 0;
  let runtimeError: string | null = null;

  await page.route("**/api/runtimes/audio-separator", async (route) => {
    if (installing) {
      installing = false;
      if (installAttempts === 1) {
        runtimeError =
          "Portable runtime installation failed while installing the pinned package.";
      } else {
        available = true;
        runtimeError = null;
      }
    }
    await route.fulfill({
      json: {
        id: "audio-separator",
        display_name: "Portable audio-separator runtime",
        version: "0.47.0",
        available,
        managed_installed: available,
        installing,
        error: runtimeError,
      },
    });
  });
  await page.route("**/api/runtimes/audio-separator/install", async (route) => {
    installAttempts += 1;
    installing = true;
    runtimeError = null;
    await route.fulfill({
      status: 202,
      json: {
        id: "audio-separator",
        display_name: "Portable audio-separator runtime",
        version: "0.47.0",
        available: false,
        managed_installed: false,
        installing: true,
        error: null,
      },
    });
  });
  await page.route("**/api/models", async (route) => {
    const response = await route.fetch();
    const models = (await response.json()) as Array<{
      provider: string | null;
      provider_options: string[];
      compatibility: {
        platform_supported: boolean;
        runtime_available: boolean;
        compatible: boolean;
        label: string;
      };
    }>;
    for (const model of models) {
      if (!model.provider_options.includes("audio-separator")) continue;
      model.provider = available ? "audio-separator" : null;
      model.compatibility.platform_supported = true;
      model.compatibility.runtime_available = available;
      model.compatibility.compatible = available;
      model.compatibility.label = available
        ? "Compatible · macOS (Apple Silicon)"
        : "Runtime required · macOS (Apple Silicon)";
    }
    await route.fulfill({ response, json: models });
  });

  await page.reload();
  await page.getByRole("button", { name: "Model manager" }).click();
  const manager = page.getByRole("dialog", { name: "Model manager" });
  await manager.getByRole("button", { name: "Community" }).click();
  await manager.getByLabel("Search models").fill("UVR-MDX-NET Inst HQ 5");
  const pilot = manager.locator(".manager-model").filter({
    has: manager.getByRole("heading", {
      name: "MDX-Net Model: UVR-MDX-NET Inst HQ 5",
    }),
  });

  await expect(pilot.getByText("Portable runtime required")).toBeVisible();
  await expect(pilot.getByRole("button", { name: "Use model" })).toHaveCount(0);
  await pilot.getByRole("button", { name: "Install portable runtime" }).click();
  await expect(
    pilot.getByRole("button", { name: "Installing portable runtime…" }),
  ).toBeVisible();
  await expect(
    manager.getByText(
      "Portable runtime installation failed while installing the pinned package.",
    ),
  ).toBeVisible({ timeout: 5_000 });
  await pilot.getByRole("button", { name: "Install portable runtime" }).click();
  await expect(
    pilot.getByRole("button", { name: "Installing portable runtime…" }),
  ).toBeVisible();
  await expect(
    pilot.getByText("Compatible · macOS (Apple Silicon)"),
  ).toBeVisible({ timeout: 5_000 });
  await pilot.getByRole("button", { name: "Use model" }).click();
  await expect(manager).toBeHidden();
  await expect(page.getByText("Selected from Model Manager")).toBeVisible();
});

test("import, real separation, mixing, looping, model comparison and removal", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  const separationRequests: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/separate")) {
      separationRequests.push(request.url());
    }
  });
  await expect(page.getByRole("heading", { name: "Your song." })).toBeVisible();
  await page.getByRole("button", { name: "Model manager" }).click();
  const manager = page.getByRole("dialog", { name: "Model manager" });
  await expect(manager).toBeVisible();
  await expect(manager.locator(".manager-model")).toHaveCount(4);
  await expect(manager.getByText("mlx-audio-separator").first()).toBeVisible();
  await expect(
    manager.getByText("Demucs", { exact: true }).first(),
  ).toBeVisible();
  await expect(manager.getByText(/Compatible · macOS/).first()).toBeVisible();
  await expect(
    manager.getByText(/^(Prepared|Downloads on first use)$/).first(),
  ).toBeVisible();
  await expect(manager.getByText("Non-commercial terms")).toBeVisible();
  await expect(
    manager.getByText("Checkpoint terms unverified", { exact: true }),
  ).toBeVisible();
  await expect(
    manager.getByText("Community weights; redistribution terms unverified"),
  ).toBeVisible();
  await expect(
    manager.getByRole("link", { name: "Source for Demucs · 6 stems" }),
  ).toHaveAttribute("href", "https://github.com/facebookresearch/demucs");
  await manager.getByRole("button", { name: "Community" }).click();
  expect(await manager.locator(".manager-model").count()).toBeGreaterThan(4);
  await manager.getByLabel("Architecture filter").selectOption("MDXC");
  await manager.getByLabel("Search models").fill("DrumSep");
  await expect(manager.locator(".manager-model")).toHaveCount(1);
  const community = manager.locator(".manager-model").filter({
    has: manager.getByRole("heading", { name: /DrumSep/ }),
  });
  await expect(
    community.getByText("Checkpoint terms unverified", { exact: true }),
  ).toBeVisible();
  const communityName = await community.getByRole("heading").innerText();
  const communityVisibility = community.getByRole("checkbox", {
    name: "Show in separation menus",
  });
  await expect(communityVisibility).not.toBeChecked();
  await community.getByRole("button", { name: "Use model" }).click();
  await expect(manager).toBeHidden();
  await expect(page.getByText("Selected from Model Manager")).toBeVisible();
  await expect(page.locator(".model-card")).toHaveCount(4);
  expect(separationRequests).toEqual([]);
  await page.evaluate(
    (key) => localStorage.removeItem(key),
    modelWorkingSetKey,
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your song." })).toBeVisible();
  await page.getByRole("button", { name: "Model manager" }).click();
  const roformer = manager.locator(".manager-model").filter({
    has: manager.getByRole("heading", {
      name: "RoFormer · 6 stems",
      exact: true,
    }),
  });
  await roformer.getByRole("button", { name: "Use model" }).click();
  await expect(manager).toBeHidden();
  await expect(
    page.locator(".model-card.chosen").getByRole("heading", {
      name: "RoFormer · 6 stems",
      exact: true,
    }),
  ).toBeVisible();
  expect(separationRequests).toEqual([]);
  await page
    .locator(".model-card")
    .filter({
      has: page.getByRole("heading", { name: "Demucs · 6 stems", exact: true }),
    })
    .click();
  await expect(
    page.getByRole("button", { name: /Guitar specialist/ }),
  ).toBeVisible();
  await page.screenshot({ path: "../data/qa-welcome.png", fullPage: true });
  await page
    .locator("input[type=file]")
    .setInputFiles(path.resolve("../data/smoke/practice-check.wav"));
  await expect(
    page.getByRole("heading", { name: "practice-check", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Stem mixer", exact: true }),
  ).toBeVisible({ timeout: 120_000 });
  await expect(
    page.getByRole("button", { name: "Play", exact: true }),
  ).toBeEnabled();
  const separationModel = page.getByLabel("Separation model", {
    exact: true,
  });
  await expect(
    separationModel.locator("option").filter({ hasText: communityName }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Manage models" }).click();
  await manager.getByRole("button", { name: "Community" }).click();
  await manager.getByLabel("Search models").fill("DrumSep");
  await expect(communityVisibility).not.toBeChecked();
  await community.getByRole("button", { name: "Use model" }).click();
  await expect(manager).toBeHidden();
  await expect(
    separationModel.locator("option").filter({ hasText: communityName }),
  ).toHaveCount(1);
  const communityModelId = await separationModel
    .locator("option")
    .filter({ hasText: communityName })
    .getAttribute("value");
  expect(communityModelId).not.toBeNull();
  await expect(separationModel).toHaveValue(communityModelId!);
  await page.getByRole("button", { name: "Manage models" }).click();
  await communityVisibility.uncheck();
  await manager.getByRole("button", { name: "Close model manager" }).click();
  await expect(
    separationModel.locator("option").filter({ hasText: communityName }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Manage models" }).click();
  await manager.getByLabel("Search models").fill("");
  await manager.getByRole("button", { name: "Curated" }).click();
  const runModel = manager.locator(".manager-model").filter({
    has: manager.getByRole("heading", {
      name: "Demucs · 6 stems",
      exact: true,
    }),
  });
  await runModel
    .getByRole("checkbox", { name: "Show in separation menus" })
    .uncheck();
  await manager.getByRole("button", { name: "Close model manager" }).click();
  await expect(
    separationModel.locator("option").filter({
      hasText: "Demucs · 6 stems",
    }),
  ).toHaveCount(0);
  await expect(
    page
      .getByLabel("Separation result")
      .locator("option")
      .filter({ hasText: "Demucs · 6 stems" }),
  ).toHaveCount(1);
  await page.getByRole("slider", { name: "Pitch", exact: true }).fill("2");
  await expect(
    page.getByRole("slider", { name: "Pitch", exact: true }),
  ).toHaveValue("2");
  const exactPitch = page.getByRole("spinbutton", {
    name: "Exact pitch in semitones",
  });
  await exactPitch.fill("99");
  await exactPitch.press("Tab");
  await expect(exactPitch).toHaveValue("12.0");
  await expect(
    page.getByRole("slider", { name: "Pitch", exact: true }),
  ).toHaveValue("12");
  await exactPitch.fill("-3.7");
  await exactPitch.press("Enter");
  await expect(
    page.getByRole("slider", { name: "Pitch", exact: true }),
  ).toHaveValue("-3.7");
  await page.getByRole("button", { name: "Reset pitch to zero" }).click();
  await expect(exactPitch).toHaveValue("0.0");
  await expect(
    page.getByRole("slider", { name: "Pitch", exact: true }),
  ).toHaveValue("0");
  await page.getByRole("button", { name: "Play guitar with the band" }).click();
  await expect(
    page.getByRole("button", { name: "Mute guitar" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Hear just the guitar" }).click();
  await expect(
    page.getByRole("button", { name: "Solo guitar" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "Mute guitar" }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Reset mix" }).click();
  await page
    .getByRole("slider", { name: "guitar volume", exact: true })
    .fill("0.42");
  await page.getByRole("button", { name: "Mute vocals" }).click();
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Pause", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".time strong")).toHaveText("0:01", {
    timeout: 5000,
  });
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const mainSeek = page.getByRole("slider", { name: "Seek", exact: true });
  await page
    .getByRole("slider", { name: "Seek guitar", exact: true })
    .fill("2");
  await expect(mainSeek).toHaveValue("2");
  await page.getByTitle("Set loop start at playhead").click();
  await mainSeek.fill("4");
  await page.getByTitle("Set loop end at playhead").click();
  await page.getByRole("button", { name: "Loop", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Loop", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.waitForTimeout(3000);
  const pos = Number(await mainSeek.inputValue());
  expect(pos).toBeGreaterThanOrEqual(2);
  expect(pos).toBeLessThan(4);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  const href = await page
    .getByRole("link", { name: "Download guitar" })
    .getAttribute("href");
  const response = await request.get(href!);
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("audio/wav");
  await page.screenshot({ path: "../data/qa-mixer.png", fullPage: true });
  await page.reload();
  await page.getByRole("button", { name: /practice-check/ }).click();
  await expect(
    page
      .getByLabel("Separation model", { exact: true })
      .locator("option")
      .filter({ hasText: "Demucs · 6 stems" }),
  ).toHaveCount(0);
  await expect(
    page
      .getByLabel("Separation result")
      .locator("option")
      .filter({ hasText: "Demucs · 6 stems" }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("slider", { name: "guitar volume", exact: true }),
  ).toHaveValue("0.42");
  await expect(
    page.getByRole("button", { name: "Mute vocals" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("Separation result").selectOption("original");
  await expect(
    page.getByRole("heading", { name: "Original track", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Separation result").selectOption({ index: 1 });
  await page
    .getByLabel("Separation model", { exact: true })
    .selectOption("roformer-6");
  await page
    .getByRole("button", { name: "Separate track", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Separate track", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("heading", { name: "Stem mixer", exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../data/qa-mobile.png", fullPage: true });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "Delete separation result", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Remove this separation result?" }),
  ).toBeVisible();
  await expect(
    page.getByText(/original audio and other separation results will remain/i),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Stem mixer", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Remove result", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Original track", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Separation result")).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Delete separation result",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Delete track", exact: true }).click();
  await page.getByRole("button", { name: "Remove track", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your song." })).toBeVisible();
  expect(errors).toEqual([]);
});
