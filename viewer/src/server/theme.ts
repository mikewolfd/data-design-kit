import { open } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { parseViewerTheme, type ViewerTheme } from '../lib/theme';

const maximumBytes = 16_384;

export async function loadViewerTheme(path?: string): Promise<ViewerTheme> {
  if (!path?.trim()) return parseViewerTheme();
  if (!isAbsolute(path)) throw new Error('DDK_VIEWER_THEME_CONFIG must be an absolute file path.');
  const file = await open(path, 'r');
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.size > maximumBytes)
      throw new Error('The viewer theme must be a JSON file of at most 16,384 bytes.');
    const buffer = Buffer.alloc(maximumBytes + 1);
    let total = 0;
    while (total < buffer.length) {
      const { bytesRead } = await file.read(buffer, total, buffer.length - total, total);
      if (!bytesRead) break;
      total += bytesRead;
    }
    if (total > maximumBytes) throw new Error('The viewer theme exceeds 16,384 bytes.');
    let value: unknown;
    try {
      value = JSON.parse(
        new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, total)),
      );
    } catch {
      throw new Error('The viewer theme must contain valid JSON.');
    }
    return parseViewerTheme(value);
  } finally {
    await file.close();
  }
}

let configured: Promise<ViewerTheme> | undefined;

/** Read operator configuration once per server process; requests cannot select a theme file. */
export function configuredViewerTheme(): Promise<ViewerTheme> {
  return (configured ??= loadViewerTheme(process.env.DDK_VIEWER_THEME_CONFIG));
}
