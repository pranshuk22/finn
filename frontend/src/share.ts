import { toBlob } from "html-to-image";

// Turn a card into an image for WhatsApp and the like. Buttons and links marked data-noshare are left out, and
// a footer names the source, so a forwarded image still says where its numbers came from.

export async function shareCard(node: HTMLElement, name: string, source: string): Promise<"shared" | "saved" | "cancelled"> {
  const bg = getComputedStyle(document.body).getPropertyValue("--surface").trim() || "#3a4342";
  const footer = document.createElement("p");
  footer.textContent = `FINN · ${source}`;
  footer.style.cssText = "margin:12px 0 0;font-size:11px;opacity:.7";
  node.appendChild(footer);
  let blob: Blob | null;
  try {
    blob = await toBlob(node, {
      backgroundColor: bg,
      pixelRatio: 2,
      filter: (el) => !(el instanceof HTMLElement && el.dataset.noshare !== undefined),
    });
  } finally {
    footer.remove();
  }
  if (!blob) throw new Error("no image");
  const file = new File([blob], `${name}.png`, { type: "image/png" });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: name });
      return "shared";
    } catch {
      return "cancelled"; // the reader closed the share sheet
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = file.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  return "saved";
}
