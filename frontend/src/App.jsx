import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { clearStoredToken, fetchCurrentUser, getStoredToken, getStoredUser } from "./api";
import { isOnboardingComplete } from "./onboardingOptions";
import Home from "./pages/Home";
import Kanban from "./pages/Kanban";
import Linking from "./pages/Linking";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Preferences from "./pages/Preferences";
import Statistics from "./pages/Statistics";

function ProtectedRoute({
  children,
  onboardingOnly = false,
  requireCompletedOnboarding = false,
}) {
  const token = getStoredToken();
  const cachedUser = getStoredUser();
  const cachedUserId = cachedUser?.userId ?? null;
  const cachedUserCompleted = isOnboardingComplete(cachedUser);
  const [resolvedUser, setResolvedUser] = useState(() => cachedUser);
  const [loading, setLoading] = useState(() => Boolean(token && !cachedUser));

  useEffect(() => {
    let active = true;

    if (!token) {
      setResolvedUser(null);
      setLoading(false);
      return undefined;
    }

    if (cachedUser) {
      setLoading(false);
      return undefined;
    }

    setLoading(true);
    fetchCurrentUser()
      .then((user) => {
        if (!active) {
          return;
        }
        setResolvedUser(user);
        setLoading(false);
      })
      .catch(() => {
        if (!active) {
          return;
        }
        clearStoredToken();
        setResolvedUser(null);
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [cachedUserCompleted, cachedUserId, token]);

  if (!token) {
    return <Navigate replace to="/" />;
  }

  const user = cachedUser ?? resolvedUser;

  if (loading) {
    return <main className="simple-shell">Checking your account...</main>;
  }

  if (!user) {
    return <Navigate replace to="/" />;
  }

  const completed = isOnboardingComplete(user);
  if (onboardingOnly && completed) {
    return <Navigate replace to="/home" />;
  }
  if (requireCompletedOnboarding && !completed) {
    return <Navigate replace to="/onboarding" />;
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
            <ProtectedRoute onboardingOnly>
              <Onboarding />
            </ProtectedRoute>
          }
          path="/onboarding"
        />
        <Route
          element={
            <ProtectedRoute requireCompletedOnboarding>
              <Preferences />
            </ProtectedRoute>
          }
          path="/preferences"
        />
        <Route
          element={
            <ProtectedRoute requireCompletedOnboarding>
              <Home />
            </ProtectedRoute>
          }
          path="/home"
        />
        <Route
          element={
            <ProtectedRoute requireCompletedOnboarding>
              <Kanban />
            </ProtectedRoute>
          }
          path="/kanban"
        />
        <Route
          element={
            <ProtectedRoute requireCompletedOnboarding>
              <Linking />
            </ProtectedRoute>
          }
          path="/linking"
        />
        <Route
          element={
            <ProtectedRoute requireCompletedOnboarding>
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
