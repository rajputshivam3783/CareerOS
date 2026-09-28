// V19.3 — Government Portal. Share a recruitment/result/admit-card
// link via the native Web Share sheet where available, falling back
// to copying the URL to the clipboard (with a caller-supplied
// callback to surface that to the user) everywhere else.
export async function shareOrCopy(title: string, url: string, onCopied?: () => void) {
  if (typeof navigator !== "undefined" && "share" in navigator) {
    try {
      await (navigator as any).share({ title, url });
      return;
    } catch {
      // User cancelled the share sheet, or it failed — fall through to copy.
    }
  }
  if (typeof navigator !== "undefined" && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(url);
      onCopied?.();
      return;
    } catch {
      /* ignore — nothing more we can do without user interaction context */
    }
  }
}
