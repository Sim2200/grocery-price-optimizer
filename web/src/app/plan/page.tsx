"use client";

import PlanPage from "../../views/PlanPage";
import { useApp } from "../AppContext";

export default function Plan() {
  const { dataVersion } = useApp();
  return <PlanPage version={dataVersion} />;
}
