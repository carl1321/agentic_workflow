/**
 * 从字符串中提取第一个完整的 JSON 对象或数组（按括号匹配），用于 content 后带多余说明的情况。
 */
function extractFirstJSON(raw: string): string {
  const trimmed = raw.trim();
  const startObj = trimmed.indexOf("{");
  const startArr = trimmed.indexOf("[");
  let start: number;
  let open: string;
  let close: string;
  if (startArr >= 0 && (startObj < 0 || startArr < startObj)) {
    start = startArr;
    open = "[";
    close = "]";
  } else if (startObj >= 0) {
    start = startObj;
    open = "{";
    close = "}";
  } else {
    return trimmed;
  }
  let depth = 0;
  let inString: string | null = null;
  let i = start;
  while (i < trimmed.length) {
    const c = trimmed[i];
    if (inString) {
      if (c === "\\" && i + 1 < trimmed.length) {
        i += 2;
        continue;
      }
      if (c === inString) inString = null;
      i++;
      continue;
    }
    if (c === '"' || c === "'") {
      inString = c;
      i++;
      continue;
    }
    if (c === open) {
      depth++;
      i++;
      continue;
    }
    if (c === close) {
      depth--;
      if (depth === 0) return trimmed.slice(start, i + 1);
      i++;
      continue;
    }
    i++;
  }
  return trimmed;
}

export function parseJSON<T>(json: string | null | undefined, fallback: T): T {
  if (!json) {
    return fallback;
  }
  const raw = json
    .trim()
    .replace(/^```json\s*/, "")
    .replace(/^```js\s*/, "")
    .replace(/^```ts\s*/, "")
    .replace(/^```plaintext\s*/, "")
    .replace(/^```\s*/, "")
    .replace(/\s*```$/, "");
  // 先只取第一个完整 JSON，再用原生 JSON.parse 解析，避免 best-effort-json-parser 的 "extra tokens" 报错
  const toParse = extractFirstJSON(raw);
  try {
    return JSON.parse(toParse) as T;
  } catch {
    return fallback;
  }
}
