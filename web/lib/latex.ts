/**
 * Utility functions for LaTeX processing
 *
 * remark-math only supports $...$ and $$...$$ delimiters by default.
 * Many LLMs output LaTeX using \(...\) and \[...\] delimiters.
 * This utility converts between formats.
 */

/**
 * Convert LaTeX delimiters from \(...\) and \[...\] to $...$ and $$...$$
 * This makes the content compatible with remark-math for ReactMarkdown rendering.
 *
 * @param content - The content containing LaTeX with \(...\) or \[...\] delimiters
 * @returns Content with $...$ and $$...$$ delimiters
 */
export function convertLatexDelimiters(content: string): string {
  if (!content) return content;

  let result = content;

  // Convert \[...\] to $$...$$ (block math)
  // Use function replacement to avoid '$' token ambiguity in replacement strings.
  result = result.replace(/\\\[([\s\S]*?)\\\]/g, (_m, block: string) => {
    const normalized = String(block ?? "").trim();
    return `\n$$\n${normalized}\n$$\n`;
  });

  // Convert \(...\) to $...$ (inline math)
  result = result.replace(/\\\(([\s\S]*?)\\\)/g, (_m, inline: string) => {
    const normalized = String(inline ?? "").trim();
    return ` $${normalized}$ `;
  });

  // Also handle cases where LaTeX is directly in the text without proper delimiters
  // e.g., standalone \lim, \frac, etc. that should be wrapped
  // This is a common issue with LLM outputs

  // Clean up multiple consecutive newlines
  result = result.replace(/\n{3,}/g, "\n\n");

  return result;
}

/**
 * Process content for ReactMarkdown rendering with proper LaTeX support
 * This is a convenience wrapper that applies all necessary transformations.
 *
 * @param content - The raw content to process
 * @returns Processed content ready for ReactMarkdown with remark-math
 */
export function processLatexContent(content: string): string {
  if (!content) return "";

  // Convert to string if not already
  const str = String(content);

  // Apply delimiter conversion
  return convertLatexDelimiters(str);
}
