import { useState, useEffect } from "react";
import { authClient } from "../js/auth";
import { useNavigate } from "react-router-dom";
import "../App.css";
import "../styles/Login.css";

export default function Login() {
    const [session, setSession] = useState(null);
    const [user, setUser] = useState(null);
    const [email, setEmail] = useState("");
    const [name, setName] = useState("");
    const [password, setPassword] = useState("");
    const [isSignUp, setIsSignUp] = useState(true);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        authClient.getSession().then((result) => {
            if (result.data?.session && result.data?.user) {
                setSession(result.data.session);
                setUser(result.data.user);
            }
            setLoading(false);
        });
    }, []);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!isSignUp) {
            const result = await fetch("http://localhost:5000/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });
            const data = await result.json();
            if (data.success) {
                localStorage.setItem("token", data.token);
                navigate("/home");
            }
        } else {
            const result = await fetch("http://localhost:5000/api/signup", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password, name }),
            });
            const data = await result.json();
            if (data.success) {
                localStorage.setItem("token", data.token);
                navigate("/onboarding");
            }
        }
    };

    const handleSignOut = async () => {
        await authClient.signOut();
        setSession(null);
        setUser(null);
    };

    if (loading) return <div>Loading...</div>;

    if (session && user) {
        return (
            <div>
                <h1>Logged in as {user.email}</h1>
                <button onClick={handleSignOut}>Sign Out</button>
            </div>
        );
    }

    return (
        <form onSubmit={handleSubmit}>
            <h1>{isSignUp ? "Create an account" : "Welcome back"}</h1>
            <div className="container">
                <input
                    type="email"
                    placeholder="Enter your email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                />
                <input
                    type="password"
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                />
                {isSignUp ? (
                    <input
                        type="text"
                        placeholder="What should we call you?"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                    ></input>
                ) : (
                    <></>
                )}
                <button type="submit">{isSignUp ? "Create" : "Log In"}</button>
            </div>
            <p>
                {isSignUp ? (
                    <>
                        Already have an account?{" "}
                        <a
                            href="#"
                            onClick={(e) => {
                                e.preventDefault();
                                setIsSignUp(false);
                            }}
                        >
                            Log in
                        </a>
                    </>
                ) : (
                    <>
                        Don't have an account?{" "}
                        <a
                            href="#"
                            onClick={(e) => {
                                e.preventDefault();
                                setIsSignUp(true);
                            }}
                        >
                            Create one
                        </a>
                    </>
                )}
            </p>
        </form>
    );
}
