import React from "react";
import { Waypoints } from "lucide-react";

export default function DataNodeIcon({ className = "" }: { className?: string }) {
  return <span className={`fabric-data-icon ${className}`} aria-hidden="true"><Waypoints/></span>;
}
