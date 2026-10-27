const LATEX_SYMBOL_MAP: Record<string, string> = {
  approx: "≈",
  sim: "∼",
  neq: "≠",
  leq: "≤",
  geq: "≥",
  pm: "±",
  times: "×",
  cdot: "·",
  to: "→",
  rightarrow: "→",
  leftarrow: "←",
  infty: "∞",
  alpha: "α",
  beta: "β",
  gamma: "γ",
  delta: "δ",
  theta: "θ",
  lambda: "λ",
  mu: "μ",
  sigma: "σ",
  pi: "π",
};

function normalizeLatexExpression(rawExpression: string): string {
  let expression = rawExpression.replace(/\\\\/g, "\\");

  expression = expression.replace(
    /\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/g,
    "($1)/($2)"
  );
  expression = expression.replace(/\\sqrt\s*\{([^{}]+)\}/g, "√($1)");
  expression = expression.replace(/\\text\s*\{([^{}]+)\}/g, "$1");
  expression = expression.replace(
    /\\(?:vec|vector)\s*\{([^{}]+)\}/gi,
    "Vector($1)"
  );
  expression = expression.replace(
    /\\(?:vec|vector)\s*\(([^()]+)\)/gi,
    "Vector($1)"
  );

  expression = expression.replace(/\\([a-zA-Z]+)\b/g, (_match, command: string) => {
    const normalizedCommand = command.toLowerCase();
    return LATEX_SYMBOL_MAP[normalizedCommand] ?? command;
  });

  expression = expression.replace(/[{}]/g, "");
  expression = expression.replace(/\s+/g, " ").trim();
  return expression;
}

function normalizeStandaloneLatexCommands(value: string): string {
  let normalized = value.replace(/\\\\/g, "\\");

  normalized = normalized.replace(
    /\\(?:vec|vector)\s*\{([^{}]+)\}/gi,
    "Vector($1)"
  );
  normalized = normalized.replace(
    /\\(?:vec|vector)\s*\(([^()]+)\)/gi,
    "Vector($1)"
  );
  normalized = normalized.replace(/\\([a-zA-Z]+)\b/g, (_match, command: string) => {
    const normalizedCommand = command.toLowerCase();
    return LATEX_SYMBOL_MAP[normalizedCommand] ?? command;
  });

  return normalized;
}

function normalizeMathDelimitedText(value: string): string {
  let normalized = value;
  normalized = normalized.replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) =>
    normalizeLatexExpression(expr)
  );
  normalized = normalized.replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) =>
    normalizeLatexExpression(expr)
  );
  normalized = normalized.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr: string) =>
    normalizeLatexExpression(expr)
  );
  normalized = normalized.replace(/\$(.+?)\$/g, (match, expr: string) => {
    const looksLikeMath = /\\|[=<>^_]|(?:\b(?:sin|cos|tan|log|exp)\b)/i.test(expr);
    if (!looksLikeMath) return match;
    return normalizeLatexExpression(expr);
  });
  return normalized;
}

export function normalizeLatexLikeText(text?: string): string | undefined {
  if (!text) return text;
  if (!/[\\$]/.test(text)) return text;

  let normalized = text.replace(/\r\n?/g, "\n");
  normalized = normalizeMathDelimitedText(normalized);
  normalized = normalizeStandaloneLatexCommands(normalized);
  normalized = normalized.replace(/\\\$/g, "$");
  return normalized;
}
