import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { AuthProvider } from "./auth";
import { Backdrop } from "./components/Backdrop";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Backdrop />
    <div className="app-shell">
      <AuthProvider>
        <App />
      </AuthProvider>
    </div>
  </StrictMode>,
);
