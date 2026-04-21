import { BrowserRouter as Router, Navigate, Route, Routes } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";

function App() {
    return (
        <Router>
            <Routes>
                <Route path="/" element={<Navigate to="/login" replace />} />
                <Route path="/login" element={<Login />} />
                <Route
                    path="/onboarding"
                    element={
                        <ProtectedRoute>
                            <Onboarding />
                        </ProtectedRoute>
                    }
                />
                <Route
                    path="/home"
                    element={
                        <ProtectedRoute>
                            <Home />
                        </ProtectedRoute>
                    }
                />
                <Route path="/dashboard" element={<Navigate to="/home" replace />} />
            </Routes>
        </Router>
    );
}

export default App;
