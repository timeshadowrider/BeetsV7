import { useRoutes, Link, useLocation } from "react-router-dom";
import { routes } from "./router";
import Layout from "./components/Layout";

export default function App() {
  const element = useRoutes(routes);
  const loc = useLocation();

  const tabs = [
    { to: "/", label: "Dashboard" },
    { to: "/player", label: "Web Player" },
    { to: "/volumio", label: "Volumio Builder" },
    { to: "/slskd", label: "SLSKD Search" },
    { to: "/logs", label: "Logs" },
    { to: "/pipeline", label: "Pipeline" }
  ];

  return (
    <Layout
      nav={
        <nav className="flex gap-3">
          {tabs.map(t => (
            <Link
              key={t.to}
              to={t.to}
              className={`px-3 py-1 rounded-full text-sm ${
                loc.pathname === t.to
                  ? "bg-accent text-black"
                  : "bg-card text-gray-300 hover:bg-zinc-700"
              }`}
            >
              {t.label}
            </Link>
          ))}
        </nav>
      }
    >
      {element}
    </Layout>
  );
}
