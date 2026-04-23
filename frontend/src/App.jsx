import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { getStoredToken } from "./api";
import Home from "./pages/Home";
import Kanban from "./pages/Kanban";
import Linking from "./pages/Linking";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Preferences from "./pages/Preferences";
import Statistics from "./pages/Statistics";

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
              <Preferences />
            </ProtectedRoute>
          }
          path="/preferences"
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
              <Kanban />
            </ProtectedRoute>
          }
          path="/kanban"
        />
        <Route
          element={
            <ProtectedRoute>
              <Linking />
            </ProtectedRoute>
          }
          path="/linking"
        />
        <Route
          element={
            <ProtectedRoute>
              <Statistics />
            </ProtectedRoute>
          }
          path="/statistics"
        />
        <Route element={<Navigate replace to="/" />} path="*" />
      </Routes>
    </BrowserRouter>
  );
}
