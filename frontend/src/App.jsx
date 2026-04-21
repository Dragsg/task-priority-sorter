import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { getStoredToken } from "./api";
import Home from "./pages/Home";
import Linking from "./pages/Linking";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";

function ProtectedRoute({ children }) {
  const token = getStoredToken();

  if (!token) {
    return <Navigate replace to="/" />;
  }

  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Login />} path="/" />
        <Route
          element={
            <ProtectedRoute>
              <Onboarding />
            </ProtectedRoute>
          }
          path="/onboarding"
        />
        <Route
          element={
            <ProtectedRoute>
              <Home />
            </ProtectedRoute>
          }
          path="/home"
        />
        <Route
          element={
            <ProtectedRoute>
              <Linking />
            </ProtectedRoute>
          }
          path="/linking"
        />
        <Route element={<Navigate replace to="/" />} path="*" />
      </Routes>
    </BrowserRouter>
  );
}
