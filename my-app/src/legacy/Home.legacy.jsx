import "../styles/Dashboard.css";

const priorityTasks = [
    {
        title: "Finalize sprint priorities",
        summary: "Review blockers, nudge deadlines, and lock tomorrow's top 3.",
        status: "In motion",
        statusTone: "warm",
        due: "Today, 4:30 PM",
    },
    {
        title: "Prep onboarding checklist",
        summary: "Turn loose notes into a reusable flow for new teammates.",
        status: "Needs focus",
        statusTone: "cool",
        due: "Tomorrow, 10:00 AM",
    },
    {
        title: "Organize personal errands",
        summary: "Batch smaller tasks into one evening route to save time.",
        status: "Low lift",
        statusTone: "mint",
        due: "Friday",
    },
];

const metrics = [
    { value: "18", label: "Tasks sorted this week" },
    { value: "6", label: "High-priority items cleared" },
    { value: "82%", label: "Focus score" },
];

const workflow = [
    "Capture every task in one list",
    "Group by urgency, energy, and impact",
    "Start with the one move that unlocks the rest",
];

export default function Home() {
    return (
        <main className="dashboard-page">
            <section className="dashboard-hero">
                <div className="dashboard-copy">
                    <p className="dashboard-kicker">Task Priority Sorter</p>
                    <h1>Build a calmer plan before the day gets noisy.</h1>
                    <p className="dashboard-intro">
                        Your dashboard keeps urgent work visible, lighter tasks
                        grouped, and the next best action easy to spot.
                    </p>

                    <div className="dashboard-actions">
                        <button type="button" className="dashboard-button primary">
                            Create task
                        </button>
                        <button type="button" className="dashboard-button secondary">
                            View schedule
                        </button>
                    </div>
                </div>

                <aside className="dashboard-spotlight">
                    <p className="eyebrow">Today&apos;s focus lane</p>
                    <h2>Ship the important work first.</h2>
                    <div className="spotlight-grid">
                        {metrics.map((item) => (
                            <article key={item.label} className="metric-card">
                                <strong>{item.value}</strong>
                                <span>{item.label}</span>
                            </article>
                        ))}
                    </div>
                </aside>
            </section>

            <section className="dashboard-content">
                <div className="task-panel">
                    <div className="section-heading">
                        <div>
                            <p className="eyebrow">Priority queue</p>
                            <h2>What deserves attention next</h2>
                        </div>
                        <span className="badge">3 active groups</span>
                    </div>

                    <div className="task-list">
                        {priorityTasks.map((task) => (
                            <article key={task.title} className="task-card">
                                <div className="task-card-top">
                                    <span className={`status-pill ${task.statusTone}`}>
                                        {task.status}
                                    </span>
                                    <span className="task-due">{task.due}</span>
                                </div>
                                <h3>{task.title}</h3>
                                <p>{task.summary}</p>
                            </article>
                        ))}
                    </div>
                </div>

                <aside className="workflow-panel">
                    <div className="section-heading">
                        <div>
                            <p className="eyebrow">Momentum map</p>
                            <h2>Your sorting rhythm</h2>
                        </div>
                    </div>

                    <ol className="workflow-list">
                        {workflow.map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ol>

                    <div className="note-card">
                        <p className="eyebrow">Quick note</p>
                        <p>
                            Try keeping your highest-effort task inside your
                            first 90 minutes. The rest of the list gets easier
                            once that one moves.
                        </p>
                    </div>
                </aside>
            </section>
        </main>
    );
}
