// import { useState } from 'react'
// import reactLogo from './assets/react.svg'
// import viteLogo from './assets/vite.svg'
// import heroImg from './assets/hero.png'
// import './App.css'

// function App() {
//   const [count, setCount] = useState(0)

//   return (
//     <>
//       <section id="center">
//         <div className="hero">
//           <img src={heroImg} className="base" width="170" height="179" alt="" />
//           <img src={reactLogo} className="framework" alt="React logo" />
//           <img src={viteLogo} className="vite" alt="Vite logo" />
//         </div>
//         <div>
//           <h1>Get started</h1>
//           <p>
//             Edit <code>src/App.jsx</code> and save to test <code>HMR</code>
//           </p>
//         </div>
//         <button
//           className="counter"
//           onClick={() => setCount((count) => count + 1)}
//         >
//           Count is {count}
//         </button>
//       </section>

//       <div className="ticks"></div>

//       <section id="next-steps">
//         <div id="docs">
//           <svg className="icon" role="presentation" aria-hidden="true">
//             <use href="/icons.svg#documentation-icon"></use>
//           </svg>
//           <h2>Documentation</h2>
//           <p>Your questions, answered</p>
//           <ul>
//             <li>
//               <a href="https://vite.dev/" target="_blank">
//                 <img className="logo" src={viteLogo} alt="" />
//                 Explore Vite
//               </a>
//             </li>
//             <li>
//               <a href="https://react.dev/" target="_blank">
//                 <img className="button-icon" src={reactLogo} alt="" />
//                 Learn more
//               </a>
//             </li>
//           </ul>
//         </div>
//         <div id="social">
//           <svg className="icon" role="presentation" aria-hidden="true">
//             <use href="/icons.svg#social-icon"></use>
//           </svg>
//           <h2>Connect with us</h2>
//           <p>Join the Vite community</p>
//           <ul>
//             <li>
//               <a href="https://github.com/vitejs/vite" target="_blank">
//                 <svg
//                   className="button-icon"
//                   role="presentation"
//                   aria-hidden="true"
//                 >
//                   <use href="/icons.svg#github-icon"></use>
//                 </svg>
//                 GitHub
//               </a>
//             </li>
//             <li>
//               <a href="https://chat.vite.dev/" target="_blank">
//                 <svg
//                   className="button-icon"
//                   role="presentation"
//                   aria-hidden="true"
//                 >
//                   <use href="/icons.svg#discord-icon"></use>
//                 </svg>
//                 Discord
//               </a>
//             </li>
//             <li>
//               <a href="https://x.com/vite_js" target="_blank">
//                 <svg
//                   className="button-icon"
//                   role="presentation"
//                   aria-hidden="true"
//                 >
//                   <use href="/icons.svg#x-icon"></use>
//                 </svg>
//                 X.com
//               </a>
//             </li>
//             <li>
//               <a href="https://bsky.app/profile/vite.dev" target="_blank">
//                 <svg
//                   className="button-icon"
//                   role="presentation"
//                   aria-hidden="true"
//                 >
//                   <use href="/icons.svg#bluesky-icon"></use>
//                 </svg>
//                 Bluesky
//               </a>
//             </li>
//           </ul>
//         </div>
//       </section>

//       <div className="ticks"></div>
//       <section id="spacer"></section>
//     </>
//   )
// }

// export default App
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

        // const result = isSignUp
        //     ? await authClient.signUp.email({
        //           name: email.split("@")[0] || "User",
        //           email,
        //           password,
        //       })
        //     : await authClient.signIn.email({ email, password });

        // if (isSignUp) {
        //     // await fetch("http://localhost:5000/api/login", {
        //     //     method: "POST",
        //     //     body: JSON.stringify({ email }),
        //     //     headers: {
        //     //         "Content-type": "application/json; charset=UTF-8",
        //     //     },
        //     // })
        //     //     .then((response) => response.json())
        //     //     .then((json) => console.log(json));
        // }

        // if (result.error) {
        //     alert(result.error.message);
        //     return;
        // }

        // const sessionResult = await authClient.getSession();
        // if (sessionResult.data?.session && sessionResult.data?.user) {
        //     setSession(sessionResult.data.session);
        //     setUser(sessionResult.data.user);
        // }
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
