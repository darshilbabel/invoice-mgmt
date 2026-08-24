import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  MAX_FILE_BYTES,
  extractInvoice,
  formatBytes,
  isAbort,
  isExtractionFailure,
  validateFile,
} from "../api/extraction";
import { useUploadDraft } from "../components/UploadDraftRoute";
import type { ExtractionFailure } from "../types";

/**
 * Wireframe 3a / 3b / 3d — one route, three states in sequence.
 *
 * 3c (review) is its own route because it is a different screen at a different
 * width; these three are the same frame with its middle swapped, so they are
 * one component with a phase.
 */

type Phase = "choose" | "extracting" | "failed";

/**
 * Named steps rather than a bare spinner, because the wait spans a real upload,
 * a model call and a database lookup.
 *
 * They advance on a timer, NOT on server progress. /api/invoices/extract/ is one
 * blocking request with nothing to report mid-flight, so the steps describe what
 * is happening rather than measure it — which is also why the bar is
 * indeterminate and no time remaining is claimed. A percentage here would be
 * invented. Real stage reporting needs a polled job; out of scope, see
 * docs/specs/2026-08-ocr-ingest.md.
 */
const STEPS = ["File uploaded", "Reading the text and extracting fields", "Matching the customer"];

/** Roughly how long each early step plausibly takes. The last one simply stays
 *  active until the response lands, however long that is. */
const STEP_INTERVAL_MS = 6000;

export default function InvoiceUpload() {
  const navigate = useNavigate();
  const { file, setFile, setResult } = useUploadDraft();

  const [phase, setPhase] = useState<Phase>("choose");
  const [failure, setFailure] = useState<ExtractionFailure | null>(null);
  const [rejected, setRejected] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [dragging, setDragging] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (phase !== "extracting") return;
    const first = setTimeout(() => setStep(1), STEP_INTERVAL_MS);
    const second = setTimeout(() => setStep(2), STEP_INTERVAL_MS * 2);
    return () => {
      clearTimeout(first);
      clearTimeout(second);
    };
  }, [phase]);

  function choose(next: File | null) {
    setRejected(null);
    if (!next) {
      setFile(null);
      return;
    }
    const invalid = validateFile(next);
    if (invalid) {
      setRejected(invalid.message);
      setFile(null);
      return;
    }
    setFile(next);
  }

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files;
    if (dropped.length > 1) {
      setRejected("One file at a time. Drop a single PDF.");
      return;
    }
    choose(dropped[0] ?? null);
  }

  async function extract() {
    if (!file) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setStep(0);
    setPhase("extracting");
    try {
      const result = await extractInvoice(file, controller.signal);
      setResult(result);
      navigate("/invoices/upload/review");
    } catch (caught) {
      if (isAbort(caught)) {
        setPhase("choose");
        return;
      }
      setFailure(
        isExtractionFailure(caught)
          ? caught
          : { reason: "timeout", message: "The extraction did not finish. Try again." },
      );
      setPhase("failed");
    } finally {
      abortRef.current = null;
    }
  }

  return (
    <>
      <p className="crumb">
        <Link to="/invoices">Invoices</Link> / Upload
      </p>

      {phase === "extracting" ? (
        <Extracting fileName={file?.name ?? ""} step={step} onCancel={() => abortRef.current?.abort()} />
      ) : phase === "failed" ? (
        <Failed
          failure={failure}
          onRetry={() => void extract()}
          onAnother={() => {
            setFailure(null);
            choose(null);
            setPhase("choose");
          }}
        />
      ) : (
        <>
          <div className="page-head">
            <div>
              <h1>Upload an invoice PDF</h1>
              <p className="muted" style={{ margin: "var(--sp-8) 0 0", maxWidth: "52ch", font: "var(--type-body-sm)" }}>
                The file is read and the fields are extracted for you to check. Nothing is saved
                until you confirm.
              </p>
            </div>
          </div>

          <label
            className={`dropzone${dragging ? " is-dragging" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            <span className="dropzone-mark" aria-hidden="true">PDF</span>
            <span className="dropzone-title">Drop a PDF here</span>
            <span className="hint">One file at a time · up to {formatBytes(MAX_FILE_BYTES)}</span>
            <span className="btn btn-secondary btn-sm" aria-hidden="true">Choose file</span>
            {/* A real input, so the picker is reachable by keyboard and by
                screen reader. Drag-and-drop above is the enhancement. */}
            <input
              type="file"
              accept="application/pdf,.pdf"
              className="dropzone-input"
              onChange={(e) => choose(e.target.files?.[0] ?? null)}
            />
          </label>

          {rejected && (
            <p role="alert" className="notice notice-danger" style={{ marginTop: "var(--sp-16)" }}>{rejected}</p>
          )}

          {file && (
            <div className="file-card" style={{ marginTop: "var(--sp-16)" }}>
              <span className="file-thumb" aria-hidden="true">PDF</span>
              <span className="stack" style={{ flex: 1, gap: "var(--sp-2)" }}>
                <span className="cell-strong">{file.name}</span>
                <span className="hint">{formatBytes(file.size)}</span>
              </span>
              <button type="button" className="btn-ghost btn-sm" onClick={() => choose(null)}>Remove</button>
            </div>
          )}

          <div className="row" style={{ marginTop: "var(--sp-24)" }}>
            <button type="button" className="btn" disabled={!file} onClick={() => void extract()}>
              Extract fields
            </button>
            <Link className="btn btn-secondary" to="/invoices">Cancel</Link>
          </div>
        </>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function Extracting({ fileName, step, onCancel }: { fileName: string; step: number; onCancel: () => void }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reading {fileName}</h1>
          <p className="muted" style={{ margin: "var(--sp-8) 0 0", font: "var(--type-body-sm)" }}>
            Keep this tab open.
          </p>
        </div>
      </div>

      <div className="card card-pad stack" style={{ gap: "var(--sp-20)" }}>
        <div className="progress" role="progressbar" aria-label="Extracting fields">
          <div className="progress-indeterminate" />
        </div>

        <ol className="steps">
          {STEPS.map((label, index) => (
            <li
              key={label}
              className={`step${index < step ? " is-done" : index === step ? " is-active" : ""}`}
              aria-current={index === step ? "step" : undefined}
            >
              <span className="step-mark" aria-hidden="true" />
              {label}
            </li>
          ))}
        </ol>
      </div>

      <div className="row" style={{ marginTop: "var(--sp-24)", alignItems: "center" }}>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button>
        <span className="hint">Cancelling discards the file. Nothing has been written.</span>
      </div>
    </>
  );
}

function Failed({
  failure,
  onRetry,
  onAnother,
}: {
  failure: ExtractionFailure | null;
  onRetry: () => void;
  onAnother: () => void;
}) {
  return (
    <>
      <div className="page-head">
        <h1>Could not read this PDF</h1>
      </div>

      <p role="alert" className="notice notice-danger">
        {failure?.message ?? "The extraction did not finish."} Nothing was saved.
      </p>

      <div className="card card-pad stack" style={{ marginTop: "var(--sp-16)", gap: "var(--sp-8)" }}>
        <h2>What you can do</h2>
        <p className="muted" style={{ margin: 0, font: "var(--type-body-sm)" }}>
          Try the extraction again — a second pass sometimes succeeds.
        </p>
        <p className="muted" style={{ margin: 0, font: "var(--type-body-sm)" }}>
          Upload a different export of the same invoice.
        </p>
        <p className="muted" style={{ margin: 0, font: "var(--type-body-sm)" }}>
          Enter it by hand instead.
        </p>
      </div>

      <div className="row" style={{ marginTop: "var(--sp-24)", flexWrap: "wrap" }}>
        <button type="button" className="btn" onClick={onRetry}>Try again</button>
        <Link className="btn btn-secondary" to="/invoices/new">Enter by hand</Link>
        <button type="button" className="btn btn-secondary" onClick={onAnother}>Choose another file</button>
      </div>
    </>
  );
}
