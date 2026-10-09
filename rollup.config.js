import { readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import commonjs from "@rollup/plugin-commonjs";
import json from "@rollup/plugin-json";
import { nodeResolve } from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import typescript from "@rollup/plugin-typescript";
import externalGlobals from "rollup-plugin-external-globals";
import importAssets from "rollup-plugin-import-assets";

const projectRoot = dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(readFileSync(join(projectRoot, "plugin.json"), "utf-8"));
const distDirectory = join(projectRoot, "dist");

export default {
  input: "./src/index.tsx",
  plugins: [
    {
      name: "clean-generated-dist",
      buildStart() {
        rmSync(distDirectory, { recursive: true, force: true });
      },
    },
    // Tests are typechecked separately; their peer-library source imports must
    // not widen this production compiler program's emitted file paths.
    typescript({ exclude: ["**/*.test.ts", "**/*.test.tsx"] }),
    json(),
    commonjs(),
    nodeResolve({ browser: true }),
    externalGlobals({
      react: "SP_REACT",
      "react/jsx-runtime": "SP_JSX",
      "react-dom": "SP_REACTDOM",
      "@decky/ui": "DFL",
      "@decky/manifest": JSON.stringify(manifest),
    }),
    replace({
      preventAssignment: false,
      "process.env.NODE_ENV": JSON.stringify(process.env.NODE_ENV || "production"),
    }),
    importAssets({
      publicPath: `http://127.0.0.1:1337/plugins/${manifest.name}/`,
    }),
  ],
  context: "window",
  external: ["react", "react-dom", "@decky/ui"],
  treeshake: {
    pureExternalImports: {
      pure: ["@decky/ui", "@decky/api"],
    },
    preset: "smallest",
  },
  output: {
    dir: "dist",
    format: "esm",
    sourcemap: true,
    sourcemapPathTransform: (relativeSourcePath) => relativeSourcePath.replace(
      /^\.\.\//,
      `decky://decky/plugin/${encodeURIComponent(manifest.name)}/`,
    ),
    exports: "default",
  },
};
