import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/home", label: "Dashboard" },
  { to: "/kanban", label: "Kanban" },
  { to: "/statistics", label: "Insights" },
  { to: "/linking", label: "Connections" },
  { to: "/preferences", label: "Settings" },
];

export default function PageNav() {
  return (
    <nav aria-label="Primary" className="page-nav">
      {LINKS.map((link) => (
        <NavLink
          className={({ isActive }) =>
            `page-nav-link${isActive ? " page-nav-link-active" : ""}`
          }
          key={link.to}
          to={link.to}
        >
          {link.label}
        </NavLink>
      ))}
    </nav>
  );
}
