import { test, expect } from "@playwright/test";

test.use({ baseURL: process.env.RIFFROOM_TEST_URL ?? "http://127.0.0.1:8765" });

test("legacy open prepares once; playback works while pending and failed; only failure offers Retry", async ({ page }) => {
  const id = "b".repeat(32);
  const track = { id, title: "Legacy song", filename: "fixture.wav", duration: 4,
    created_at: "now", status: "idle", message: "", runs: [], active_run: null,
    peaks: [], error: null, beat_analysis: undefined as undefined | Record<string, unknown> };
  let preparations = 0;
  let retries = 0;
  const audio = Buffer.alloc(44 + 4 * 8000 * 2);
  audio.write("RIFF", 0); audio.writeUInt32LE(audio.length - 8, 4);
  audio.write("WAVEfmt ", 8); audio.writeUInt32LE(16, 16);
  audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
  audio.writeUInt32LE(8000, 24); audio.writeUInt32LE(16000, 28);
  audio.writeUInt16LE(2, 32); audio.writeUInt16LE(16, 34);
  audio.write("data", 36); audio.writeUInt32LE(audio.length - 44, 40);
  await page.route("**/api/models", route => route.fulfill({ json: [] }));
  await page.route("**/api/tracks", route => route.fulfill({ json: [track] }));
  await page.route(`**/api/tracks/${id}`, route => route.fulfill({ json: track }));
  await page.route(`**/api/tracks/${id}/original`, route => route.fulfill({ contentType: "audio/wav", body: audio }));
  await page.route(`**/api/tracks/${id}/beats/prepare`, route => {
    preparations++;
    track.beat_analysis = { status: "queued", error: null };
    return route.fulfill({ status: 202, json: track });
  });
  await page.route(`**/api/tracks/${id}/beats`, route => {
    retries++;
    track.beat_analysis = { status: "processing", error: null };
    return route.fulfill({ status: 202, json: track });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /Legacy song/ }).click();
  await expect(page.getByText("Beats queued…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analyze beats" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry beat analysis" })).toHaveCount(0);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /Legacy song/ }).click();
  await expect(page.getByText("Beats queued…", { exact: true })).toBeVisible();
  expect(preparations).toBe(1);
  track.beat_analysis = { status: "error", error: "Install beat tracking, then Retry." };
  await expect(page.getByRole("button", { name: "Retry beat analysis" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /Legacy song/ }).click();
  await expect(page.getByText("Install beat tracking, then Retry.")).toBeVisible();
  expect(preparations).toBe(1);
  expect(retries).toBe(0);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retry beat analysis" }).click();
  await expect(page.getByText("Analyzing beats…", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry beat analysis" })).toHaveCount(0);
  expect(retries).toBe(1);
});
