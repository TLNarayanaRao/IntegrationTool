/// <reference types="vite/client" />

interface Window {
  fabricDesktop?: {
    isDesktop: boolean;
    platform: string;
    saveFile(options: { path?: string; filename: string; bytes: number[]; filters?: Array<{ name: string; extensions: string[] }> }): Promise<string | null>;
    saveProjectFolder(options: { path?: string; folderName: string; project: unknown }): Promise<string | null>;
    openProject(): Promise<{ path: string; name: string; bytes?: number[]; project?: unknown; kind?: "file" | "folder" } | null>;
    selectCodeArtifact(kind: "java" | "python"): Promise<{ path: string; name: string; kind: string } | null>;
  };
}
