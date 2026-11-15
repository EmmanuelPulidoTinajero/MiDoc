/*
 * Contrato ejecutable del sistema de diseño (S1, S4).
 *
 * Verifica dos cosas que hasta ahora sólo estaban escritas en prosa:
 * 1. Los tokens de `_tokens.css` y los documentados en `design/system.md`
 *    son el mismo conjunto. Un token sin documentar es un valor inventado;
 *    un token documentado que falta es una promesa rota.
 * 2. Las parejas de color que el producto usa de verdad cumplen el mínimo
 *    de contraste WCAG 2.x (4.5:1 para texto, 3:1 para límites de control).
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const TOKENS_CSS = './_tokens.css';
const SYSTEM_DOC = '../../../design/system.md';

function readRepoFile(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf-8');
}

function declaredTokens(css: string): Map<string, string> {
  const tokens = new Map<string, string>();
  for (const match of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    tokens.set(match[1], match[2].trim());
  }
  return tokens;
}

function documentedTokens(markdown: string): Set<string> {
  return new Set([...markdown.matchAll(/`(--[a-z0-9-]+)`/g)].map((match) => match[1]));
}

function channelLuminance(hex: string): number {
  const value = Number.parseInt(hex, 16) / 255;
  return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex: string): number {
  const [r, g, b] = [0, 2, 4].map((offset) =>
    channelLuminance(hex.slice(offset, offset + 2)),
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(foreground: string, background: string): number {
  const [lighter, darker] = [relativeLuminance(foreground), relativeLuminance(background)].sort(
    (a, b) => b - a,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

function hexOf(tokens: Map<string, string>, token: string): string {
  const value = tokens.get(token);
  if (!value || !/^#[0-9a-f]{6}$/i.test(value)) {
    throw new Error(`${token} no es un color hexadecimal de 6 dígitos: ${String(value)}`);
  }
  return value.slice(1);
}

const tokens = declaredTokens(readRepoFile(TOKENS_CSS));
const systemDoc = readRepoFile(SYSTEM_DOC);

describe('tokens del sistema de diseño', () => {
  it('declara todos los tokens mencionados en design/system.md', () => {
    const missing = [...documentedTokens(systemDoc)].filter((token) => !tokens.has(token));

    expect(missing.sort()).toEqual([]);
  });

  it('no declara tokens que design/system.md no documente', () => {
    const undocumented = [...tokens.keys()].filter(
      (token) => !documentedTokens(systemDoc).has(token),
    );

    expect(undocumented.sort()).toEqual([]);
  });

  // 4.5:1 para texto legible, 3:1 para límites de control y anillo de foco.
  const pairs: Array<[foreground: string, background: string, minimum: number]> = [
    ['--color-text', '--color-canvas', 4.5],
    ['--color-text', '--color-surface', 4.5],
    ['--color-text-soft', '--color-canvas', 4.5],
    ['--color-text-soft', '--color-surface', 4.5],
    ['--color-text-inverse', '--color-primary', 4.5],
    ['--color-text-inverse', '--color-primary-hover', 4.5],
    ['--color-text-inverse', '--color-danger', 4.5],
    ['--color-accent', '--color-canvas', 4.5],
    ['--color-warning', '--color-warning-soft', 4.5],
    ['--color-info', '--color-info-soft', 4.5],
    ['--color-success', '--color-success-soft', 4.5],
    ['--color-primary', '--color-primary-soft', 3],
    ['--color-border-strong', '--color-canvas', 3],
    ['--color-border-strong', '--color-surface', 3],
    ['--color-focus', '--color-canvas', 3],
  ];

  it.each(pairs)('%s sobre %s cumple %s:1', (foreground, background, minimum) => {
    const ratio = contrastRatio(hexOf(tokens, foreground), hexOf(tokens, background));

    expect(Number(ratio.toFixed(2))).toBeGreaterThanOrEqual(minimum);
  });

  it('apaga todo el movimiento cuando el sistema lo pide', () => {
    expect(readRepoFile(TOKENS_CSS)).toContain('@media (prefers-reduced-motion: reduce)');
  });
});
