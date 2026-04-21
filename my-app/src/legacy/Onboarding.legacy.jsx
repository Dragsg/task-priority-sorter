import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";

export default function Onboarding() {
    const [userData, setUserData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [preferences, setPreferences] = useState(null);
    const navigate = useNavigate();

    useEffect(() => {
        const token = localStorage.getItem("token");

        const fetchUserData = async () => {
            await fetch("http://localhost:5000/api/user", {
                headers: { Authorization: `Bearer ${token}` },
            }).then(async (res) => {
                if (res) {
                    res = await res.json();
                    setUserData(res);
                    setLoading(false);
                    console.log(res);
                }
            });
        };

        fetchUserData();
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        console.log(preferences);
        const token = localStorage.getItem("token");
        if (preferences) {
            await fetch("http://localhost:5000/api/onboarding", {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({ preferences }),
            });
        }
        navigate("/home");
    };

    if (loading) return <div>Loading...</div>;

    return (
        <form onSubmit={handleSubmit}>
            <h1>
                {userData.email} Before you begin, let us personalise your
                experience
            </h1>

            <h3>What do you plan to use this tool for?</h3>

            <label>
                <input
                    type="radio"
                    id="school"
                    name="preferences"
                    onChange={(e) => setPreferences("School")}
                />
                School
            </label>
            <br></br>

            <label>
                <input
                    type="radio"
                    id="work"
                    name="preferences"
                    onChange={(e) => setPreferences("Work")}
                />
                Work
            </label>
            <br></br>

            <label>
                <input
                    type="radio"
                    id="personal"
                    name="preferences"
                    onChange={(e) => setPreferences("Personal")}
                />
                Personal
            </label>
            <br></br>

            <label>
                <input
                    type="radio"
                    id="unsure"
                    name="preferences"
                    onChange={(e) => setPreferences("Unsure")}
                />
                Unsure
            </label>
            <br></br>

            <button type="submit">Continue</button>
        </form>
    );
}
