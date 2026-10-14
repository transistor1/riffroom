import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const fixture = (name: string) => JSON.parse(readFileSync(
  new URL(`../../backend/tests/fixtures/${name}`, import.meta.url), "utf8",
));
const easyLover = fixture("easy_lover_approved_groove.json");
const easyLoverCorrection = fixture("easy_lover_correction.json");
const reelin = fixture("reelin_original_grid.json");

test.use({ baseURL: process.env.RIFFROOM_TEST_URL ?? "http://127.0.0.1:8765" });

for (const [title, fixture, status] of [
  ["Easy Lover", easyLover, "applied"], ["Reelin", reelin, "no_confident_repair"],
] as const) {
  test(`${title}: correction opt-in, reversible live switching, remembered per song and explicit failure`, async ({ page }) => {
    const id = "a".repeat(32);
    const track = { id, title, filename: "fixture.wav", duration: 400, created_at: "now",
      status: "ready", message: "", runs: [], active_run: null, peaks: [], error: null,
      beat_analysis: fixture.source_analysis };
    let fail = false;
    let holdCorrection = true;
    let releaseCorrection: (() => void) | undefined;
    let correctionRequests = 0;
    const forbidden: string[] = [];
    page.on("request", request => {
      if (request.method() !== "GET") forbidden.push(request.method() + " " + request.url());
    });
    const sampleRate = 8000;
    const audio = Buffer.alloc(44 + track.duration * sampleRate * 2);
    audio.write("RIFF", 0); audio.writeUInt32LE(audio.length - 8, 4);
    audio.write("WAVEfmt ", 8); audio.writeUInt32LE(16, 16);
    audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22);
    audio.writeUInt32LE(sampleRate, 24); audio.writeUInt32LE(sampleRate * 2, 28);
    audio.writeUInt16LE(2, 32); audio.writeUInt16LE(16, 34);
    audio.write("data", 36); audio.writeUInt32LE(audio.length - 44, 40);
    await page.route("**/api/models", route => route.fulfill({ json: [] }));
    await page.route("**/api/runtimes/audio-separator", route => route.fulfill({ json: { available: false } }));
    await page.route("**/api/tracks", route => route.fulfill({ json: [track] }));
    await page.route(`**/api/tracks/${id}`, route => route.fulfill({ json: track }));
    await page.route(`**/api/tracks/${id}/original`, route => route.fulfill({ contentType: "audio/wav", body: audio }));
    await page.route(`**/api/tracks/${id}/beats/correction`, async route => {
      correctionRequests++;
      if (holdCorrection) await new Promise<void>(resolve => { releaseCorrection = resolve; });
      return route.fulfill(fail ? { status: 422, json: { detail: "Experimental correction failed." } }
        : { json: { status, source_analysis: track.beat_analysis,
          grid: title === "Easy Lover" ? easyLoverCorrection.grid : track.beat_analysis } });
    });
    await page.goto("/");
    await page.getByRole("button", { name: new RegExp(title) }).click();
    const toggle = page.getByRole("button", { name: "Beat correction", exact: true });
    await expect(toggle).toBeDisabled();
    await expect(toggle).toHaveAttribute("aria-description", "Preparing correction; source grid in use.");
    await expect.poll(() => !!releaseCorrection).toBe(true);
    holdCorrection = false;
    releaseCorrection!();
    releaseCorrection = undefined;
    await expect(toggle).toBeEnabled();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await page.getByLabel("Count-in", { exact: false }).selectOption("1");
    await page.getByRole("button", { name: "Click", exact: true }).click();
    await toggle.click();
    await expect(toggle).toHaveAttribute("title", status === "applied"
      ? "Beat repair applied." : "No confident repair; source grid unchanged.");
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect(toggle).toHaveClass(/selected/);
    await expect(page.getByLabel("Beat click controls").locator("small")).toHaveCount(0);
    await page.getByRole("button", { name: "Play", exact: true }).click();
    await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
    // Use the actual waveform seek control during SoundTouch playback. Each
    // seek must yield to both timers and animation frames without a refresh.
    for (const enabled of [true, false]) {
      if (await toggle.getAttribute("aria-pressed") !== String(enabled)) await toggle.click();
      const seek = page.getByRole("slider", { name: "Seek", exact: true });
      await seek.fill("100.15");
      for (const fraction of [0.55, 0.25, 0.95, 0.01]) {
        const box = await seek.boundingBox();
        expect(box).not.toBeNull();
        await seek.click({ position: { x: box!.width * fraction, y: box!.height / 2 } });
        await expect.poll(async () => Number(await seek.inputValue())).toBeGreaterThan(track.duration * fraction - 5);
        await expect.poll(async () => Number(await seek.inputValue())).toBeLessThan(track.duration * fraction + 5);
        await page.evaluate(() => new Promise<void>(resolve => {
          setTimeout(() => requestAnimationFrame(() => resolve()), 0);
        }));
        await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
      }
    }
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(correctionRequests).toBe(1); // on/off is local; no inference or requests
    holdCorrection = true;
    await page.reload();
    await page.getByRole("button", { name: new RegExp(title) }).click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect(toggle).toBeEnabled();
    await expect(toggle).toHaveAttribute("aria-description", /Preparing correction; click and count-in unavailable/);
    await expect(page.getByLabel("Beat click controls").locator("small")).toHaveCount(0);
    await expect.poll(() => !!releaseCorrection).toBe(true);
    holdCorrection = false;
    releaseCorrection!();
    releaseCorrection = undefined;
    await expect(toggle).toHaveAttribute("title", status === "applied"
      ? "Beat repair applied." : "No confident repair; source grid unchanged.");
    fail = true;
    await page.reload();
    await page.getByRole("button", { name: new RegExp(title) }).click();
    await expect(toggle).toHaveAttribute("title", /Correction failed:.*Click and count-in unavailable/);
    await expect(toggle).toHaveAttribute("aria-description", /Correction failed:.*turn correction off or retry/);
    await expect(page.getByRole("button", { name: "Retry correction" })).toBeVisible();
    await expect(page.getByLabel("Beat click controls").locator("small")).toHaveCount(0);
    await toggle.click();
    await expect(toggle).toHaveAttribute("title", /Correction failed:.*Source grid in use; retry available/);
    await expect(toggle).not.toHaveClass(/selected/);
    fail = false;
    await page.getByRole("button", { name: "Retry correction" }).click();
    await expect(toggle).toBeEnabled();
    await expect(toggle).toHaveAttribute("title", "Correction off; source grid in use.");
    await expect(page.getByRole("button", { name: "Retry correction" })).toHaveCount(0);
    expect(forbidden).toEqual([]);
  });
}
