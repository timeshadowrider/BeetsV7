import { RouteObject } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import WebPlayer from "./pages/WebPlayer";
import VolumioBuilder from "./pages/VolumioBuilder";
import Logs from "./pages/Logs";
import PipelineControl from "./pages/PipelineControl";
import SlskdSearch from "./pages/SlskdSearch";

export const routes: RouteObject[] = [
  { path: "/", element: <Dashboard /> },
  { path: "/player", element: <WebPlayer /> },
  { path: "/volumio", element: <VolumioBuilder /> },
  { path: "/slskd", element: <SlskdSearch /> },
  { path: "/logs", element: <Logs /> },
  { path: "/pipeline", element: <PipelineControl /> }
];
