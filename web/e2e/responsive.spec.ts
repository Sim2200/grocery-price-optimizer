import { test, expect } from "@playwright/test";

const widths = [360, 390, 768, 1024, 1440];
const pages = ["/", "/upload", "/receipts", "/prices", "/insights", "/plan"];

for (const width of widths) {
  for (const page of pages) {
    const testName = `${page === "/" ? "home" : page.replace(/^\//, "")} at ${width}px`;

    test(`${page} at ${width}px`, async ({ page: testPage }) => {
      await testPage.setViewportSize({ width, height: 800 });
      await testPage.goto(page);
      await testPage.waitForLoadState("networkidle");

      const result = await testPage.evaluate((innerWidth) => {
        const overflowing: string[] = [];
        document.querySelectorAll("*").forEach((el) => {
          const rect = el.getBoundingClientRect();
          if (rect.right > innerWidth + 1) {
            let skip = false;
            let parent = el.parentElement;
            while (parent) {
              const style = window.getComputedStyle(parent);
              if (
                style.overflowX === "auto" ||
                style.overflowX === "scroll" ||
                style.overflowX === "hidden"
              ) {
                skip = true;
                break;
              }
              parent = parent.parentElement;
            }
            if (!skip && !el.classList.contains("sr-only")) {
              const tag = el.tagName.toLowerCase();
              const classes = el.className ? `.${el.className.split(" ").join(".")}` : "";
              const text = el.textContent?.substring(0, 30) || "";
              overflowing.push(`${tag}${classes} "${text}"`);
            }
          }
        });
        return {
          scrollWidth: document.documentElement.scrollWidth,
          overflowing: overflowing.slice(0, 5),
        };
      }, width);

      expect(result.scrollWidth).toBeLessThanOrEqual(width);
      if (result.overflowing.length > 0) {
        throw new Error(
          `${testName}: Elements overflow viewport:\n${result.overflowing.join("\n")}`
        );
      }

      await testPage.screenshot({
        path: `e2e/screenshots/${width}/${testName}.png`,
        fullPage: true,
      });
    });
  }
}
