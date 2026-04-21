import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import Login from "../pages/Login";
import Onboarding from "../pages/Onboarding";
import Home from "../pages/Home";

function App() {
    return (
        <Router>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/onboarding" element={<Onboarding />} />
                <Route path="/home" element={<Home />} />
                <Route path="/dashboard" element={<Home />} />
            </Routes>
        </Router>
    );
}

export default App;
