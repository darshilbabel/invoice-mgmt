import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import type { ExtractionResult } from "../types";

/**
 * Carries the in-progress upload across /invoices/upload and
 * /invoices/upload/review.
 *
 * It is a layout route rather than page state because the two wireframe states
 * are two routes (3a-3b-3d and 3c) but one draft. A File cannot be serialised
 * into a URL or into history state usefully, so the review route is only
 * reachable with a live draft in memory — refresh it and you land back on the
 * chooser rather than on a half-empty form. Same shape as ProtectedRoute.
 */

interface UploadDraft {
  file: File | null;
  /** blob: URL for "Open PDF in a new tab". Revoked when the file changes. */
  objectUrl: string | null;
  result: ExtractionResult | null;
  setFile: (file: File | null) => void;
  setResult: (result: ExtractionResult | null) => void;
  clear: () => void;
}

const UploadDraftContext = createContext<UploadDraft | null>(null);

export function useUploadDraft(): UploadDraft {
  const draft = useContext(UploadDraftContext);
  if (!draft) throw new Error("useUploadDraft must be used inside UploadDraftRoute.");
  return draft;
}

export default function UploadDraftRoute() {
  const { user } = useAuth();
  const location = useLocation();

  const [file, setFileState] = useState<File | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractionResult | null>(null);

  // The live blob: URL lives in a ref as well as state so revoking it never
  // depends on a state updater running exactly once.
  const urlRef = useRef<string | null>(null);

  const setFile = useCallback((next: File | null) => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = next ? URL.createObjectURL(next) : null;
    setFileState(next);
    setObjectUrl(urlRef.current);
    // A new file invalidates whatever the previous one extracted to.
    setResult(null);
  }, []);

  const clear = useCallback(() => setFile(null), [setFile]);

  useEffect(() => () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }, []);

  const value = useMemo<UploadDraft>(
    () => ({ file, objectUrl, result, setFile, setResult, clear }),
    [file, objectUrl, result, setFile, clear],
  );

  // VIEWER cannot create invoices (conventions.md, Permissions), so the whole
  // flow is closed to them — not just the Save button at the end of it.
  if (user?.role === "VIEWER") return <Navigate to="/invoices" replace />;

  // Reached the review screen without an extraction? There is nothing to review.
  if (location.pathname.startsWith("/invoices/upload/review") && !result) {
    return <Navigate to="/invoices/upload" replace />;
  }

  return (
    <UploadDraftContext.Provider value={value}>
      <Outlet />
    </UploadDraftContext.Provider>
  );
}
