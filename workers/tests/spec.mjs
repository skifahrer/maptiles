import { createRequire } from "node:module";

/** The MapLibre style spec, or null; not checked in, the job installs it under STYLE_SPEC_DIR. */
export function styleSpec() {
  const require = createRequire(import.meta.url);
  const paths = [process.env.STYLE_SPEC_DIR, process.cwd()].filter(Boolean);
  try {
    return require(require.resolve("@maplibre/maplibre-gl-style-spec", { paths }));
  } catch (err) {
    if (process.env.TESTS_REQUIRE_ALL === "1") throw err;
    return null;
  }
}

export const NEEDS_SPEC = "needs @maplibre/maplibre-gl-style-spec";
