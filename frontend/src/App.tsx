import { Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import ProtectedRoute from "./components/ProtectedRoute";
import UploadDraftRoute from "./components/UploadDraftRoute";
import CustomerList from "./pages/CustomerList";
import Dashboard from "./pages/Dashboard";
import InvoiceDetail from "./pages/InvoiceDetail";
import InvoiceForm from "./pages/InvoiceForm";
import InvoiceList from "./pages/InvoiceList";
import InvoiceUpload from "./pages/InvoiceUpload";
import InvoiceUploadReview from "./pages/InvoiceUploadReview";
import Login from "./pages/Login";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<AppShell><Dashboard /></AppShell>} />
        <Route path="/invoices" element={<AppShell><InvoiceList /></AppShell>} />
        <Route path="/invoices/new" element={<AppShell><InvoiceForm /></AppShell>} />
        {/* Before /invoices/:id, or "upload" is matched as an invoice id. The
            two states share one draft, held by the UploadDraftRoute layout. */}
        <Route element={<UploadDraftRoute />}>
          <Route path="/invoices/upload" element={<AppShell><InvoiceUpload /></AppShell>} />
          <Route path="/invoices/upload/review" element={<AppShell><InvoiceUploadReview /></AppShell>} />
        </Route>
        <Route path="/invoices/:id" element={<AppShell><InvoiceDetail /></AppShell>} />
        <Route path="/invoices/:id/edit" element={<AppShell><InvoiceForm /></AppShell>} />
        <Route path="/customers" element={<AppShell><CustomerList /></AppShell>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
