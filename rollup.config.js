import deckyPlugin from "@decky/rollup";

function cssInjectedPlugin() {
  return {
    name: 'css-injected-plugin',
    transform(code, id) {
      if (/\.css(?:\?.*)?$/.test(id)) {
        const escapedCss = code.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
        return {
          code: `
            if (typeof window !== 'undefined' && typeof document !== 'undefined') {
              const style = document.createElement('style');
              style.textContent = \`${escapedCss}\`;
              document.head.appendChild(style);
            }
            export default \`${escapedCss}\`;
          `,
          map: { mappings: '' },
          moduleSideEffects: true
        };
      }
    }
  };
}

export default deckyPlugin({
  plugins: [
    cssInjectedPlugin()
  ]
})