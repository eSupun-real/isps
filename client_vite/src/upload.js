const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB

export function validateFileSize(file) {
  if (file.size > MAX_FILE_SIZE) {
    throw new Error(`File "${file.name}" exceeds the 5 MB limit (${(file.size / 1024 / 1024).toFixed(1)} MB).`);
  }
  return true;
}

export function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    validateFileSize(file);
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result.split(',')[1]);
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

export async function pollDocumentStatus(callId, onProgress) {
  const maxAttempts = 60;
  const interval = 3000;
  let attempts = 0;

  return new Promise((resolve) => {
    const check = async () => {
      attempts++;
      try {
        const { api } = await import('./api.js');
        const status = await api('GET', `/api/vessels/${callId}/status`);
        if (onProgress) onProgress(status);
        const docs = status.documents || {};
        const entries = Object.values(docs).filter(d => d.ocr_status && d.ocr_status !== 'not_uploaded');
        const allDone = entries.length > 0 && entries.every(d => d.ocr_status === 'done');
        if (allDone || attempts >= maxAttempts) {
          resolve({ done: allDone, status });
          return;
        }
      } catch (e) {
        console.warn('Poll status error:', e);
      }
      setTimeout(check, interval);
    };
    check();
  });
}
