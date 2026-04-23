import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/home", label: "Home" },
  { to: "/kanban", label: "Kanban" },
  { to: "/statistics", label: "Statistics" },
  { to: "/linking", label: "Linking" },
  { to: "/preferences", label: "Preferences" },
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
