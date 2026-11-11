import { expect, test, type Page } from "@playwright/test";

test.use({ baseURL: process.env.RIFFROOM_TEST_URL ?? "http://127.0.0.1:8765" });

async function fixture(page: Page) {
  const id = "c".repeat(32);
  const track = {
    id, title: "Original song", filename: "original-file.wav", duration: 4,
    created_at: "now", status: "ready", message: "Ready", error: null,
    active_run: "run", next_take_number: 4, peaks: [0.2],
    runs: [{ id: "run", take_number: 3, model_id: "demucs-6",
      source: { type: "original" },
      stems: [{ name: "guitar", file: "guitar.wav", url: "/fixture.wav", peaks: [0.2] }] }],
    practice: { loops: [{ id: "intro", name: "Intro", a: 1, b: 2, enabled: true }] },
    beat_analysis: { status: "error", error: "Beat tracking unavailable." },
  };
  const other = { ...track, id: "d".repeat(32), title: "Another song" };
  let libraryReads = 0;
  let audioReads = 0;
  const writes: unknown[] = [];
  const audio = Buffer.alloc(44 + 4 * 8000 * 2);
  audio.write("RIFF", 0); audio.writeUInt32LE(audio.length - 8, 4);
  audio.write("WAVEfmt ", 8); audio.writeUInt32LE(16, 16);
  audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
  audio.writeUInt32LE(8000, 24); audio.writeUInt32LE(16000, 28);
  audio.writeUInt16LE(2, 32); audio.writeUInt16LE(16, 34);
  audio.write("data", 36); audio.writeUInt32LE(audio.length - 44, 40);
  await page.route("**/api/models", route => route.fulfill({ json: [] }));
  await page.route("**/api/tracks", route => {
    libraryReads++;
    return route.fulfill({ json: [track, other] });
  });
  for (const item of [track, other]) {
    await page.route(`**/api/tracks/${item.id}`, route => route.fulfill({ json: item }));
  }
  await page.route("**/fixture.wav", route => {
    audioReads++;
    return route.fulfill({ contentType: "audio/wav", body: audio });
  });
  await page.route(`**/api/tracks/${id}/title`, route => {
    expect(route.request().method()).toBe("PUT");
    const body = route.request().postDataJSON();
    writes.push(body);
    track.title = body.title;
    return route.fulfill({ json: track });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Original song/ }).click();
  await expect(page.getByRole("button", { name: "Play", exact: true })).toBeEnabled();
  return { track, writes, libraryReads: () => libraryReads, audioReads: () => audioReads };
}

test("title persists in heading and library; polling preserves drafts, mix, loops and takes", async ({ page }) => {
  const state = await fixture(page);
  const before = structuredClone(state.track);
  await page.getByRole("slider", { name: "guitar volume", exact: true }).fill("0.42");
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  const input = page.getByRole("textbox", { name: "Song title", exact: true });
  await expect(input).toBeFocused();
  expect(await input.evaluate((element: HTMLInputElement) =>
    [element.selectionStart, element.selectionEnd])).toEqual([0, before.title.length]);
  await input.fill("  My renamed song 🎸  ");
  const reads = state.libraryReads();
  await expect.poll(state.libraryReads).toBeGreaterThan(reads);
  await expect(input).toHaveValue("  My renamed song 🎸  ");
  await expect(input).toBeFocused();
  const audioReads = state.audioReads();
  await input.press("Enter");
  await expect(page.getByRole("heading", { name: "My renamed song 🎸", exact: true })).toBeVisible();
  await expect(page.locator(".library-track strong").first()).toHaveText("My renamed song 🎸");
  await expect(page.locator(".topbar strong")).toHaveText("My renamed song 🎸");
  await expect(page.getByRole("button", { name: "Edit title", exact: true })).toBeFocused();
  expect(state.writes).toEqual([{ title: "My renamed song 🎸" }]);
  expect(state.track).toEqual({ ...before, title: "My renamed song 🎸" });
  await expect(page.getByRole("slider", { name: "guitar volume", exact: true })).toHaveValue("0.42");
  await expect(page.getByTestId("loop-region")).toHaveText(["1. Intro"]);
  await expect(page.getByLabel("Separation result")).toHaveValue("run");
  expect(state.audioReads()).toBe(audioReads);
  await page.reload();
  await expect(page.locator(".library-track strong").first()).toHaveText("My renamed song 🎸");
  await page.getByRole("button", { name: /My renamed song/ }).click();
  await expect(page.getByRole("heading", { name: "My renamed song 🎸", exact: true })).toBeVisible();
  await expect(page.getByRole("slider", { name: "guitar volume", exact: true })).toHaveValue("0.42");
  // Search uses the persisted display title too.
  await page.getByRole("searchbox", { name: "Search songs" }).fill("renamed");
  await expect(page.locator(".library-track")).toHaveCount(1);
});

test("invalid titles and failed saves retain editing; Cancel and Escape discard drafts", async ({ page }) => {
  const state = await fixture(page);
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  const input = page.getByRole("textbox", { name: "Song title", exact: true });
  for (const invalid of ["   ", "x".repeat(201), "🎸".repeat(201)]) {
    await input.fill(invalid);
    await page.getByRole("button", { name: "Save title", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveText("Enter a title between 1 and 200 characters.");
    await expect(input).toHaveValue(invalid);
  }
  expect(state.writes).toEqual([]);
  await input.press("Escape");
  await expect(page.getByRole("heading", { name: "Original song", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  await input.fill("Discard me");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  await expect(input).toHaveValue("Original song");
  await input.fill("Try again");
  await page.route(`**/api/tracks/${state.track.id}/title`, async route => {
    await route.fulfill({ status: 500, json: { detail: "Could not write title." } });
  }, { times: 1 });
  await input.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("Could not write title.");
  await expect(input).toHaveValue("Try again");
  await expect(page.locator(".library-track strong").first()).toHaveText("Original song");
  const reads = state.libraryReads();
  await expect.poll(state.libraryReads).toBeGreaterThan(reads);
  await expect(page.getByRole("alert")).toHaveText("Could not write title.");
  await expect(input).toHaveValue("Try again");
  await page.getByRole("button", { name: "Save title", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Try again", exact: true })).toBeVisible();
  expect(state.writes).toEqual([{ title: "Try again" }]);
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  await input.fill("Unrelated draft");
  await page.getByRole("button", { name: /Another song/ }).click();
  await expect(input).toHaveCount(0);
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  await expect(input).toHaveValue("Another song");
});

test("an older library response cannot revert a successful rename", async ({ page }) => {
  const state = await fixture(page);
  const old = structuredClone(state.track);
  let release: () => void = () => {};
  let held = false;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/tracks", async route => {
    held = true;
    await gate;
    await route.fulfill({ json: [old] });
  }, { times: 1 });
  await expect.poll(() => held).toBe(true);
  await page.getByRole("button", { name: "Edit title", exact: true }).click();
  await page.getByRole("textbox", { name: "Song title", exact: true }).fill("Saved title");
  await page.getByRole("button", { name: "Save title", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Saved title", exact: true })).toBeVisible();
  const response = page.waitForResponse(result => result.url().endsWith("/api/tracks"));
  release();
  await response;
  await expect(page.getByRole("heading", { name: "Saved title", exact: true })).toBeVisible();
  await expect(page.locator(".library-track strong").first()).toHaveText("Saved title");
});
