export function downloadUrl(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  try {
    downloadUrl(url, filename);
  } finally {
    // Revoke after the click handler completes; browsers keep the URL alive long
    // enough for the download to start.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
