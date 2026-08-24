/**
 * Invoice PDF extraction — POST /api/invoices/extract/.
 *
 * The endpoint reads the PDF with OpenAI and returns fields for the user to
 * check. It writes no invoice and no line items: the review screen's Save is the
 * ordinary POST /api/invoices/. The one row it does create is a `Customer`, when
 * the supplier on the PDF matches nothing already on file — see open question 4
 * in docs/specs/2026-08-ocr-ingest.md for why, and what it costs.
 *
 * The uploaded file is not stored anywhere. It is read in memory, sent, dropped.
 */

import { ApiError, api } from "./client";
import type { ExtractionFailure, ExtractionResult } from "../types";

/**
 * Mirrors settings.INVOICE_UPLOAD_MAX_BYTES. Checking here saves a pointless
 * round trip with a 10 MB body attached; the server enforces the real limit.
 */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

export function isExtractionFailure(value: unknown): value is ExtractionFailure {
  return typeof value === "object" && value !== null && "reason" in value && "message" in value;
}

export function isAbort(value: unknown): boolean {
  return value instanceof DOMException && value.name === "AbortError";
}

/** Human-readable file size for the file card. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Courtesy validation, run the moment a file is picked so an obvious mistake is
 * caught without a request. Returns null when the file is acceptable. Not a
 * control — the server checks the size and the PDF magic bytes itself.
 */
export function validateFile(file: File): ExtractionFailure | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) {
    return { reason: "not_pdf", message: `${file.name} is not a PDF. Upload a PDF export of the invoice.` };
  }
  if (file.size > MAX_FILE_BYTES) {
    return {
      reason: "too_large",
      message: `${file.name} is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_FILE_BYTES)}.`,
    };
  }
  return null;
}

/**
 * Rejects with an ExtractionFailure the caller can render, or with an AbortError
 * when `signal` fires. The request blocks for the length of a model call — there
 * is no job queue behind this, so it can take the better part of a minute.
 */
export async function extractInvoice(
  file: File,
  signal?: AbortSignal,
): Promise<ExtractionResult> {
  const invalid = validateFile(file);
  if (invalid) throw invalid;

  const form = new FormData();
  form.append("file", file);

  try {
    return await api.upload<ExtractionResult>("/invoices/extract/", form, signal);
  } catch (caught) {
    if (isAbort(caught)) throw caught;
    if (caught instanceof ApiError) {
      // The server already phrased this for a person (conventions.md: surface
      // DRF's message verbatim, never paraphrase it).
      const failure: ExtractionFailure = { reason: "no_text", message: caught.message };
      throw failure;
    }
    const failure: ExtractionFailure = {
      reason: "timeout",
      message: "Could not reach the server. Check it is running and try again.",
    };
    throw failure;
  }
}
