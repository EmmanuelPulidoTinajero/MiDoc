import path from 'node:path';

export default {
  plugins: [
    {
      name: 'midoc:relative-vitest-include',
      enforce: 'post',
      config(config) {
        const root = config.root || process.cwd();
        if (Array.isArray(config.test?.include)) {
          config.test.include = config.test.include.map((entry) =>
            path.isAbsolute(entry)
              ? path.relative(root, entry).replace(/\\/g, '/')
              : entry,
          );
        }
      },
    },
  ],
};
