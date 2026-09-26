"use client";

import UploadPage from "../../views/UploadPage";
import { useApp } from "../AppContext";

export default function Upload() {
  const { health, refresh } = useApp();
  return <UploadPage onSaved={refresh} demoMode={health?.demo_mode ?? true} />;
}
