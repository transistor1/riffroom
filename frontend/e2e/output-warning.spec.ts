import { expect, test } from "@playwright/test";

test.use({ baseURL: process.env.RIFFROOM_TEST_URL ?? "http://127.0.0.1:8765" });

test("output warning persists with the affected selected take across reloads", async ({ page }) => {
  const id = "e".repeat(32);
  const warning = "The separation model's output differed from what Riffroom expected. The results are available using their output filenames. This may indicate a model compatibility mismatch. Please notify the developer.";
  const stems = (names: string[]) => names.map(name => ({
    name, file: `${name}.wav`, url: "/fixture.wav", peaks: [0.2],
  }));
  const track = {
    id, title: "Unexpected outputs", filename: "source.wav", duration: 4,
    created_at: "now", status: "ready", message: "Ready to practice", error: null,
    active_run: "affected", peaks: [0.2],
    beat_analysis: { status: "error", error: "Beat tracking unavailable." },
    runs: [
      { id: "affected", model_id: "roformer-vocals", take_number: 1,
        source: { type: "original" }, stems: stems(["vocals", "hiccup", "third output"]),
        output_warning: { code: "unexpected_model_outputs", message: warning,
          expected_stems: ["vocals", "instrumental"],
          actual_files: ["vocals.wav", "hiccup.wav", "third output.wav"] } },
      { id: "clean", model_id: "roformer-vocals", take_number: 2,
        source: { type: "original" }, stems: stems(["vocals", "instrumental"]) },
    ],
  };
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
  await page.route("**/fixture.wav", route => route.fulfill({ contentType: "audio/wav", body: audio }));
  await page.route(`**/api/tracks/${id}/original`, route => route.fulfill({ contentType: "audio/wav", body: audio }));
  await page.goto("/");
  await page.getByRole("button", { name: /Unexpected outputs/ }).click();
  const notice = page.locator(".output-warning");
  const select = page.getByRole("combobox", { name: "Separation result" });
  await expect(notice).toContainText(warning);
  await expect(notice).toContainText("Expected: vocals, instrumental");
  await expect(notice).toContainText("Actual: vocals.wav, hiccup.wav, third output.wav");
  await expect(page.locator(".stem-row")).toHaveCount(3);
  await expect(page.getByRole("slider", { name: "hiccup volume", exact: true })).toBeVisible();
  await page.getByRole("slider", { name: "hiccup volume", exact: true }).press("Home");
  await page.getByRole("slider", { name: "hiccup volume", exact: true }).press("ArrowRight");
  await expect(page.getByRole("slider", { name: "hiccup volume", exact: true })).toHaveValue("0.01");
  const mute = page.getByRole("button", { name: "Mute hiccup", exact: true });
  await mute.click();
  await expect(mute).toHaveAttribute("aria-pressed", "true");
  await mute.click();
  const solo = page.getByRole("button", { name: "Solo hiccup", exact: true });
  await solo.click();
  await expect(solo).toHaveAttribute("aria-pressed", "true");
  await solo.click();
  await expect(page.getByRole("link", { name: "Download hiccup", exact: true })).toHaveAttribute("href", "/fixture.wav");
  await select.selectOption("clean");
  await expect(notice).toHaveCount(0);
  await select.selectOption("original");
  await expect(notice).toHaveCount(0);
  await select.selectOption("affected");
  await expect(notice).toContainText(warning);
  await page.reload();
  await page.getByRole("button", { name: /Unexpected outputs/ }).click();
  await expect(notice).toContainText(warning);
  await expect(page.locator(".stem-row")).toHaveCount(3);
});
